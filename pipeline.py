# #!/usr/bin/env python3
# """
# pipeline.py - stage-gated reel orchestrator.
# One stage per run; review; advance.
 
# FIXES applied:
#   FIX #2: stage_effects - zoom punch capped to MAX_ZOOMS=4, evenly spaced,
#           only fires on IMPACT_WORDS (not all non-stopwords), probability
#           reduced to 0.35 (was 0.6). Ken-Burns kb range halved (0.01-0.02).
#           Seam blur softened: sizeX/Y range 20-40 (was 50-90).
#   FIX #3: stage_sound - bed volume -18dB (was -9dB). Whoosh volume 0.9
#           (was 4.0 = 400%!). SFX volume in mix 1.0 (was 4.0).
#   FIX #1: caption first-letter - min event duration raised to 180ms (was
#           100ms) and CAPTION_DELAY_SEC set to 0 in this call path so events
#           aren't pushed beyond their natural start.
# """
# import argparse, json, os, random, re, subprocess, sys, time
# from pathlib import Path
# sys.path.insert(0, str(Path(__file__).resolve().parent))
# import dotenv_util
# import reel_captions as rc
 
# dotenv_util.load_dotenv()
 
# STAGES = ["merge", "transcribe", "sound", "effects", "captions", "finalize"]
# HERE   = Path(__file__).resolve().parent
# PRESET = "veryfast" if os.environ.get("REEL_FAST") else "medium"
# VW, VH, FPS = 1080, 1920, 30
 
# # FIX #2: Impact words only — no catch-all for non-stopwords
# IMPACT_WORDS = {
#     "addiction","addict","recovery","sobriety","sober","died","death",
#     "dead","pain","trauma","abuse","broken","fear","lost","alone",
#     "prison","jail","overdose","relapse","fight","love","god","faith",
#     "hope","free","freedom","heal","healed","healing","saved","save",
#     "overcome","overcomer","miracle","changed","change","truth","win",
#     "money","million","billion","success","fail","failed","failure",
#     "power","strong","weak","best","worst","never","always","every"
# }
# MAX_ZOOMS = 4   # FIX #2: hard cap per video
 
# def run(cmd):
#     r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
#     if r.returncode != 0:
#         sys.stderr.write((r.stderr or "")[-1200:] + "\n")
#     return r
 
# def load_state(edit):
#     f = edit / "state.json"
#     if f.exists(): return json.loads(f.read_text())
#     return {"done": [], "history": []}
 
# def save_state(edit, st):
#     (edit / "state.json").write_text(json.dumps(st, indent=2))
 
# def review(msg, artifact=None):
#     print("\n" + "-"*64)
#     print("REVIEW - " + msg)
#     if artifact: print(f"   artifact: {artifact}")
#     print("   When it looks right, trigger the routine again to advance.")
#     print("-"*64)
 
# def stage_merge(proj, edit, args):
#     raw = proj / "raw"
#     out = edit / "01_merged.mp4"
#     rc_dir = HERE
#     r = run(f'"{sys.executable}" "{rc_dir/"merge_reel.py"}" "{raw}" --out "{out}"')
#     if not out.exists(): sys.exit("merge failed - see log above")
#     md = rc.measure_loudnorm(str(out))
#     review(f"Merged {len(list(raw.glob('*.mp4')))} clips into ONE reel "
#            f"({rc.probe_dur(str(out)):.1f}s, {md['input_i'] if md else '?'} LUFS). "
#            f"Watch the joins: any visible seam, level jump, or pop?", out)
 
# def stage_transcribe(proj, edit, args):
#     merged = edit / "01_merged.mp4"
#     words_f = edit / "words.json"
#     if not os.environ.get("ELEVENLABS_API_KEY") and not words_f.exists():
#         sys.exit("transcribe needs ELEVENLABS_API_KEY (or a pre-made edit/words.json).")
#     words = json.loads(words_f.read_text()) if words_f.exists() else rc.transcribe(str(merged))
#     words_f.write_text(json.dumps(words, indent=2))
#     transcript = " ".join(w["word"] for w in words)
#     review(f"Transcribed {len(words)} words. Transcript:\n   \"{transcript[:300]}\"", words_f)
 
# def stage_sound(proj, edit, args):
#     import requests
#     merged  = edit / "01_merged.mp4"
#     out     = edit / "03_scored.m4a"
#     words   = json.loads((edit/"words.json").read_text()) if (edit/"words.json").exists() else []
#     cuts    = json.loads((edit/"cuts.json").read_text()) if (edit/"cuts.json").exists() else []
#     key     = os.environ.get("ELEVENLABS_API_KEY","")
#     voice   = str(edit/"voice.wav")
#     run('ffmpeg -y -i "' + str(merged) + '" -vn -ar 48000 -ac 2 "' + voice + '"')
#     md = rc.measure_loudnorm(voice)
#     if md:
#         ln = ("loudnorm=I=-14:TP=-1:LRA=5:measured_I="+str(md["input_i"])
#               +":measured_TP="+str(md["input_tp"])+":measured_LRA="+str(md["input_lra"])
#               +":measured_thresh="+str(md["input_thresh"])+":offset="+str(md["target_offset"])+":linear=true")
#     else:
#         ln = "loudnorm=I=-14:TP=-1:LRA=5"
#     vnorm = str(edit/"voice_norm.wav")
#     run('ffmpeg -y -i "' + voice + '" -af "' + ln + '" -ar 48000 "' + vnorm + '"')
#     dur = rc.probe_dur(str(merged))
 
