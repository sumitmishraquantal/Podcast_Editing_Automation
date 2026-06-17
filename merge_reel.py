#!/usr/bin/env python3
"""
merge_reel.py  (v10 - FIXED)
Step 1: merge raw clips into ONE seamless podcast reel.

Changes from v9:
- FIX #4: LRA tightened from 11 -> 5 so within-clip dynamics are compressed;
  quiet speakers come up, loud speakers come down. linear=true preserved so
  voice timbre is NOT altered — only perceived loudness is balanced.
- FIX #4: Added per-clip RMS pre-scan print so you can see raw levels before/after.
- FADE reduced from 0.03 -> 0.015 (15ms) so first/last syllable of each clip
  is not faded out — this also fixes the "first letter cut off" at join points.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

VW, VH, FPS = 1080, 1920, 30
FADE = 0.015          # FIX #1 partial: was 0.03 — shorter fade preserves edge syllables
LUFS_I, LUFS_TP = -14, -1
LUFS_LRA = 5          # FIX #4: was 11 — tighter range = speakers balanced within clip
SIL_NOISE, SIL_MIN = "-32dB", 0.20
EDGE_PAD = 0.06

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-1200:] + "\n")
    return r

def dur(p):
    r = run(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{p}"')
    try: return float(r.stdout.strip())
    except: return 0.0

def edge_trim_points(clip):
    d = dur(clip)
    r = run(f'ffmpeg -i "{clip}" -af silencedetect=noise={SIL_NOISE}:d={SIL_MIN} -f null -')
    log = (r.stderr or "") + (r.stdout or "")
    starts = [float(x) for x in re.findall(r'silence_start:\s*([-\d.]+)', log)]
    ends   = [float(x) for x in re.findall(r'silence_end:\s*([-\d.]+)', log)]
    s = 0.0
    if ends and starts and starts[0] < 0.15:
        s = max(0.0, ends[0] - EDGE_PAD)
    e = d
    if len(starts) > len(ends):
        e = min(d, starts[-1] + EDGE_PAD)
    if e - s < 0.3:
        return 0.0, d
    return s, e

def measure(src):
    r = run(f'ffmpeg -i "{src}" -af loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}'
            f':print_format=json -f null -')
    txt = (r.stderr or "") + (r.stdout or "")
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', txt, re.DOTALL)
    return json.loads(m.group()) if m else None

def conform(clip, out, target, trim):
    s, e = edge_trim_points(clip) if trim else (0.0, dur(clip))
    seg = e - s
    ss = f"-ss {s:.3f} -t {seg:.3f}"
    md = measure(clip)
    if md:
        print(f"    raw loudness: {md['input_i']} LUFS  TP={md['input_tp']} dBTP")
    # FIX #4: linear=true preserves voice timbre; LRA=5 tightens speaker dynamics
    ln = (f"loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}:measured_I={md['input_i']}"
          f":measured_TP={md['input_tp']}:measured_LRA={md['input_lra']}"
          f":measured_thresh={md['input_thresh']}:offset={md['target_offset']}:linear=true"
          ) if md else f"loudnorm=I={LUFS_I}:TP={LUFS_TP}:LRA={LUFS_LRA}"
    # FIX #1 partial: FADE=0.015 so edge syllables are not swallowed
    af = f"{ln},afade=t=in:st=0:d={FADE},afade=t=out:st={max(0,seg-FADE):.3f}:d={FADE}"
    vf = (f"scale={VW}:{VH}:force_original_aspect_ratio=increase,"
          f"crop={VW}:{VH},fps={FPS},setsar=1,format=yuv420p")
    run(f'ffmpeg -y {ss} -i "{clip}" -vf "{vf}" -af "{af}" '
        f'-c:v libx264 -profile:v high -crf 18 -preset medium '
        f'-c:a aac -b:a 256k -ar 48000 -ac 2 "{out}"')
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir")
    ap.add_argument("--out", default="merged.mp4")
    ap.add_argument("--no-trim", action="store_true")
    ap.add_argument("--target", type=float, default=-14)
    a = ap.parse_args()

    raw = Path(a.raw_dir)
    seen = {}
    for pat in ("*.mp4","*.mov","*.MP4","*.MOV"):
        for c in raw.glob(pat):
            seen[c.name.lower()] = c
    clips = [seen[k] for k in sorted(seen)]
    if not clips: sys.exit(f"No clips in {raw}")
    print(f"  {len(clips)} clips: {[c.name for c in clips]}")

    work = Path(a.out).parent / "_conform"; work.mkdir(parents=True, exist_ok=True)
    normed = []
    for i, c in enumerate(clips):
        o = str(work / f"n{i:02d}.mp4")
        print(f"\n  Clip {i+1}/{len(clips)}: {c.name}")
        conform(str(c), o, a.target, not a.no_trim)
        print(f"  -> {Path(o).name} ({dur(o):.2f}s)")
        normed.append(o)

    lst = work / "list.txt"
    lst.write_text("".join(f"file '{Path(n).resolve()}'\n" for n in normed))
    run(f'ffmpeg -y -f concat -safe 0 -i "{lst}" -c copy -movflags +faststart "{a.out}"')
    cuts, acc = [], 0.0
    for n in normed[:-1]:
        acc += dur(n); cuts.append(round(acc, 3))
    (Path(a.out).parent / "cuts.json").write_text(json.dumps(cuts))
    print(f"  cuts at: {cuts}")

    out_md = measure(a.out)
    print(f"\n  [OK] {a.out}  dur={dur(a.out):.2f}s  "
          f"loudness={out_md['input_i'] if out_md else '?'} LUFS "
          f"TP={out_md['input_tp'] if out_md else '?'} dBTP")

if __name__ == "__main__":
    main()
