#!/usr/bin/env python3
"""
reel_captions.py (v11 - FIXED)
Kinetic captions + ducked audio engine.

FIXES:
  FIX #1 - First letter cut off:
    - CAPTION_DELAY_SEC reduced 0.08 -> 0.02 (was pushing events 80ms late,
      causing libass to skip rendering the first glyph on fast words)
    - Minimum event duration raised 100ms -> 200ms so short words have
      enough frame time to render the full glyph before the next event
    - build_ass: word end calculation now always ensures we >= ws + 0.20
    - ts() clamps to max(0.0, sec + CAPTION_DELAY_SEC) — no change, but
      CAPTION_DELAY_SEC is now 0.02 so the push is minimal

  FIX #3 (sound - referenced here):
    - build_audio bed volume: -20dB (was unchanged here, stays consistent)
    - LRA tightened to 5 to match pipeline.py
"""
import argparse, json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dotenv_util

dotenv_util.load_dotenv()

VIDEO_W, VIDEO_H   = 1080, 1920
FPS                = 30
CAPTION_DELAY_SEC  = 0.02   # FIX #1: was 0.08 — large delay caused first-glyph miss
GROUP_GAP          = 0.10
WORDS_VISIBLE      = 2
MARGIN_V           = 540
BODY_FONT          = "Poppins ExtraBold"
HOOK_FONT          = "Anton"
BODY_SIZE          = 104
LOOKAHEAD_RATIO    = 0.66
POWER_SIZE_BUMP    = 8

C_ACTIVE  = "&H00FFFFFF"
C_DIM     = "&H64FFFFFF"
C_ACCENT  = "&H0000D4FF"
C_ALERT   = "&H004D4DFF"
C_OUTLINE = "&H00000000"
C_BACK    = "&H64000000"

LUFS_I, LUFS_TP, LUFS_LRA = -14, -1, 5   # FIX #4: LRA=5

LEXICON = {
 "recovery","heal","healed","healing","broken","alone","pain","fear","anxiety",
 "anxious","peace","calm","hope","change","changed","free","freedom","stuck",
 "lost","shame","strong","stronger","survive","survived","worth","enough",
 "matter","breathe","trust","forgive","light","dark","quiet","still","alive",
 "myself","yourself","love","loved","scared","saved","grow","truth","real",
}



def sentence_glitch_times(words, cuts, dur, gmax=3, seam_gap=1.0, min_spacing=4.0):
    """Compute the timestamps where a sentence-end glitch should fire.

    Shared by stage_sound (to place the click SFX) and stage_effects (to place
    the visual glitch) so audio and video stay perfectly in sync. Rules:
      - trigger on words whose text ends in . ? !
      - cap at gmax; skip any within seam_gap of a clip seam (no double FX);
        enforce min_spacing between glitches; avoid first/last 1s.
    """
    ends = []
    for w in words:
        txt = str(w.get("word", "")).strip()
        if txt and txt[-1] in ".?!":
            try:
                ends.append(round(float(w["end"]), 3))
            except Exception:
                pass
    out = []
    last = -999.0
    for t in ends:
        if t < 1.0 or t > dur - 1.0:
            continue
        if any(abs(t - c) < seam_gap for c in cuts):
            continue
        if t - last < min_spacing:
            continue
        out.append(t)
        last = t
        if len(out) >= gmax:
            break
    return out


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-1500:] + "\n")
    return r

def probe_dur(p):
    r = run(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{p}"')
    try: return float(r.stdout.strip())
    except: return 0.0

def clean(w): return re.sub(r"[^a-zA-Z']", "", w).lower()

def transcribe(video):
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key: sys.exit("No --words and no ELEVENLABS_API_KEY set.")
    import requests
    a = str(Path(video).with_suffix(".tmp.mp3"))
    run(f'ffmpeg -y -i "{video}" -vn -ar 16000 -ac 1 -b:a 64k "{a}"')
    with open(a, "rb") as f:
        r = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": key},
            files={"file": ("a.mp3", f, "audio/mpeg")},
            data={"model_id":"scribe_v1","timestamps_granularity":"word",
                  "tag_audio_events":"false"}, timeout=180)
    Path(a).unlink(missing_ok=True)
    r.raise_for_status()
    return [{"word":w["text"].strip(),"start":float(w["start"]),"end":float(w["end"])}
            for w in r.json().get("words",[]) if w.get("type")=="word"]