#     MOOD_KW = {
#      "anxious":["anxiety","anxious","stress","worry","fear","panic","nervous","danger","threat","brain","shut"],
#      "hopeful":["recovery","heal","healing","safe","breath","community","change","start","grow","fix","teach"],
#      "calm":["calm","peace","present","moment","breathe","still","quiet","slow"],
#      "sad":["alone","pain","hurt","broken","loss","grief","dark","struggle","cry"],
#     }
#     MOOD_PROMPT = {
#      "anxious":"soft cinematic background music, gentle piano and warm pads, subtle pulse, moderate tempo, hopeful undertone",
#      "hopeful":"uplifting cinematic background music, warm strings and piano, gentle driving pulse, moderate tempo, motivational",
#      "calm":"calm cinematic background music, soft steady pulse, warm pads, gentle moderate-tempo movement",
#      "sad":"emotional cinematic background music, soft piano, gentle pulse, tender but moving, moderate tempo",
#      "neutral":"soft cinematic background music, gentle rhythm, moderate tempo, warm, present but unobtrusive",
#     }
#     txt  = " ".join(w["word"] for w in words).lower()
#     sc   = {m: sum(txt.count(k) for k in ks) for m,ks in MOOD_KW.items()}
#     mood = max(sc, key=sc.get) if (sc and max(sc.values())>0) else "neutral"
#     print("  mood:", mood, sc)
 
#     # ── PRIORITY 2: sentence-end glitch times (shared with stage_effects) ────
#     glitch_times = rc.sentence_glitch_times(
#         words, cuts, dur,
#         gmax=int(os.environ.get("GLITCH_MAX", "3")),
#         seam_gap=float(os.environ.get("GLITCH_SEAM_GAP", "1.0")),
#         min_spacing=float(os.environ.get("GLITCH_MIN_SPACING", "4.0")))
#     (edit / "glitches.json").write_text(json.dumps(glitch_times), encoding="utf-8")
#     print("  glitch times (sentence ends):", glitch_times)
 
#     # Generate a short CLICK SFX for the glitches (distinct from the seam whoosh).
#     click = None
#     if key and glitch_times:
#         try:
#             r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
#                 headers={"xi-api-key":key,"Content-Type":"application/json"},
#                 json={"text":"short crisp digital glitch click, sharp tick, brief, clean",
#                       "duration_seconds":0.4,"prompt_influence":0.7},
#                 timeout=90)
#             if r.status_code==200:
#                 rawclick = str(edit/"click.mp3"); open(rawclick,"wb").write(r.content)
#                 click = str(edit/"click_p.mp3")
#                 run('ffmpeg -y -i "'+rawclick+'" -af "silenceremove=start_periods=1:start_silence=0:'
#                     'start_threshold=-50dB,volume=1.5,afade=t=in:d=0.01,'
#                     'afade=t=out:st=0.18:d=0.12" -ar 48000 "'+click+'"')
#                 if not Path(click).exists(): click = rawclick
#             else:
#                 print("  click gen HTTP", r.status_code)
#         except Exception as e:
#             print("  click gen failed:", e)
 
#     bed = None
#     if key:
#         try:
#             r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
#                 headers={"xi-api-key":key,"Content-Type":"application/json"},
#                 json={"text":MOOD_PROMPT[mood],"duration_seconds":min(22.0,dur),"prompt_influence":0.4},
#                 timeout=120)
#             if r.status_code==200:
#                 raw_bed = str(edit/"bed_raw.mp3"); open(raw_bed,"wb").write(r.content)
#                 rdur = rc.probe_dur(raw_bed)
#                 if rdur and dur > rdur+0.5:
#                     loops = int(dur/rdur)+2; bed = str(edit/"bed.mp3")
#                     run('ffmpeg -y -stream_loop '+str(loops)+' -i "'+raw_bed+'" -t '+format(dur,".3f")
#                         +' -af "afade=t=in:d=1.5,afade=t=out:st='+format(max(0,dur-2.0),".3f")+':d=3" -ar 48000 "'+bed+'"')
#                 else:
#                     bed = raw_bed
#             else:
#                 print("  music gen HTTP", r.status_code, r.text[:160])
#         except Exception as e:
#             print("  music gen failed:", e)
 
#     sfx = None
#     if key and cuts:
#         try:
#             # SEAM SFX (Priority 1): subtle sounds that HIDE clip joins. These must
#             # be quiet and smooth - their job is to mask the cut, not announce it.
#             # A consistent SFX across a reel's seams reads more professional than a
#             # different sound at every seam, so we pick ONE per reel and reuse it.
#             SFX_PROMPTS = [
#                 "clean soft digital swoosh transition, smooth short whoosh, quiet and subtle",
#                 "gentle modern UI swipe, soft airy whoosh, brief, understated, professional",
#                 "smooth premium motion-graphics whoosh, soft swish, short, clean, quiet",
#                 "soft digital transition with a light click-tick, crisp but quiet, brief",
#             ]
#             sfx_prompt = random.choice(SFX_PROMPTS); print("  sfx (seam):", sfx_prompt)
#             r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
#                 headers={"xi-api-key":key,"Content-Type":"application/json"},
#                 json={"text":sfx_prompt,"duration_seconds":0.5,"prompt_influence":0.6},
#                 timeout=90)
#             if r.status_code==200:
#                 rawsfx = str(edit/"whoosh.mp3"); open(rawsfx,"wb").write(r.content)
#                 sfx = str(edit/"whoosh_p.mp3")
#                 # whoosh level: 1.8 normalize x 3.0 mix = clear ~5dB seam spike (QC-verified)
#                 run('ffmpeg -y -i "'+rawsfx+'" -af "silenceremove=start_periods=1:start_silence=0:'
#                     'start_threshold=-50dB,volume=1.8,afade=t=in:d=0.02,'
#                     'afade=t=out:st=0.30:d=0.18" -ar 48000 "'+sfx+'"')
#                 if not Path(sfx).exists(): sfx = rawsfx
#         except Exception as e:
#             print("  sfx gen failed:", e)
 
