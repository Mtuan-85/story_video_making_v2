# BUILD LOG — Sprint 3 Final Fix

**Plan**: `SPRINT3_FINAL_FIX.md` (8 changes, 5-6h)
**Started**: 2026-05-01
**Resumed**: 2026-05-02

---

## Changes

### Day 1 — Cleanup + UI (commit `dbf4ec6`)

- [x] **Change 7** — Cleanup V1 redundancy
  - Verified: `render/` no longer contains `subtitle_filter.py`, `zoom_effect.py`
  - Verified: `voice/subtitle_builder.py` removed
  - Verified: `ui/dialogs/voice_import.py` removed
- [x] **Change 8** — Rename V2 → main
  - Verified: `render/composite.py`, `render/assemble.py` exist (no `_v2` suffix)
  - Verified: no `_v2` references in repo
- [x] **Change 1** — Auto-clone `scenes_edited.json`
  - Verified: `test_live/scenes_edited.json` present alongside `scenes.json`
- [x] **Change 2** — Bỏ wizard "Import Voice Files"
  - Verified: `voice_import.py` deleted; `Process voice` button wired
- [x] **Change 3** — UI Review dialog 2-column
  - Verified: `ui/dialogs/voice_align_review.py` rewritten with QGridLayout

### Day 2 — Render fixes (uncommitted, in working tree)

- [x] **Change 4** — Fix zoom jitter image_grok (`build_zoom_filter`)
  - Code landed in `render/visual_fit.py` (pre-scale 4x lanczos, trunc x/y, d=total_frames)
- [x] **Change 5** — Fix slideshow trắng + zoom video jitter (`_zoom_tail`, `build_video_filter`)
  - Code landed in `render/visual_fit.py` (pre-scale 4x, trunc, d=1, speedup cap 1.2x + trim)
- [x] **Change 6** — Voice-led timeline + freeze frame pause
  - `voice/voice_aligner.py`: `add_freeze_pauses()` impl + call site
  - `core/voice_mapping.py`: `freeze_pause_after` / `render_duration` schema
  - `render/composite.py`: freeze pause append + audio apad
  - `voice/ass_generator.py`: subtitle timing accounts for freeze pause
  - `ui/dialogs/voice_align_review.py`: `freeze_pause` aware
- [x] **E2E test** — Render full `test_live` PASS: final.mp4 28.90s, 9 subtitle events, smooth zoom confirmed by user (2026-05-02)
- [x] **COMMIT 2** — `Sprint 3 Day 2: render fix smooth zoom + voice-led timeline`

---

## Active step

**Sprint 3 Final Fix DONE.** All 8 Changes shipped + E2E pass.

---

## Day 1 verify (pre-resume gate)

- [x] `test_live/scenes_edited.json` exists
- [x] GUI: Process voice → no wizard, dialog 2-column (user confirmed via E2E run)
- [x] `render/` lists only: `__init__.py`, `assemble.py`, `bgm_mixer.py`, `composite.py`, `kdenlive_export.py`, `slideshow.py`, `visual_fit.py`, `voice_slicer.py` (no `_v2`, no `subtitle_filter`, no `zoom_effect`)
- [x] `ui/dialogs/voice_import.py` absent

---

## Resume rules

- Each Change starts with `git commit --allow-empty -m "wip: change N start"` (breakpoint marker)
- Each Change ends with `git commit -m "Sprint 3 Change N: <desc>"`
- Update checkbox in this log immediately after each commit
- After auto-reset:
  1. `git log --oneline -10` → find last `wip: change N start` or `Sprint 3 Change N` commit
  2. `git diff --stat HEAD` → file → Change mapping (see below)
  3. Open this log → read **Active step** section

## File → Change map

| File | Change |
|---|---|
| `core/project.py`, `core/paths.py` | 1 |
| `ui/main_window.py` (Process voice button) | 2 |
| `ui/dialogs/voice_align_review.py` | 3, 6 |
| `render/visual_fit.py` (`build_zoom_filter`) | 4 |
| `render/visual_fit.py` (`_zoom_tail`, `build_video_filter`) | 5 |
| `render/composite.py`, `voice/voice_aligner.py`, `core/voice_mapping.py`, `voice/ass_generator.py` | 6 |

## E2E test cheatsheet

```bash
# Clear stale artifacts
rm -f test_live/renders/*.mp4 test_live/final.mp4 test_live/final.ass test_live/voice_mapping.json

# Render via GUI: load test_live → Process voice → Save → Render final
# Inspect:
#   - SCENE-03 (slideshow): bitrate > 1Mbps, content visible (NOT white)
#   - SCENE-02, SCENE-05 (zoom_out): smooth, no jitter
#   - voice_mapping.json: each scene has freeze_pause_after
#   - final.mp4: freeze frame pause between scenes, subtitle ends at voice_out
```
