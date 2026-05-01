# BUILD LOG — Sprint 3 Render Fix

**Started**: 2026-05-01
**Goal**: Fix 5 issues per `SPRINT3_RENDER_FIX.md`

---

## Steps

- [x] **1. Karaoke swap colors** — PRIMARY=yellow, SECONDARY=white. Verified karaoke.jpg shows white→yellow direction
- [x] **5. Zoom expression linear** — linear `on/total_frames`, `d=1`. SCENE-05 first frame tight crop, last frame wide crop = smooth zoom_out
- [x] **3. Apply zoom on video_grok** — stacked zoompan after canvas pad. SCENE-04 (video_grok zoom_in) first frame wide, last frame tight = zoom_in working
- [x] **4. Slideshow route as video** — added `source_is_video` param + `is_static` dispatch in composite_v2. SCENE-03 bitrate 192Kbps→578Kbps, frames show coffee cup content (was white)
- [x] **2. Dialog 2-column layout** — _SceneRow rebuilt with QGridLayout: Script/Voice text left, Render duration/Voice timing right
- [x] **E2E re-render** — final_v6.mp4 26.68s w/ all 5 scenes; 14/14 modules import green

## Active step: DONE — manual GUI confirm + commit pending

## Resume cheatsheet

- E2E render: `python test_phase6_render.py` writes `test_live/final_v6.mp4`
- Frame inspection: `ffmpeg -i test_live/renders_v6/SCENE-XX.mp4 -vf fps=1 frame_%02d.jpg`
- ASS file inspection: `cat test_live/final_v6.ass` (look for `Style: Default,...`)
- Phase 6 reference: render worker wired Plan D, schema v4.0, render_duration override done.