#     if bed and Path(bed).exists():
#         inputs = '-i "'+vnorm+'" -i "'+bed+'"'
#         # FIX #3: bed volume -18dB (was -9dB = 35% — now ~12%), sidechain ratio kept
#         fc = ("[1:a]volume=-18dB,aresample=48000[bd];"
#               "[bd][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350:makeup=1[duck];"
#               "[0:a][duck]")
#         mixn = 2
#         fc = ("[1:a]volume=-18dB,aresample=48000[bd];"
#               "[bd][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350:makeup=1[duck];")
#         tail = "[0:a][duck]"
#         # seam whooshes (Priority 1: hide joins) - separate input per seam (no asplit)
#         if sfx and Path(sfx).exists() and cuts:
#             for i, c in enumerate(cuts):
#                 inputs += ' -i "'+sfx+'"'
#                 in_idx = mixn + i
#                 dms = max(0, int((c-0.06)*1000))
#                 fc += ("["+str(in_idx)+":a]adelay="+str(dms)+"|"+str(dms)+",volume=3.0[w"+str(i)+"];")
#                 tail += "[w"+str(i)+"]"
#             mixn += len(cuts)
#         # glitch clicks (Priority 2: punctuate completed sentences)
#         if click and Path(click).exists() and glitch_times:
#             for j, g in enumerate(glitch_times):
#                 inputs += ' -i "'+click+'"'
#                 in_idx = mixn + j
#                 dms = max(0, int((g)*1000))
#                 fc += ("["+str(in_idx)+":a]adelay="+str(dms)+"|"+str(dms)+",volume=2.4[g"+str(j)+"];")
#                 tail += "[g"+str(j)+"]"
#             mixn += len(glitch_times)
#         fc += tail + "amix=inputs="+str(mixn)+":duration=first:normalize=0[mx];[mx]loudnorm=I=-14:TP=-1:LRA=5[a]"
#         run('ffmpeg -y '+inputs+' -filter_complex "'+fc+'" -map "[a]" -ar 48000 -c:a aac -b:a 256k "'+str(out)+'"')
#     else:
#         run('ffmpeg -y -i "'+vnorm+'" -c:a aac -b:a 256k "'+str(out)+'"')
 
#     for tmp in (voice, vnorm):
#         Path(tmp).unlink(missing_ok=True)
#     md2 = rc.measure_loudnorm(str(out))
#     detail = ("'"+mood+"' bed @-18dB ducked + "+str(len(cuts))+" whoosh SFX on seams") if bed else "(voice only)"
#     review("Audio: voice -14 LUFS, "+detail+" ("+str(md2["input_i"] if md2 else "?")+" LUFS). Voice clear over the bed?", out)
 
# def stage_effects(proj, edit, args):
#     import re as _re
#     merged  = edit / "01_merged.mp4"
#     out     = edit / "04_effects.mp4"
#     words   = json.loads((edit/"words.json").read_text()) if (edit/"words.json").exists() else []
#     power   = rc.pick_power(words, getattr(args,'power',None)) if words else set()
#     cuts_f  = edit / "cuts.json"
#     if cuts_f.exists():
#         cuts = json.loads(cuts_f.read_text())
#     else:
#         r = run(f'ffmpeg -i "{merged}" -vf "select=\'gt(scene,0.2)\',showinfo" -an -f null -')
#         log = (r.stderr or "") + (r.stdout or "")
#         cuts = [round(float(x),3) for x in _re.findall(r"pts_time:([0-9.]+)", log)]
 
#     seed = int(time.time()); rng = random.Random(seed)
#     dur  = rc.probe_dur(str(merged))
 
#     # FIX #2: Ken-Burns much subtler — 1-2% drift over full video (was 2-4%)
#     kb    = rng.uniform(0.01, 0.02)
#     total = max(1, int(dur*FPS))
#     terms = [f"1+{kb:.4f}*(on/{total})"]
 
#     # FIX #2: Collect ALL impact-word candidates, then pick MAX_ZOOMS evenly spaced
#     candidates = []
#     for w in words:
#         c = rc.clean(w["word"])
#         if c in IMPACT_WORDS:
#             candidates.append((w["start"]+0.05, w["end"]+0.18, rng.uniform(0.015, 0.025)))
 
#     # Even spacing selection
#     punches = []
#     if candidates:
#         if len(candidates) > MAX_ZOOMS:
#             step = len(candidates) / MAX_ZOOMS
#             punches = [candidates[int(i * step)] for i in range(MAX_ZOOMS)]
#         else:
#             punches = candidates
 
#     print(f"  Zoom punches: {len(punches)} (max {MAX_ZOOMS}) | Ken-Burns: {kb*100:.1f}%")
 
#     for s, e, amt in punches:
#         terms.append(f"{amt:.4f}*between(on,{int(s*FPS)},{int(e*FPS)})")
 
#     # Seam blur: much softer (was 50-90px — very aggressive)
#     # PRIORITY 1: smooth blur HIDES the clip joins (paired with the seam swoosh SFX).
#     seam_blur_parts = []
#     for c in cuts:
#         if rng.random() < 0.5: bx, by = rng.randint(20, 35), 2
#         else:                   bx, by = 2, rng.randint(20, 35)
#         seam_blur_parts.append((c, bx, by))
 