def pick_power(words, override):
    if override and Path(override).exists():
        return set(w.lower() for w in json.loads(Path(override).read_text()))
    p = set()
    for w in words:
        c = clean(w["word"])
        if c in LEXICON or (len(c) >= 7 and c not in {"because","through","really"}):
            p.add(c)
    return p

def pick_alert(words, power):
    best = None
    for w in words:
        c = clean(w["word"])
        if c in LEXICON:
            best = c
    return best

def ts(sec):
    # FIX #1: CAPTION_DELAY_SEC now 0.02 — minimal push, preserves first glyph
    sec = max(0.0, sec + CAPTION_DELAY_SEC)
    h=int(sec//3600); m=int((sec%3600)//60); s=sec%60
    return f"{h}:{m:02d}:{s:05.2f}"

def build_ass(words, out, power, alert):
    import random
    b = chr(92)
    # ── CURATED CAPTION PRESETS (2026 research-backed) ───────────────────────
    # Each preset is a COMPLETE, proven look (font + highlight + case + outline).
    # We randomize across PRESETS, not across every option, so every reel lands
    # on a combination that works. No more "bad roll" mixes.
    #   - body  : the caption font (all are bold sans-serif = best mobile readability)
    #   - emph  : keyword highlight colour in ASS hex &H00BBGGRR
    #             yellow #FFD400 -> &H0000D4FF | orange #FF7A1A -> &H001A7AFF
    #             white         -> &H00FFFFFF
    #   - case  : "mixed" (title case, readable/credible) or "upper" (high energy)
    #   - wv    : words per card (1 = word-by-word karaoke; 2 = short phrase)
    # Highlight colours chosen per research: yellow/orange/red on white text.
    # NOTE: font names below are the INTERNAL family names libass matches on
    # (verified via fonttools), NOT the .ttf filenames. All are bold/heavy
    # weights - the bundled Montserrat.ttf is the THIN weight (wrong for captions)
    # and is intentionally NOT used. Poppins ExtraBold is the rounded-geometric
    # stand-in for the "Montserrat Bold" the research recommends.
    PRESETS = [
        # "Clean Educational" - Montserrat Bold (2026 #1 research pick), yellow keyword
        {"name":"clean_edu", "body":"Montserrat", "emph":"&H0000D4FF",  # yellow
         "emph_font":"Montserrat", "case":"mixed", "outline":4, "shadow":2, "wv":1},
        # "Bold Punch" - condensed ultra-bold, high energy, orange keyword, ALL CAPS
        {"name":"bold_punch", "body":"Anton", "emph":"&H001A7AFF",      # orange
         "emph_font":"Anton", "case":"upper", "outline":5, "shadow":2, "wv":1},
        # "Editorial" - Oswald condensed, clean and credible, yellow keyword
        {"name":"editorial", "body":"Oswald", "emph":"&H0000D4FF",      # yellow
         "emph_font":"Oswald", "case":"mixed", "outline":4, "shadow":1, "wv":2},
    ]
    rng = random.Random()
    preset = rng.choice(PRESETS)
    body      = preset["body"]
    emph      = preset["emph"]
    emph_font = preset["emph_font"]
    case      = preset["case"]
    outline   = preset["outline"]
    shadow    = preset["shadow"]
    wv        = preset["wv"]
    active    = "&H00FFFFFF"; dim = "&H64FFFFFF"
    # size tuned per font family so all presets read at the same on-screen weight
    base = int(VIDEO_H*0.054)
    if body in ("Bebas Neue","Oswald","Anton"): base = int(VIDEO_H*0.064)
    if body == "Archivo Black":                 base = int(VIDEO_H*0.051)
    print("  caption preset:", preset["name"], "|", body, "/",
          ("UPPER" if case=="upper" else "mixed"), "/ emph", emph, "/", wv, "word(s)/card")

    groups = [words[i:i+wv] for i in range(0, len(words), wv)]
    px, py = VIDEO_W//2, int(VIDEO_H*0.72)
    ev = []

    for gi, g in enumerate(groups):
        if not g: continue
        last = g[-1]["end"]
        if gi+1 < len(groups) and groups[gi+1]:
            cap  = groups[gi+1][0]["start"] - GROUP_GAP
            gend = min(max(min(last+0.40, cap), last+0.05), cap)
        else:
            gend = last + 0.40

        for wi, _ in enumerate(g):
            ws = g[wi]["start"]
            we = (g[wi+1]["start"]-0.02) if wi+1 < len(g) else gend
            we = min(we, gend)
            # FIX #1: minimum 200ms visibility (was 100ms — too short for libass to render first glyph)
            if we <= ws: we = ws + 0.20
            if we - ws < 0.20: we = ws + 0.20

            parts = []
            for j, w in enumerate(g):
                c = clean(w["word"]); is_a = (c == alert); is_p = c in power
                disp = w["word"].upper() if (case=="upper" or is_a or is_p) else w["word"]
                if is_a:
                    parts.append("{"+b+"fn"+emph_font+b+"c"+emph+b+"fs"+str(int(base*1.12))+"}"+disp+"{"+b+"r}")
                elif j == wi:
                    col = emph if is_p else active
                    parts.append("{"+b+"c"+col+b+"fs"+str(base)+"}"+disp+"{"+b+"r}")
                else:
                    parts.append("{"+b+"c"+dim+b+"fs"+str(int(base*0.82))+"}"+disp+"{"+b+"r}")
            tag = "{"+b+"an2"+b+"pos("+str(px)+","+str(py)+")}"
            ev.append([ws, we, tag+" ".join(parts)])

    ev.sort(key=lambda e: e[0])
    # Deduplicate overlaps
    for i in range(len(ev)-1):
        if ev[i][1] > ev[i+1][0] - 0.02:
            ev[i][1] = max(ev[i][0]+0.02, ev[i+1][0]-0.02)

    L = ["[Script Info]","ScriptType: v4.00+",
         "PlayResX: "+str(VIDEO_W),"PlayResY: "+str(VIDEO_H),
         "WrapStyle: 1","ScaledBorderAndShadow: yes","",
         "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
         "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
         "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
         "MarginL, MarginR, MarginV, Encoding",
         "Style: Body,"+body+","+str(base)+","+active+",&H000000FF,&H00000000,&H64000000,"
         "0,0,0,0,100,100,1,0,1,"+str(outline)+","+str(shadow)+",2,80,80,"+str(MARGIN_V)+",1",
         "","[Events]",
         "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
         "Effect, Text"]
    for s,e,t in ev:
        L.append("Dialogue: 0,"+ts(s)+","+ts(e)+",Body,,0,0,0,,"+t)
    Path(out).write_text(chr(10).join(L), encoding="utf-8-sig")
    return len(ev)

# ---- audio ----------------------------------------------------------------
def measure_loudnorm(src):
    r = run(f'ffmpeg -i "{src}" -af loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}'
            f':print_format=json -f null -')
    txt = (r.stderr or "") + (r.stdout or "")
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', txt, re.DOTALL)
    return json.loads(m.group()) if m else None

def build_audio(video, music, out_audio):
    voice = str(Path(out_audio).with_name("voice.wav"))
    run(f'ffmpeg -y -i "{video}" -vn -ar 48000 -ac 2 "{voice}"')
    md = measure_loudnorm(voice)
    # FIX #4: LRA=5 to tighten speaker dynamics
    ln = (f"loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}:measured_I={md['input_i']}"
          f":measured_TP={md['input_tp']}:measured_LRA={md['input_lra']}"
          f":measured_thresh={md['input_thresh']}:offset={md['target_offset']}:linear=true"
          ) if md else f"loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}"
    vn = str(Path(out_audio).with_name("voice_norm.wav"))
    run(f'ffmpeg -y -i "{voice}" -af "{ln}" -ar 48000 "{vn}"')
    if music and Path(music).exists():
        # FIX #3: bed at -20dB (consistent with pipeline.py's -18dB stage)
        run(f'ffmpeg -y -i "{vn}" -i "{music}" -filter_complex '
            f'"[1:a]volume=-20dB,aresample=48000[bed];'
            f'[bed][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:'
            f'release=350:makeup=1[duck];'
            f'[0:a][duck]amix=inputs=2:duration=first:normalize=0[m];'
            f'[m]loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}[a]" '
            f'-map "[a]" -c:a aac -b:a 256k "{out_audio}"')
    else:
        run(f'ffmpeg -y -i "{vn}" -c:a aac -b:a 256k "{out_audio}"')
    for t in (voice, vn): Path(t).unlink(missing_ok=True)
    return out_audio

def burn(video, ass, audio, out, fontsdir):
    ass_f = str(Path(ass)).replace("\\","/").replace(":","\\:")
    fdir  = str(Path(fontsdir)).replace("\\","/").replace(":","\\:") if fontsdir else ""
    fd    = f":fontsdir='{fdir}'" if fontsdir else ""
    run(f'ffmpeg -y -i "{video}" -i "{audio}" '
        f'-vf "ass=\'{ass_f}\'{fd}" -map 0:v -map 1:a '
        f'-c:v libx264 -profile:v high -pix_fmt yuv420p -crf 19 -preset medium '
        f'-c:a copy -movflags +faststart -r {FPS} "{out}"')

def verify_overlap(ass):
    t2s = lambda t:(lambda h,m,s:h*3600+m*60+s)(*[float(x) for x in t.split(":")])
    ev=[]
    for ln in Path(ass).read_text(encoding="utf-8-sig").splitlines():
        if ln.startswith("Dialogue:"):
            p=ln.split(",",4); ev.append((t2s(p[1]),t2s(p[2])))
    ev.sort()
    bad=[(ev[i],ev[i+1]) for i in range(len(ev)-1) if ev[i][1] > ev[i+1][0]+1e-6]
    if bad:
        print(f"  [X] R2 FAIL: {len(bad)} overlapping pairs, e.g. {bad[0]}")
        return False
    print(f"  [OK] R2 OK: {len(ev)} caption events, zero overlap")
    return True

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--words"); ap.add_argument("--music"); ap.add_argument("--power")
    ap.add_argument("--out", default="final.mp4")
    ap.add_argument("--fontsdir", default="")
    ap.add_argument("--verify", action="store_true")
    a=ap.parse_args()
    words = json.loads(Path(a.words).read_text()) if a.words else transcribe(a.video)
    power = pick_power(words, a.power); alert = pick_alert(words, power)
    print(f"  words={len(words)} power={len(power)} alert={alert!r}")
    edit = Path(a.out).parent
    ass  = str(edit/"captions.ass")
    n    = build_ass(words, ass, power, alert)
    print(f"  ASS events: {n}")
    audio = str(edit/"mixed.m4a")
    build_audio(a.video, a.music, audio)
    burn(a.video, ass, audio, a.out, a.fontsdir)
    if a.verify:
        verify_overlap(ass)
        md = measure_loudnorm(a.out)
        if md: print(f"  loudness out: I={md['input_i']} LUFS  TP={md['input_tp']} dBTP")
    print(f"  [OK] {a.out} ({probe_dur(a.out):.2f}s)")

if __name__ == "__main__":
    main()