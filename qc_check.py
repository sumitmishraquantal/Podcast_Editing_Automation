#!/usr/bin/env python3
"""qc_check.py - objective QC + REVIEW.md for one project."""
import json, subprocess, sys
from pathlib import Path

def run(c): return subprocess.run(c, shell=True, capture_output=True, text=True)
def out(r): return (r.stderr or "") + (r.stdout or "")

def loud(p):
    t = out(run('ffmpeg -i "'+p+'" -af loudnorm=I=-14:TP=-1:print_format=json -f null -'))
    i = t.find('"input_i"')
    if i < 0: return None
    s = t.rfind("{", 0, i); e = t.find("}", i)
    try: return json.loads(t[s:e+1])
    except: return None

def dur(p):
    r = run('ffprobe -v error -show_entries format=duration -of csv=p=0 "'+p+'"')
    try: return float(r.stdout.strip())
    except: return 0.0

def grab(t, key):
    if key not in t: return -99.0
    seg = t.split(key,1)[1].strip().split("dB")[0].strip()
    try: return float(seg)
    except: return -99.0

def vol(p, t, w, key):
    return grab(out(run('ffmpeg -ss '+str(t)+' -t '+str(w)+' -i "'+p+'" -af volumedetect -f null -')), key)

def main():
    proj = Path(sys.argv[1]); edit = proj/"edit"; final = edit/"final.mp4"
    checks=[]; flags=[]
    def ok(n, c, d=""): checks.append((n, bool(c), d))
    if not final.exists():
        (edit).mkdir(parents=True, exist_ok=True)
        (edit/"REVIEW.md").write_text("# REVIEW  ----  FATAL"+chr(10)+chr(10)+"final.mp4 was never produced. Re-run the pipeline from the failing stage.")
        print("QC FATAL: no final.mp4"); sys.exit(1)
    d = dur(str(final)); ok("duration 12-90s", 12<=d<=90, str(round(d,1))+"s")
    md = loud(str(final))
    if md:
        I=float(md["input_i"]); TP=float(md["input_tp"])
        ok("loudness -16..-12 LUFS", -16<=I<=-12, str(I)+" LUFS")
        ok("true peak <= -0.5 dBTP", TP<=-0.5, str(TP)+" dBTP")
    blk = out(run('ffmpeg -i "'+str(final)+'" -vf blackdetect=d=0.1:pic_th=0.98 -an -f null -'))
    ok("no black frames", "black_start" not in blk)
    ass = edit/"captions.ass"
    if ass.exists():
        raw = ass.read_text(encoding="utf-8-sig")
        t2s = lambda x:(lambda h,m,s:h*3600+m*60+s)(*[float(z) for z in x.split(":")])
        ev=[]
        for ln in raw.splitlines():
            if ln.startswith("Dialogue:"):
                p=ln.split(",",4); ev.append((t2s(p[1]),t2s(p[2])))
        ev.sort(); bad=sum(1 for i in range(len(ev)-1) if ev[i][1]>ev[i+1][0]+1e-6)
        ok("no caption overlap", bad==0, str(bad)+" overlaps")
        clean = (("fs{" not in raw) and (chr(12) not in raw) and (chr(7) not in raw))
        ok("caption tags well-formed", clean, "" if clean else "STRAY BRACE/CTRL CHAR - reel_captions corrupted")
    cuts = json.loads((edit/"cuts.json").read_text()) if (edit/"cuts.json").exists() else []
    if (edit/"bed.mp3").exists():
        gaps = [vol(str(final), x, 0.5, "mean_volume:") for x in (d*0.3, d*0.6, d*0.9)]
        ok("music bed audible", any(g>-42 for g in gaps), "gaps "+str([round(g) for g in gaps]))
        for c in cuts:
            before = vol(str(final), max(0,c-0.6), 0.25, "max_volume:")
            at = vol(str(final), max(0,c-0.05), 0.25, "max_volume:")
            if at <= before+0.5:
                flags.append("Whoosh at seam "+str(round(c,1))+"s does not spike (before "+str(round(before,1))+" / at "+str(round(at,1))+") - SFX mistimed/too quiet.")
    failed=[c for c in checks if not c[1]]
    verdict = "SHIPPABLE" if not failed and not flags else ("BLOCKED - objective fail" if failed else "SHIPPABLE (with human-eye flags)")
    L=["# REVIEW  ----  "+verdict,"","final.mp4  "+str(round(d,1))+"s","","## Objective checks"]
    for n,p,dd in checks: L.append("- ["+("x" if p else " ")+"] "+n+((" ("+dd+")") if dd else ""))
    if flags: L+=["","## Needs human eyes/ears (Claude cannot see/hear video)"]+["- "+f for f in flags]
    if failed: L+=["","## FAILED - re-run the relevant stage"]+["- "+n+": "+dd for n,p,dd in failed]
    (edit/"REVIEW.md").write_text(chr(10).join(L), encoding="utf-8")
    print("QC:", verdict, "| failed:", len(failed), "| flags:", len(flags))
    sys.exit(0)

if __name__=="__main__":
    main()