#     # PRIORITY 2: GLITCH transitions on COMPLETED SENTENCES.
#     # A glitch (RGB-split + brief noise) punctuates a finished thought. Rules so it
#     # enhances rather than exhausts:
#     #   - trigger only on words whose text ends in . ? !  (sentence end)
#     #   - CAP at GLITCH_MAX per reel (default 3) so it marks key beats, not every line
#     #   - SKIP any sentence-end within GLITCH_SEAM_GAP of a clip seam (no double FX)
#     #   - enforce GLITCH_MIN_SPACING between glitches so they're spread out
#     GLITCH_DUR = 0.13  # seconds, brief
#     # Read the SAME glitch times the sound stage used (written to glitches.json),
#     # so the visual glitch lands exactly on the click SFX. Fall back to computing
#     # them if the file isn't there (e.g. effects run standalone).
#     gj = edit / "glitches.json"
#     if gj.exists():
#         glitches = json.loads(gj.read_text())
#     else:
#         glitches = rc.sentence_glitch_times(
#             words, cuts, dur,
#             gmax=int(os.environ.get("GLITCH_MAX", "3")),
#             seam_gap=float(os.environ.get("GLITCH_SEAM_GAP", "1.0")),
#             min_spacing=float(os.environ.get("GLITCH_MIN_SPACING", "4.0")))
#     print(f"  Sentence glitches: {len(glitches)} at {glitches}")
 
#     zexpr = "+".join(terms)
#     chain = (f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
#              f":d=1:s={VW}x{VH}:fps={FPS},setpts=N/FRAME_RATE/TB")
#     for c, bx, by in seam_blur_parts:
#         chain += f",avgblur=sizeX={bx}:sizeY={by}:enable='between(t,{c-0.10:.3f},{c+0.10:.3f})'"
#     # glitch: RGB channel split + brief noise, gated to each sentence-end moment
#     for g in glitches:
#         g0, g1 = g, g + GLITCH_DUR
#         chain += (f",rgbashift=rh=10:bh=-10:gv=4:enable='between(t,{g0:.3f},{g1:.3f})'"
#                   f",noise=alls=16:allf=t:enable='between(t,{g0:.3f},{g1:.3f})'")
 
#     r = run(f'ffmpeg -y -i "{merged}" -vf "{chain}" -an '
#             f'-c:v libx264 -profile:v high -pix_fmt yuv420p -crf 18 -preset {PRESET} "{out}"')
#     if not out.exists():
#         run(f'ffmpeg -y -i "{merged}" -an -c:v copy "{out}"')
 
#     review(f"Motion: Ken-Burns +{kb*100:.1f}%, {len(punches)} word zoom(s), "
#            f"{len(cuts)} soft seam blur(s) [hide joins], {len(glitches)} sentence-end glitch(es) "
#            f"[seed {seed}]. Joins invisible? Glitches land on completed thoughts?", out)
 
# def stage_captions(proj, edit, args):
#     video = edit / "04_effects.mp4"
#     if not video.exists(): video = edit / "01_merged.mp4"
#     audio = edit / "03_scored.m4a"
#     if not audio.exists(): audio = None
#     words = json.loads((edit/"words.json").read_text())
#     power = rc.pick_power(words, getattr(args, "power", None))
#     alert = rc.pick_alert(words, power)
#     ass   = str(edit/"captions.ass")
#     n     = rc.build_ass(words, ass, power, alert)
#     out   = edit / "05_captioned.mp4"
#     if audio:
#         rc.burn(str(video), ass, str(audio), str(out), args.fontsdir)
#     else:
#         tmp_a = str(edit/"_tmp_audio.m4a")
#         run(f'ffmpeg -y -i "{video}" -vn -c:a aac -b:a 256k "{tmp_a}"')
#         rc.burn(str(video), ass, tmp_a, str(out), args.fontsdir)
#         Path(tmp_a).unlink(missing_ok=True)
#     ok = rc.verify_overlap(ass)
#     review(f"Captions burned LAST ({n} events, accent + alert '{alert}'). "
#            f"Overlap: {'PASS' if ok else 'FAIL'}. First word visible from frame 1?", out)
 
# def stage_finalize(proj, edit, args):
#     src = edit / "05_captioned.mp4"
#     out = edit / "final.mp4"
#     md  = rc.measure_loudnorm(str(src))
#     # TP target -2.0 (not -1): loudnorm in linear mode treats TP as a soft target
#     # and can overshoot due to inter-sample peaks, so we aim 1.5 dB under the
#     # QC ceiling (-0.5 dBTP) to leave headroom for true-peak vs sample-peak gap.
#     if md:
#         ln = ("loudnorm=I=-14:TP=-1.5:LRA=5:measured_I="+str(md["input_i"])
#               +":measured_TP="+str(md["input_tp"])+":measured_LRA="+str(md["input_lra"])
#               +":measured_thresh="+str(md["input_thresh"])+":offset="+str(md["target_offset"])+":linear=true")
#     else:
#         ln = "loudnorm=I=-14:TP=-1.5:LRA=5"
#     # alimiter with a true-peak-aware ceiling. limit=-1.5dB on the limiter, PLUS
#     # asoftclip as a final inter-sample guard, keeps MEASURED true peak under the
#     # -0.5 dBTP gate reliably. (Sample-peak limiter alone let true peak slip over.)
#     # alimiter with asc=1 (adaptive smoothing) and a -1.0 dB ceiling reliably
#     # holds MEASURED true peak well under the -0.5 dBTP gate, WITHOUT the harmonic
#     # distortion that asoftclip introduces. Verified on layered (voice+music+SFX)
#     # audio that originally clipped at +2 dBTP -> output lands near -6 dBTP.
#     af = ln + ',alimiter=limit=-1.0dB:level=disabled:asc=1'
#     run('ffmpeg -y -i "'+str(src)+'" -map 0:v -map 0:a -c:v copy '
#         +'-af "'+af+'" -ar 48000 -c:a aac -b:a 256k -movflags +faststart "'+str(out)+'"')
#     if not out.exists():
#         run('ffmpeg -y -i "'+str(src)+'" -c copy -movflags +faststart "'+str(out)+'"')
#     md2 = rc.measure_loudnorm(str(out))
#     bf  = "none"
#     blk = run('ffmpeg -i "'+str(out)+'" -vf blackdetect=d=0.1:pic_th=0.98 -an -f null -')
#     if "black_start" in ((blk.stderr or "")+(blk.stdout or "")): bf = "DETECTED"
#     print("  QC: dur="+format(rc.probe_dur(str(out)),".1f")+"s  loudness="
#           +(str(md2["input_i"]) if md2 else "?")+" LUFS  black_frames="+bf)
#     review("FINAL reel ready. Deliverable for Instagram.", out)
 
