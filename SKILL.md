---
name: reel-editing
description: Turn raw podcast clips into an Instagram reel (recovery/mental-health). Stage-gated pipeline run via pipeline.py - merge, transcribe, sound, effects, captions, finalize - one reviewable artifact per run.
---
# Reel Editing - Video Pipeline Processor

Run the pipeline one stage at a time:
  python pipeline.py <PROJECT_DIR>          # next pending stage, then stop
  python pipeline.py <PROJECT_DIR> --stage <name>   # re-run one stage
  python pipeline.py <PROJECT_DIR> --restart        # start over

Stages: merge -> transcribe -> sound -> effects -> captions -> finalize.
Artifacts land in <PROJECT_DIR>/edit/ (01_merged, words.json, 03_scored,
04_effects, 05_captioned, final.mp4). Captions are burned LAST.

Hard rules: no word cut at a join (cut in silence), no two captions on screen
at once (verified), captions in safe zone, one accent colour + one alert word,
music ducked under voice, output -14 LUFS.