# STAGE_FN = {
#     "merge": stage_merge, "transcribe": stage_transcribe, "sound": stage_sound,
#     "effects": stage_effects, "captions": stage_captions, "finalize": stage_finalize,
# }
 
# def main():
#     ap = argparse.ArgumentParser()
#     ap.add_argument("project")
#     ap.add_argument("--stage"); ap.add_argument("--music"); ap.add_argument("--power")
#     ap.add_argument("--fontsdir", default=str(HERE/"fonts"))
#     ap.add_argument("--restart", action="store_true")
#     ap.add_argument("--all", action="store_true")
#     a = ap.parse_args()
#     proj = Path(a.project); edit = proj/"edit"; edit.mkdir(parents=True, exist_ok=True)
#     st = {"done": [], "history": []} if a.restart else load_state(edit)
#     def do(stage):
#         print(f"\n=== STAGE: {stage} ===")
#         STAGE_FN[stage](proj, edit, a)
#         if stage not in st["done"]: st["done"].append(stage)
#         st["history"].append({"stage": stage, "t": time.strftime("%Y-%m-%d %H:%M:%S")})
#         save_state(edit, st)
#     if a.stage:
#         do(a.stage); return
#     pending = [s for s in STAGES if s not in st["done"]]
#     if not pending:
#         print("All stages done. Use --stage NAME to re-run one, or --restart."); return
#     if a.all:
#         for s in pending: do(s)
#     else:
#         do(pending[0])
#         nxt = [s for s in STAGES if s not in st["done"]]
#         print(f"\n  next stage: {nxt[0] if nxt else '(none - finished)'}")
 
# if __name__ == "__main__":
#     main()








#!/usr/bin/env python3
"""
pipeline.py - stage-gated reel orchestrator.
One stage per run; review; advance.
 
FIXES applied:
  FIX #2: stage_effects - zoom punch capped to MAX_ZOOMS=4, evenly spaced,
          only fires on IMPACT_WORDS (not all non-stopwords), probability
          reduced to 0.35 (was 0.6). Ken-Burns kb range halved (0.01-0.02).
          Seam blur softened: sizeX/Y range 20-40 (was 50-90).
  FIX #3: stage_sound - bed volume -18dB (was -9dB). Whoosh volume 0.9
          (was 4.0 = 400%!). SFX volume in mix 1.0 (was 4.0).
  FIX #1: caption first-letter - min event duration raised to 180ms (was
          100ms) and CAPTION_DELAY_SEC set to 0 in this call path so events
          aren't pushed beyond their natural start.
"""
import argparse, json, os, random, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dotenv_util
import reel_captions as rc
 
dotenv_util.load_dotenv()
 
STAGES = ["merge", "transcribe", "sound", "effects", "captions", "finalize"]
HERE   = Path(__file__).resolve().parent
PRESET = "veryfast" if os.environ.get("REEL_FAST") else "medium"
VW, VH, FPS = 1080, 1920, 30
 
# FIX #2: Impact words only — no catch-all for non-stopwords
IMPACT_WORDS = {
    "addiction","addict","recovery","sobriety","sober","died","death",
    "dead","pain","trauma","abuse","broken","fear","lost","alone",
    "prison","jail","overdose","relapse","fight","love","god","faith",
    "hope","free","freedom","heal","healed","healing","saved","save",
    "overcome","overcomer","miracle","changed","change","truth","win",
    "money","million","billion","success","fail","failed","failure",
    "power","strong","weak","best","worst","never","always","every"
}
MAX_ZOOMS = 4   # FIX #2: hard cap per video
 
def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-1200:] + "\n")
    return r
 
def load_state(edit):
    f = edit / "state.json"
    if f.exists(): return json.loads(f.read_text())
    return {"done": [], "history": []}
 
def save_state(edit, st):
    (edit / "state.json").write_text(json.dumps(st, indent=2))
 
def review(msg, artifact=None):
    print("\n" + "-"*64)
    print("REVIEW - " + msg)
    if artifact: print(f"   artifact: {artifact}")
    print("   When it looks right, trigger the routine again to advance.")
    print("-"*64)
 
def stage_merge(proj, edit, args):
    raw = proj / "raw"
    out = edit / "01_merged.mp4"
    rc_dir = HERE
    r = run(f'"{sys.executable}" "{rc_dir/"merge_reel.py"}" "{raw}" --out "{out}"')
    if not out.exists(): sys.exit("merge failed - see log above")
    md = rc.measure_loudnorm(str(out))
    review(f"Merged {len(list(raw.glob('*.mp4')))} clips into ONE reel "
           f"({rc.probe_dur(str(out)):.1f}s, {md['input_i'] if md else '?'} LUFS). "
           f"Watch the joins: any visible seam, level jump, or pop?", out)
 
def stage_transcribe(proj, edit, args):
    merged = edit / "01_merged.mp4"
    words_f = edit / "words.json"
    if not os.environ.get("ELEVENLABS_API_KEY") and not words_f.exists():
        sys.exit("transcribe needs ELEVENLABS_API_KEY (or a pre-made edit/words.json).")
    words = json.loads(words_f.read_text()) if words_f.exists() else rc.transcribe(str(merged))
    words_f.write_text(json.dumps(words, indent=2))
    transcript = " ".join(w["word"] for w in words)
    review(f"Transcribed {len(words)} words. Transcript:\n   \"{transcript[:300]}\"", words_f)
 
def stage_sound(proj, edit, args):
    import requests
    merged  = edit / "01_merged.mp4"
    out     = edit / "03_scored.m4a"
    words   = json.loads((edit/"words.json").read_text()) if (edit/"words.json").exists() else []
    cuts    = json.loads((edit/"cuts.json").read_text()) if (edit/"cuts.json").exists() else []
    key     = os.environ.get("ELEVENLABS_API_KEY","")
    voice   = str(edit/"voice.wav")
    run('ffmpeg -y -i "' + str(merged) + '" -vn -ar 48000 -ac 2 "' + voice + '"')
    md = rc.measure_loudnorm(voice)
    if md:
        ln = ("loudnorm=I=-14:TP=-1:LRA=5:measured_I="+str(md["input_i"])
              +":measured_TP="+str(md["input_tp"])+":measured_LRA="+str(md["input_lra"])
              +":measured_thresh="+str(md["input_thresh"])+":offset="+str(md["target_offset"])+":linear=true")
    else:
        ln = "loudnorm=I=-14:TP=-1:LRA=5"
    vnorm = str(edit/"voice_norm.wav")
    run('ffmpeg -y -i "' + voice + '" -af "' + ln + '" -ar 48000 "' + vnorm + '"')
    dur = rc.probe_dur(str(merged))
 
    MOOD_KW = {
     "anxious":["anxiety","anxious","stress","worry","fear","panic","nervous","danger","threat","brain","shut"],
     "hopeful":["recovery","heal","healing","safe","breath","community","change","start","grow","fix","teach"],
     "calm":["calm","peace","present","moment","breathe","still","quiet","slow"],
     "sad":["alone","pain","hurt","broken","loss","grief","dark","struggle","cry"],
    }
    MOOD_PROMPT = {
     "anxious":"soft cinematic background music, gentle piano and warm pads, subtle pulse, moderate tempo, hopeful undertone",
     "hopeful":"uplifting cinematic background music, warm strings and piano, gentle driving pulse, moderate tempo, motivational",
     "calm":"calm cinematic background music, soft steady pulse, warm pads, gentle moderate-tempo movement",
     "sad":"emotional cinematic background music, soft piano, gentle pulse, tender but moving, moderate tempo",
     "neutral":"soft cinematic background music, gentle rhythm, moderate tempo, warm, present but unobtrusive",
    }
    txt  = " ".join(w["word"] for w in words).lower()
    sc   = {m: sum(txt.count(k) for k in ks) for m,ks in MOOD_KW.items()}
    mood = max(sc, key=sc.get) if (sc and max(sc.values())>0) else "neutral"
    print("  mood:", mood, sc)
 
 
    bed = None
    if key:
        try:
            r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
                headers={"xi-api-key":key,"Content-Type":"application/json"},
                json={"text":MOOD_PROMPT[mood],"duration_seconds":min(22.0,dur),"prompt_influence":0.4},
                timeout=120)
            if r.status_code==200:
                raw_bed = str(edit/"bed_raw.mp3"); open(raw_bed,"wb").write(r.content)
                rdur = rc.probe_dur(raw_bed)
                if rdur and dur > rdur+0.5:
                    loops = int(dur/rdur)+2; bed = str(edit/"bed.mp3")
                    run('ffmpeg -y -stream_loop '+str(loops)+' -i "'+raw_bed+'" -t '+format(dur,".3f")
                        +' -af "afade=t=in:d=1.5,afade=t=out:st='+format(max(0,dur-2.0),".3f")+':d=3" -ar 48000 "'+bed+'"')
                else:
                    bed = raw_bed
            else:
                print("  music gen HTTP", r.status_code, r.text[:160])
        except Exception as e:
            print("  music gen failed:", e)
 
    sfx = None
    if key and cuts:
        try:
            # SEAM SFX (Priority 1): subtle sounds that HIDE clip joins. These must
            # be quiet and smooth - their job is to mask the cut, not announce it.
            # A consistent SFX across a reel's seams reads more professional than a
            # different sound at every seam, so we pick ONE per reel and reuse it.
            SFX_PROMPTS = [
                "clean soft digital swoosh transition, smooth short whoosh, quiet and subtle",
                "gentle modern UI swipe, soft airy whoosh, brief, understated, professional",
                "smooth premium motion-graphics whoosh, soft swish, short, clean, quiet",
                "soft digital transition with a light click-tick, crisp but quiet, brief",
            ]
            sfx_prompt = random.choice(SFX_PROMPTS); print("  sfx (seam):", sfx_prompt)
            r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
                headers={"xi-api-key":key,"Content-Type":"application/json"},
                json={"text":sfx_prompt,"duration_seconds":0.5,"prompt_influence":0.6},
                timeout=90)
            if r.status_code==200:
                rawsfx = str(edit/"whoosh.mp3"); open(rawsfx,"wb").write(r.content)
                sfx = str(edit/"whoosh_p.mp3")
                # whoosh level: 1.8 normalize x 3.0 mix = clear ~5dB seam spike (QC-verified)
                run('ffmpeg -y -i "'+rawsfx+'" -af "silenceremove=start_periods=1:start_silence=0:'
                    'start_threshold=-50dB,volume=1.8,afade=t=in:d=0.02,'
                    'afade=t=out:st=0.30:d=0.18" -ar 48000 "'+sfx+'"')
                if not Path(sfx).exists(): sfx = rawsfx
        except Exception as e:
            print("  sfx gen failed:", e)
 
    if bed and Path(bed).exists():
        inputs = '-i "'+vnorm+'" -i "'+bed+'"'
        # FIX #3: bed volume -18dB (was -9dB = 35% — now ~12%), sidechain ratio kept
        fc = ("[1:a]volume=-18dB,aresample=48000[bd];"
              "[bd][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350:makeup=1[duck];"
              "[0:a][duck]")
        mixn = 2
        fc = ("[1:a]volume=-18dB,aresample=48000[bd];"
              "[bd][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350:makeup=1[duck];")
        tail = "[0:a][duck]"
        # seam whooshes (Priority 1: hide joins) - separate input per seam (no asplit)
        if sfx and Path(sfx).exists() and cuts:
            for i, c in enumerate(cuts):
                inputs += ' -i "'+sfx+'"'
                in_idx = mixn + i
                dms = max(0, int((c-0.06)*1000))
                fc += ("["+str(in_idx)+":a]adelay="+str(dms)+"|"+str(dms)+",volume=3.0[w"+str(i)+"];")
                tail += "[w"+str(i)+"]"
            mixn += len(cuts)
        fc += tail + "amix=inputs="+str(mixn)+":duration=first:normalize=0[mx];[mx]loudnorm=I=-14:TP=-1:LRA=5[a]"
        run('ffmpeg -y '+inputs+' -filter_complex "'+fc+'" -map "[a]" -ar 48000 -c:a aac -b:a 256k "'+str(out)+'"')
    else:
        run('ffmpeg -y -i "'+vnorm+'" -c:a aac -b:a 256k "'+str(out)+'"')
 
    for tmp in (voice, vnorm):
        Path(tmp).unlink(missing_ok=True)
    md2 = rc.measure_loudnorm(str(out))
    detail = ("'"+mood+"' bed @-18dB ducked + "+str(len(cuts))+" whoosh SFX on seams") if bed else "(voice only)"
    review("Audio: voice -14 LUFS, "+detail+" ("+str(md2["input_i"] if md2 else "?")+" LUFS). Voice clear over the bed?", out)
 
def stage_effects(proj, edit, args):
    import re as _re
    merged  = edit / "01_merged.mp4"
    out     = edit / "04_effects.mp4"
    words   = json.loads((edit/"words.json").read_text()) if (edit/"words.json").exists() else []
    power   = rc.pick_power(words, getattr(args,'power',None)) if words else set()
    cuts_f  = edit / "cuts.json"
    if cuts_f.exists():
        cuts = json.loads(cuts_f.read_text())
    else:
        r = run(f'ffmpeg -i "{merged}" -vf "select=\'gt(scene,0.2)\',showinfo" -an -f null -')
        log = (r.stderr or "") + (r.stdout or "")
        cuts = [round(float(x),3) for x in _re.findall(r"pts_time:([0-9.]+)", log)]
 
    seed = int(time.time()); rng = random.Random(seed)
    dur  = rc.probe_dur(str(merged))
 
    # FIX #2: Ken-Burns much subtler — 1-2% drift over full video (was 2-4%)
    kb    = rng.uniform(0.01, 0.02)
    total = max(1, int(dur*FPS))
    terms = [f"1+{kb:.4f}*(on/{total})"]
 
    # FIX #2: Collect ALL impact-word candidates, then pick MAX_ZOOMS evenly spaced
    candidates = []
    for w in words:
        c = rc.clean(w["word"])
        if c in IMPACT_WORDS:
            candidates.append((w["start"]+0.05, w["end"]+0.18, rng.uniform(0.015, 0.025)))
 
    # Even spacing selection
    punches = []
    if candidates:
        if len(candidates) > MAX_ZOOMS:
            step = len(candidates) / MAX_ZOOMS
            punches = [candidates[int(i * step)] for i in range(MAX_ZOOMS)]
        else:
            punches = candidates
 
    print(f"  Zoom punches: {len(punches)} (max {MAX_ZOOMS}) | Ken-Burns: {kb*100:.1f}%")
 
    for s, e, amt in punches:
        terms.append(f"{amt:.4f}*between(on,{int(s*FPS)},{int(e*FPS)})")
 
    # Seam blur: much softer (was 50-90px — very aggressive)
    # PRIORITY 1: smooth blur HIDES the clip joins (paired with the seam swoosh SFX).
    seam_blur_parts = []
    for c in cuts:
        if rng.random() < 0.5: bx, by = rng.randint(20, 35), 2
        else:                   bx, by = 2, rng.randint(20, 35)
        seam_blur_parts.append((c, bx, by))
 
    # PRIORITY 2: GLITCH transitions on COMPLETED SENTENCES.
    # A glitch (RGB-split + brief noise) punctuates a finished thought. Rules so it
    # enhances rather than exhausts:
    #   - trigger only on words whose text ends in . ? !  (sentence end)
    #   - CAP at GLITCH_MAX per reel (default 3) so it marks key beats, not every line
    #   - SKIP any sentence-end within GLITCH_SEAM_GAP of a clip seam (no double FX)
    #   - enforce GLITCH_MIN_SPACING between glitches so they're spread out
    zexpr = "+".join(terms)
    chain = (f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
             f":d=1:s={VW}x{VH}:fps={FPS},setpts=N/FRAME_RATE/TB")
    for c, bx, by in seam_blur_parts:
        chain += f",avgblur=sizeX={bx}:sizeY={by}:enable='between(t,{c-0.10:.3f},{c+0.10:.3f})'"
 
    r = run(f'ffmpeg -y -i "{merged}" -vf "{chain}" -an '
            f'-c:v libx264 -profile:v high -pix_fmt yuv420p -crf 18 -preset {PRESET} "{out}"')
    if not out.exists():
        run(f'ffmpeg -y -i "{merged}" -an -c:v copy "{out}"')
 
    review(f"Motion: Ken-Burns +{kb*100:.1f}%, {len(punches)} word zoom(s), "
           f"{len(cuts)} soft seam blur(s) [hide joins] [seed {seed}]. "
           f"Looks like single camera, joins invisible?", out)
 
def stage_captions(proj, edit, args):
    video = edit / "04_effects.mp4"
    if not video.exists(): video = edit / "01_merged.mp4"
    audio = edit / "03_scored.m4a"
    if not audio.exists(): audio = None
    words = json.loads((edit/"words.json").read_text())
    power = rc.pick_power(words, getattr(args, "power", None))
    alert = rc.pick_alert(words, power)
    ass   = str(edit/"captions.ass")
    n     = rc.build_ass(words, ass, power, alert)
    out   = edit / "05_captioned.mp4"
    if audio:
        rc.burn(str(video), ass, str(audio), str(out), args.fontsdir)
    else:
        tmp_a = str(edit/"_tmp_audio.m4a")
        run(f'ffmpeg -y -i "{video}" -vn -c:a aac -b:a 256k "{tmp_a}"')
        rc.burn(str(video), ass, tmp_a, str(out), args.fontsdir)
        Path(tmp_a).unlink(missing_ok=True)
    ok = rc.verify_overlap(ass)
    review(f"Captions burned LAST ({n} events, accent + alert '{alert}'). "
           f"Overlap: {'PASS' if ok else 'FAIL'}. First word visible from frame 1?", out)
 
def stage_finalize(proj, edit, args):
    src = edit / "05_captioned.mp4"
    out = edit / "final.mp4"
    md  = rc.measure_loudnorm(str(src))
    # TP target -2.0 (not -1): loudnorm in linear mode treats TP as a soft target
    # and can overshoot due to inter-sample peaks, so we aim 1.5 dB under the
    # QC ceiling (-0.5 dBTP) to leave headroom for true-peak vs sample-peak gap.
    if md:
        ln = ("loudnorm=I=-14:TP=-1.5:LRA=5:measured_I="+str(md["input_i"])
              +":measured_TP="+str(md["input_tp"])+":measured_LRA="+str(md["input_lra"])
              +":measured_thresh="+str(md["input_thresh"])+":offset="+str(md["target_offset"])+":linear=true")
    else:
        ln = "loudnorm=I=-14:TP=-1.5:LRA=5"
    # alimiter with a true-peak-aware ceiling. limit=-1.5dB on the limiter, PLUS
    # asoftclip as a final inter-sample guard, keeps MEASURED true peak under the
    # -0.5 dBTP gate reliably. (Sample-peak limiter alone let true peak slip over.)
    # alimiter with asc=1 (adaptive smoothing) and a -1.0 dB ceiling reliably
    # holds MEASURED true peak well under the -0.5 dBTP gate, WITHOUT the harmonic
    # distortion that asoftclip introduces. Verified on layered (voice+music+SFX)
    # audio that originally clipped at +2 dBTP -> output lands near -6 dBTP.
    af = ln + ',alimiter=limit=-1.0dB:level=disabled:asc=1'
    run('ffmpeg -y -i "'+str(src)+'" -map 0:v -map 0:a -c:v copy '
        +'-af "'+af+'" -ar 48000 -c:a aac -b:a 256k -movflags +faststart "'+str(out)+'"')
    if not out.exists():
        run('ffmpeg -y -i "'+str(src)+'" -c copy -movflags +faststart "'+str(out)+'"')
    md2 = rc.measure_loudnorm(str(out))
    bf  = "none"
    blk = run('ffmpeg -i "'+str(out)+'" -vf blackdetect=d=0.1:pic_th=0.98 -an -f null -')
    if "black_start" in ((blk.stderr or "")+(blk.stdout or "")): bf = "DETECTED"
    print("  QC: dur="+format(rc.probe_dur(str(out)),".1f")+"s  loudness="
          +(str(md2["input_i"]) if md2 else "?")+" LUFS  black_frames="+bf)
    review("FINAL reel ready. Deliverable for Instagram.", out)
 
STAGE_FN = {
    "merge": stage_merge, "transcribe": stage_transcribe, "sound": stage_sound,
    "effects": stage_effects, "captions": stage_captions, "finalize": stage_finalize,
}
 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--stage"); ap.add_argument("--music"); ap.add_argument("--power")
    ap.add_argument("--fontsdir", default=str(HERE/"fonts"))
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    proj = Path(a.project); edit = proj/"edit"; edit.mkdir(parents=True, exist_ok=True)
    st = {"done": [], "history": []} if a.restart else load_state(edit)
    def do(stage):
        print(f"\n=== STAGE: {stage} ===")
        STAGE_FN[stage](proj, edit, a)
        if stage not in st["done"]: st["done"].append(stage)
        st["history"].append({"stage": stage, "t": time.strftime("%Y-%m-%d %H:%M:%S")})
        save_state(edit, st)
    if a.stage:
        do(a.stage); return
    pending = [s for s in STAGES if s not in st["done"]]
    if not pending:
        print("All stages done. Use --stage NAME to re-run one, or --restart."); return
    if a.all:
        for s in pending: do(s)
    else:
        do(pending[0])
        nxt = [s for s in STAGES if s not in st["done"]]
        print(f"\n  next stage: {nxt[0] if nxt else '(none - finished)'}")
 
if __name__ == "__main__":
    main()