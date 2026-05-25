# Build Log — Sprint 3 Final Patches

> Resume hint: open this file first when you return. Pending live-test
> checklist is at the bottom. Static checks all pass.

---

## Session 2026-05-25 — native timeline render + ref mapping + final audio mix

Status: implemented with targeted verification. Full repo test deliberately not run because it can crash this Codex session.

### Summary

The final render path now consumes the trusted voice timeline directly:

```
voice/voice_matching_timeline.json + voice/master_voice.wav
  -> render/timeline_visual.py builds visual-only scene/gap/pause segments
  -> concat visual-only timeline
  -> final ffmpeg pass burns ASS and mixes master voice + optional BGM
```

This replaces the legacy behavior where render sliced voice per scene and then concatenated scene mp4s. That old approach removed natural inter-scene voice gaps that were present in `master_voice.wav`, making narration feel unnaturally tight.

### Render / voice changes

- `workers/render_worker.py` now requires both:
  - `voice/voice_matching_timeline.json`
  - `voice/master_voice.wav`
- No automatic fallback to legacy `voice_mapping.json` for timing.
- `voice_mapping.json` is only used for ASS subtitle phrase data when available.
- `render/timeline_visual.py` is the visual timeline builder:
  - scene segments use the matched render duration from timeline items
  - `freeze_gap` segments preserve natural gaps between timeline items
  - `beat_pause` segments preserve explicit beat pauses
  - all intermediate clips are visual-only (`-an`)
- Final audio uses the continuous `master_voice.wav`, not per-scene `atrim` slices.
- Voice is normalized in the final mix with ffmpeg loudnorm:
  - `I=-16:TP=-1.5:LRA=11`

### Subtitle / BGM changes

- ASS subtitle style now uses Cambria bold, centered vertically, with 100px horizontal margins for wrapping.
- BGM is selected by sorted filename order from `bgm/*.mp3` and `bgm/*.wav`, concatenated sequentially, looped if needed, trimmed at video end, and faded in/out 2s.
- BGM level changed from `-15dB` to `-17dB`.
- Subtitle burn and BGM/voice mixing happen in one final ffmpeg command to avoid double re-encode.
- `render/bgm_mixer.py` now supports:
  - ASS + BGM
  - no ASS + BGM
  - ASS + master voice + BGM
  - no BGM fallback with subtitle burn only

### Reference image mapping

Added project-level ref mapping file:

```
{project_stem}_ref_mapping.json
```

New contract:

- style/background ref is the default ref for scenes without characters
- character refs are mapped once from project-level `character` names
- each scene resolves refs from its scene-level `characters_in_scene`
- character scenes may also include the style ref when the toggle is enabled
- disabled refs are ignored
- render/generation checks the mapping file before image tasks and warns if required paths are missing

Main modules:

```
core/ref_mapping.py
ui/refs_panel.py
engines/grok/image_worker_flow.py
workers/task_contract.py
```

### Verification run

Targeted checks only:

```
python -m pytest tests\test_ref_mapping.py tests\test_image_worker_flow_paths.py tests\test_task_contract.py tests\test_ui_batch_edit_structure.py tests\test_generate_worker_routing.py tests\test_worker_cli_noop.py
# 32 passed

python -m pytest tests\test_timeline_render.py tests\test_bgm_mix_and_ass.py
# 8 passed

python -m py_compile render\timeline_visual.py render\bgm_mixer.py workers\render_worker.py ui\main_window.py
# passed
```

### Open follow-ups

- Live render on a real project after Process Voice to confirm perceived narration pacing.
- Generate subtitle phrases from the new voice timeline directly, then make ASS independent from legacy `voice_mapping.json`.
- Expose BGM dB / fade / voice loudnorm parameters in UI only if repeated manual tuning is needed.

### Reminder for future slideshow engine expansion

Slideshow SFX currently belongs to the standalone slideshow MP4:

- each zone has a `sound` value (`pop`, `flip`, `whoosh`, `swoosh`, `ding`)
- `slideshow/renderer.py::_collect_audio_inputs()` places each WAV at the zone `appear_at`
- `_encode_video()` mixes those clips into the slideshow MP4 with ffmpeg `amix`
- `SlideshowEditDialog` supports per-zone sound and bulk `Sound all → Apply`

Important limitation: final render uses `render/timeline_visual.py` visual-only
segments (`-an`) and then muxes continuous `master_voice.wav` + BGM. That means
audio embedded in slideshow MP4s is intentionally stripped from `final.mp4`.
If we want slideshow SFX in final render, add a separate SFX timeline/mix pass
that extracts/places slideshow audio against the trusted voice timeline and
mixes it with master voice + BGM.

---

## 🔖 PENDING — older resume note (2026-05-25, superseded by session above)

Sprint 1 + Sprint 2 implementation is **done but not yet committed**.
BUILD_LOG session entry below (2026-05-24) is fully written.

**To resume:**

1. Read the 2026-05-24 session entry below for full context.
2. Verify uncommitted changes match the file list at the bottom of that entry:
   ```bash
   cd D:/Projects/story_video_making_v2
   git status --short
   ```
3. Stage SOURCE files only (skip `project 1/*`, `exports/*`, `launch_opera.bat`,
   `.claude/settings.local.json`):
   ```bash
   git add BUILD_LOG.md core/paths.py slideshow/orchestrator.py \
           slideshow/assets/sounds/*.wav \
           workers/export_worker.py workers/render_worker.py \
           workers/two_level_match_worker.py ui/main_window.py \
           voice/s5_loader.py voice/beat_timeline.py voice/master_audio_builder.py \
           voice/master_whisper.py voice/flexible_matcher.py voice/silent_allocator.py \
           voice/timeline_builder.py voice/timeline_to_mapping.py \
           exporters/ \
           sprint_1_two_level_voice_matching_spec.md \
           sprint_2_kdenlive_xml_export_spec.md
   ```
4. Commit:
   ```
   sprint 1 + 2: two-level voice match + Kdenlive XML export
   ```
   See "Session 2026-05-24" below for the full message body.
5. Push:
   ```bash
   git push origin main
   ```
6. Live-test punch list (defer if time-boxed):
   - Open `exports/kdenlive/Naomi2.kdenlive` in Kdenlive 22+ → verify
     timeline has A1 master audio + V1 scene/pause clips + markers.
   - Click Render Final after Process Voice → verify resume (stop
     mid-render → restart → finished scenes skipped).
   - Slideshow re-render → verify pop/flip/whoosh sound effects in output mp4.

Open follow-ups from this older note have been partially superseded:
- BGM mix is now active in render.
- Render now consumes `voice_matching_timeline.json` natively.
- Subtitle phrase extraction from the new timeline is still open; legacy `voice_mapping.json` can still provide ASS phrases when present.

---

## Session 2026-05-24 — Sprint 1 (two-level voice match) + Sprint 2 (Kdenlive export)

Status: ready to commit. End-to-end tested on Naomi2 (25 beats / 86 scenes).

### Overview

Replaced the global-cursor voice alignment with a **two-level matcher**
driven by a per-beat narration source-of-truth (`{stem}_S5.json`) and
per-beat TTS audio (`voice/beat-XX.mp3`). Rebuilt the Kdenlive XML
exporter as a clean editable project (master audio on A1, separate
visual clips for scenes + beat pauses on V1, markers, freeze-frame
generation, placeholder fallback).

Specs consumed verbatim:
- `sprint_1_two_level_voice_matching_spec.md` (root)
- `sprint_2_kdenlive_xml_export_spec.md` (root)

### Sprint 1 — voice matching

New modules under `voice/`:

```
s5_loader.py              # parse + validate {stem}_S5.json against scenes
beat_timeline.py          # ffprobe per beat → exact beat-level timeline
master_audio_builder.py   # concat beats + synthetic silence → master_voice.wav
master_whisper.py         # Whisper master once (global timestamps)
flexible_matcher.py       # per-beat fuzzy match (70-135% window, weighted score)
silent_allocator.py       # allocate silent scenes inside beat gaps
timeline_builder.py       # orchestrator + validations + diagnostics
timeline_to_mapping.py    # adapter → legacy VoiceMapping for render
```

New worker:

```
workers/two_level_match_worker.py   # GUI wrapper, 6-step pipeline
```

New `ProjectPaths` properties:

```
s5_beats_json                       # {root}/{stem}_S5.json
master_voice_wav                    # {root}/voice/master_voice.wav
voice_matching_timeline_json        # {root}/voice/voice_matching_timeline.json
voice_matching_diagnostics_json     # {root}/voice/voice_matching_diagnostics.json
```

Pipeline (sync, per call):

```
input: {stem}_S5.json + voice/beat-XX.mp3 + scenes_edited.json
[1] Load + validate S5 (scene refs in order, no dupes, beat MP3s exist)
[2] ffprobe per beat → beat timeline (cursor only used here, exact)
[3] ffmpeg concat beats + anullsrc(pause_after_sec) → master_voice.wav
    Validation: |measured - expected| ≤ 0.05s
[4] Whisper transcribe master_voice.wav once (global timestamps)
[5] Per-beat scene matching:
    - Filter words to beat window [voice_in, voice_out]
    - Local cursor per beat (NEVER global)
    - Single-scene beat → full beat window shortcut
    - Multi-scene beat → flexible 70-135% window, weighted score:
        start 25 / end 25 / full 35 / continuity 15
    - no_match keeps scene_type="voiced" + status="unmatched_voiced_scene"
      (spec §14.3: never silently convert to silent)
    - Silent scenes allocated into existing beat gaps proportional to design
[6] Cross-beat overlap normalization, validation, save outputs
```

Outputs:

```
voice/master_voice.wav
voice/voice_matching_timeline.json
voice/voice_matching_diagnostics.json
```

Hard rules (spec §17 + §14):
- Master-audio mode → Whisper timestamps are GLOBAL. Do NOT add beat.voice_in.
  `detect_double_offset` raises a diagnostic warning if first-word.start > max beat.voice_in.
- Scene cursor resets at the start of every beat (acceptance #7).
- `pause_after_sec` is synthesized as silence in the master audio, not a TTS task.
- No voiced scene is ever converted to silent (acceptance #13).

Test on Naomi2 (25 beats / 86 scenes):

```
S5 validation:       86/86 scene refs, 0 errors, 0 warnings
Beat timeline:       758.15s total (voice 741.35s + pauses 16.80s)
Master audio drift:  +0.002s (tolerance ±0.05s)
Whisper output:      2078 words on master timeline
Match results:       86 voiced matched, 0 silent, 0 unmatched, 24 pauses
Cross-beat overlap:  2 clamps (SCENE-44 +0.013s, SCENE-55 +0.220s)
```

### Sprint 2 — Kdenlive XML export

New `exporters/` package:

```
timecode.py        # sec↔frame conversion (single source of truth)
freeze_frame.py    # ffmpeg -sseof -0.1 for video-pause stills
placeholder.py     # PIL placeholder JPGs for missing assets
asset_registry.py  # resolve every asset, register producer_id, generate freezes/placeholders
validators.py      # pre-export checks (audio dur, no negative dur, no major overlap)
mlt_builder.py     # MLT XML structure: profile, producers, V1/A1, tractor, guides
kdenlive_exporter.py  # top-level orchestrator (export_kdenlive_project)
```

`workers/export_worker.py` rewritten to call the new exporter.
`ui/main_window.py::_on_export_done` updated to surface the new
`(kdenlive_path, diagnostics_path)` signal.
The legacy `render/kdenlive_export.py` is retired (still on disk for git history).

Track layout produced:

```
V1: scene clips + beat_pause clips (separate visible clips, spec §9)
A1: master_voice.wav as 1 continuous clip (no per-scene slicing, spec §6.1)
```

Markers via `kdenlive:docproperties.guides` JSON property: BEAT/SCENE/PAUSE
labels at every boundary with color codes.

Scene visual resolution:
- Image scene → `sources/{id}.jpg`, MLT image producer
- Video / slideshow scene → `sources/{id}.mp4`, MLT avformat producer
- Beat pause after image scene → reuse same image producer (new playlist entry)
- Beat pause after video scene → ffmpeg `-sseof -0.1` extracts last frame
- Missing asset → policy="placeholder" (default) generates labelled JPG; "strict" fails

Test on Naomi2:
- Output: `exports/kdenlive/Naomi2.kdenlive` (61.3 KB)
- 110 clips (86 scenes + 24 pauses)
- 110 placeholders generated (project has no rendered visuals yet)
- 0 freeze-frames (no source videos exist)

### Render pipeline migration (adapter, not full rewrite)

The render pipeline (composite_scene + assemble_concat + ASS burn) still
consumes the legacy `voice_mapping.json` (v4.0). Rather than rewrite it,
`voice/timeline_to_mapping.py` adapts Sprint 1's timeline → VoiceMapping
on demand. `_start_render` invokes the adapter automatically when no
legacy mapping exists.

Mapping decisions:
- voice_files: single entry pointing at master_voice.wav (concat demuxer
  with one file = just that file, atrim works directly with global ts)
- freeze_pause_after per scene: derived from beat.pause_after_sec for the
  LAST scene of each beat; 0 for others (silent gaps handled by allocator)
- subtitle_phrases: not extracted (Sprint 1 doesn't compute these);
  `apply_ass_subtitle` falls back to copy when the .ass file is empty/missing

### Resume support in RenderWorker

`workers/render_worker.py` now skips composite for scenes whose
`renders/SCENE-XX.mp4` already exists with a duration matching expected
(`voice_part + freeze_pause`, ±0.10s).

- User can stop mid-render → on next click, only un-rendered scenes
  are composited; finished scenes are appended to `scene_outputs` and
  pipeline proceeds.
- Force re-render: delete `renders/` folder.

### Slideshow sound effects bundling

5 WAV files (`pop/flip/whoosh/swoosh/ding`) copied from
`zone_show_automation/assets/sounds/` to `slideshow/assets/sounds/`.
`slideshow/orchestrator.py` auto-wires `_DEFAULT_SOUNDS_DIR` when caller
passes `sounds_dir=None`. Slideshow renders now include zone sound effects
without any caller configuration.

### UI changes

- "🎬 Render Final" button moved from the bottom action row into the
  project header (right side), height 36px, green background. Acts as
  the pipeline endpoint.
- `_on_process_voice` swapped from `VoiceAlignWorker` (legacy global align)
  to `TwoLevelMatchWorker` (Sprint 1).
- Pre-flight check fails clearly if `{stem}_S5.json` or `beat-XX.mp3` are
  missing.
- Render + Kdenlive buttons enable when EITHER the legacy mapping OR
  the new timeline exists.

### Specs

`sprint_1_two_level_voice_matching_spec.md` and
`sprint_2_kdenlive_xml_export_spec.md` checked into the repo root so the
implementation contract is versioned with the code.

### Files in this session

```
NEW   voice/s5_loader.py
NEW   voice/beat_timeline.py
NEW   voice/master_audio_builder.py
NEW   voice/master_whisper.py
NEW   voice/flexible_matcher.py
NEW   voice/silent_allocator.py
NEW   voice/timeline_builder.py
NEW   voice/timeline_to_mapping.py
NEW   workers/two_level_match_worker.py
NEW   exporters/__init__.py
NEW   exporters/timecode.py
NEW   exporters/freeze_frame.py
NEW   exporters/placeholder.py
NEW   exporters/asset_registry.py
NEW   exporters/validators.py
NEW   exporters/mlt_builder.py
NEW   exporters/kdenlive_exporter.py
NEW   slideshow/assets/sounds/{ding,flip,pop,swoosh,whoosh}.wav
NEW   sprint_1_two_level_voice_matching_spec.md
NEW   sprint_2_kdenlive_xml_export_spec.md

MOD   core/paths.py                          # Sprint 1 path properties
MOD   slideshow/orchestrator.py              # _DEFAULT_SOUNDS_DIR auto-wire
MOD   workers/export_worker.py               # new exporter API
MOD   workers/render_worker.py               # resume support
MOD   ui/main_window.py                      # Sprint 1 wiring + render button placement
```

### Open follow-ups

- Subtitle phrases for render: Sprint 1 doesn't extract them. Either
  add a phrase extractor that reads whisper_words.json + timeline OR
  fold ASS generation into `voice_aligner`-equivalent inside Sprint 1.
- Superseded 2026-05-25: BGM is now active in render at `-17dB`.
- Superseded 2026-05-25: render now consumes `voice_matching_timeline.json`
  natively and uses continuous `master_voice.wav`.
- Nested zones in slideshow (Scene 13 case): documented limitation
  from earlier session — not affected by this work.

---

## Session 2026-05-23 — Slideshow v2 engine (zone-animate) + state-aware UI

Status: ready to commit. End-to-end tested (Edit single, re-render, multi-scene).

### Overview

Replaced the legacy `slideshow/` engine (rembg + object cropping + ffmpeg overlay)
with **slideshow v2** — a zone-based reveal-animation engine ported from
`D:/Projects/zone_show_automation`. Slideshow v2 is standalone (no zone_animate
runtime dependency), runs synchronously in a fresh QThread per call, and produces
re-editable output (zones JSON + polygon thumbnail) so the user can refine zones
without re-calling Claude.

### Engine — `slideshow/` (rewritten)

New modules:

- `slideshow/__init__.py` — package entry; exports `render_slideshow_v2`, `rerender_slideshow_v2`
- `slideshow/orchestrator.py` — 6-step pipeline (BG detect → Claude vision → polygon refine → overlap → render → save zones+thumb)
- `slideshow/bg_detect.py` — median border-pixel BG color detection (PIL only)
- `slideshow/claude_runner.py` — Claude CLI subprocess + vision prompt builder
  - `cwd=image_path.parent` (NOT temp dir) so Claude Read tool resolves the image
  - Pops `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` → forces subscription billing
- `slideshow/zone_refiner.py` — bbox → tight polygon (chroma + connected components + dilate + Douglas-Peucker)
- `slideshow/renderer.py` — M1 frame composition (PIL) + ffmpeg encode
- `slideshow/animations.py` — 7 animations (fade_in, scale_pop, slide_in_{l,r,t,b}, drop_in, pulse, glow, shake)
- `slideshow/easing.py` — ease_out_cubic/back/bounce + triangle_wave
- `slideshow/README_V2.md` — engine doc

Removed: `slideshow/preprocess.py` (legacy rembg pipeline).

### Pipeline (sync, per call)

```
input: image_path, duration, hint, output_path, zones_json_path, thumb_path, cache_dir
[1] BG detect             — median border pixels                                ~50ms
[2] Claude vision         — pick zones (bboxes + animation + sound + timing)    ~30-60s
[3] Polygon refine        — per zone: chroma → cc filter → dilate → contour     ~50ms × N
[4] Overlap resolution    — nearest-centroid pixel reassignment                 ~200ms
[5] Render video          — extract stickers + frame composition + ffmpeg       ~15-30s
[6] Save zones JSON + thumb — persistent for re-edit                            ~50ms
total: ~1-2 min/scene (Claude dominates)
```

Re-render path (`rerender_slideshow_v2`) skips steps 1-4, loads saved zones,
re-runs only step 5 — ~20-30s instead of 1-2 min.

### State model — `edit` field (independent from `video`)

`scene_state` gains a new top-level key:

```python
"edit": {
    "status": "pending|generating|ready|failed",
    "zones_json": "sources/edit/SCENE-XX-zones.json",
    "thumb_path":  "sources/edit/SCENE-XX-thumb.png",
    "last_render_at": "...",
    "fail_reason": null,
}
```

Rationale: `video.path` holds the final MP4 regardless of source (provider or
slideshow). `edit.zones_json` survives a Gen Video overwrite so the user can
reopen the zone editor later. Provider video and slideshow render are now
fully independent.

`core/project.py::_reconcile` was updated to:
1. Forward-migrate older state.json (add missing top-level keys per scene).
2. **Reset stuck `status="generating"` → `"failed"` on load** — recovers from
   prior crashes (e.g. the cv2 heap-corruption issue described below) that
   left state mid-flight.

`core/paths.py` adds: `edit_dir`, `edit_zones_json(sid)`, `edit_thumb(sid)`,
`edit_cache_dir(sid)`. Everything lives under `sources/edit/`.

### File organization

```
sources/
├── picN.jpg                    # image
├── vidN.mp4                    # final video (overwrite-OK; provider OR slideshow)
└── edit/
    ├── SCENE-XX-zones.json     # PERSISTENT — re-render input
    ├── SCENE-XX-thumb.png      # polygon overlay preview
    └── .cache/SCENE-XX/        # EPHEMERAL — Claude logs + frames; deleted on success
```

Previously the slideshow workspace lived in `tempfile.gettempdir()`. Moved to
project-local for debug visibility + per-project isolation.

### Worker — fresh QThread per call (was AsyncQThread)

`workers/slideshow_worker.py` rewritten:

- Base: `QThread` (Qt native), no qasync/`asyncio.to_thread`
- `run()` is sync, calls `slideshow.render_slideshow_v2` directly
- Two modes: full pipeline (Claude) vs `rerender_only=True` (skip Claude)
- Imports happen INSIDE `run()` so heavy modules (cv2, PIL) load in the worker thread
- Signals: `scene_started`, `scene_finished`, `scene_failed`, `log_message`

Why QThread instead of AsyncQThread:

- `asyncio.to_thread` reuses threads from a shared `ThreadPoolExecutor`.
- After ~20 slideshow renders we hit **Windows heap corruption (0xc0000374)**
  inside `cv2.morphologyEx`, traced to BLAS/OpenCV/asyncio pool interaction
  accumulating state across calls.
- QThread spawns a fresh OS thread per worker. Thread dies after `run()`
  returns → BLAS pool, cv2 TBB pool, Python module-level caches all cleaned up.
- Mirrors `zone_show_automation`'s proven pattern.

### Algorithm defenses (zone_refiner + renderer)

To prevent native crashes when cv2 / numpy slices interact across threads:

1. `np.ascontiguousarray(..., dtype=np.uint8)` before every cv2 call.
2. Chroma mask uses **int32 squared-distance** (not `np.linalg.norm` → no BLAS sub-pool).
3. `cv2.connectedComponentsWithStats` returns areas vectorized (was O(N×pixels)
   loop with `np.sum(labels == i)` that hung pipelines on pathological inputs).
4. Safety caps: `MAX_BBOX_PIXELS = 30M`, `MAX_COMPONENTS = 5000`, `MAX_DILATION_PX = 25`.
5. Granular per-step timing logs in `refine_polygon_from_bbox` so a stuck step
   identifies itself in the log.

### Algorithm fixes (P0)

- **Dilation kernel was half intended size.** `(dilation, dilation)` →
  `(dilation*2+1, dilation*2+1)`. Polygon now expands by the configured radius;
  prior bug clipped character/shadow edges.
- **Chroma threshold mismatch fixed.** Sticker extractor was using `threshold=25`
  while refiner used `15` — created a permanent halo of bg_color around faint
  edges. Sticker now imports `CHROMA_THRESHOLD` from `zone_refiner`.

### Performance (P1)

- **Glow layer cached per sticker.** Was rebuilding GaussianBlur(25px) every
  frame; now built once on first frame, reused for the rest of the emphasis
  cycle. ~30-50ms × 18 frames saved per glow zone.
- **Animation instances cached per scene.** `build_animation()` was called
  every frame; now built once in `_build_render_plan` and stashed under
  `scene["_entry_anim"]` / `scene["_emphasis_anim"]`.
- **Opacity uses 256-entry LUT** instead of Python lambda per pixel.
- **Z-order sort once** before the frame loop (was per-frame).
- **ffmpeg pad color** uses detected `bg_color` (was hardcoded white).
- **`with Image.open()`** in renderer (was leaking file handle to GC).
- **uint8 overflow guard** in `resolve_overlaps` (sum across n zones).
- **Edge-expansion early break** when bbox can't expand further (at image boundary).
- **Bbox validation** rejects `x2 <= x1 or y2 <= y1` with clear error.

### UI — state-aware buttons + 3 dialogs

`ui/scene_row.py`:

- Removed the generic `✏` edit button (redundant).
- Thumbnail is preview-only (no click action).
- Three asset buttons emit dedicated signals: `image_clicked`, `video_clicked`, `edit_clicked`.
- Button enabled state: `setEnabled(status != "generating")`.

`ui/main_window.py`:

- New routers `_on_image_btn_clicked` / `_on_video_btn_clicked` / `_on_edit_btn_clicked`.
- `pending`/`failed` → direct first-gen (no dialog).
- `ready` → opens dedicated dialog.
- Edit requires `image.status == "ready"` (warning otherwise).
- **Loguru sink hop via Qt signal** (`_log_sink_signal`) — `_sink` callback fires
  on any thread (worker, loguru queue) but emits a queued signal so the
  `log_view.append` always runs on the main thread. Previously caused a segfault
  via Qt thread affinity violation when the worker thread called `log.info()`.

New dialogs under `ui/dialogs/`:

- `image_preview_dialog.py` — image display + script + image prompt + Gen Image (+ Fast).
- `video_preview_dialog.py` — video player + script + image prompt (readonly) +
  video prompt + Gen Video. **Codec fallback**: on `QMediaPlayer.errorOccurred`
  the video widget is replaced with a "📺 Mở bằng player hệ thống" button that
  calls `os.startfile()` so users without H.264 codec can still preview.
- `slideshow_canvas.py` — `QGraphicsView` polygon editor (IDLE/SELECTED/EDITING_VERTEX
  state machine, drag handles, right-click insert/delete vertex, QUndoStack).
- `slideshow_edit_dialog.py` — modal combining canvas + per-zone table
  (animation/emphasis/sound/in-out timing) + Re-render (skip Claude) +
  preview-in-system-player + folder open.

`ui/scene_list.py` re-emits per-asset signals from `SceneRow` (was a single
generic `edit_clicked`).

### `render/slideshow.py` (legacy wrapper)

Kept as a deprecation shim for `workers/batch_video.py` which still imports
`render_slideshow` (async wrapper). Newly-flagged ⚠️ DEPRECATED in the docstring —
new callers should go through `SlideshowWorker` (fresh QThread + sync orchestrator)
to avoid the shared-pool heap corruption.

### Known limitation deferred

Claude occasionally returns **nested zones** (e.g. `"Turn-taking label"` whose
bbox sits inside `"Turn-taking scene"`). Current pipeline paints both polygons
on the base canvas, so the inner zone's content is masked out of the outer
sticker — user sees the outer zone animate first, then the inner zone
"reveal" on top. Documented in user testing on Scene 13. Algorithmic fix
(detect nested → subtract inner from outer mask, or enforce strict z-order)
is **not** implemented in this session.

### Files changed in this session

```
core/paths.py                         + edit_dir paths
core/project.py                       + 'edit' field, _reconcile recovery
render/slideshow.py                   deprecated wrappers, kept for batch_video
slideshow/__init__.py                 (new)
slideshow/orchestrator.py             (new) 6-step pipeline + rerender path
slideshow/bg_detect.py                (new)
slideshow/claude_runner.py            (rewritten) cwd fix + new vision prompt
slideshow/zone_refiner.py             (new) refine + resolve_overlaps + defenses
slideshow/renderer.py                 (rewritten) M1 logic + animation cache + LUT
slideshow/animations.py               (rewritten) 7 animations + Glow cache
slideshow/easing.py                   (new)
slideshow/preprocess.py               DELETED (legacy rembg pipeline)
slideshow/README_V2.md                (new)
workers/slideshow_worker.py           AsyncQThread → fresh QThread, two modes
ui/scene_row.py                       state-aware 3 buttons, removed ✏
ui/scene_list.py                      forward image_clicked / video_clicked
ui/main_window.py                     3 routers + edit state wiring + log signal
ui/dialogs/image_preview_dialog.py    (new)
ui/dialogs/video_preview_dialog.py    (new) + codec fallback
ui/dialogs/slideshow_canvas.py        (new) polygon editor
ui/dialogs/slideshow_edit_dialog.py   (new) V3 zone editor
```

### Verification

- All imports resolve cleanly (`python -c "from slideshow import render_slideshow_v2, rerender_slideshow_v2"`).
- MainWindow loads with new signal/handler wiring.
- SlideshowWorker base class is `QThread` (verified by `__mro__`).
- End-to-end live test: Scene 23 first-gen (Claude → render → zones JSON saved)
  then re-render (skip Claude, ~36s). Both completed successfully.
- Loguru cross-thread sink no longer crashes — `_log_sink_signal` routes appends
  to the main thread via `Qt.QueuedConnection`.
- SCENE-06 stuck "generating" state recovered on next load.

### Learning doc

A separate post-mortem covering the threading evolution, OpenCV/numpy defenses,
Qt thread-affinity rules, and design rules-of-thumb lives at
`D:/Projects/99_learning_vibe_code/story_video_v2_va_slideshow_v2_kien_truc.md`.

---

## Session 2026-05-20 — CDP provider worker refactor, image vertical slice

Status: uncommitted. Implemented by task slices with spec + quality review checkpoints. No git commit was made in this session.

### Follow-up design note — Batch Image / Video / Edit

User clarified the next UI structure:

- Keep provider/model generation separate from offline edit tools.
- Batch lanes should be:
  - `Batch Image`: selected scenes -> provider/model image generation.
  - `Batch Video`: selected `Video` scenes -> provider/model video generation.
  - `Batch Edit`: selected scenes -> offline edit/render tools.
- Single-scene actions should mirror the same split:
  - `Single Image`
  - `Single Video`
  - `Single Edit`
- The old `Batch animation` wording is too broad and should be replaced.
- The current `Voice` button can be removed from the main action row and replaced with a single/batch edit entry point because voice is not the active workflow now.
- Selection helpers are needed because manual ticking is slow:
  - `Select All`
  - `Clear`
  - optionally later: select by visual type/status.

Slideshow policy:

- Slideshow belongs under `Batch Edit` / `Single Edit`, not `Batch Video`.
- Slideshow only runs when the scene has a ready source image.
- Slideshow is packaged as the `slideshow/` tool folder and wrapped by `render/slideshow.py`; future edit tools should follow the same package-or-wrapper pattern rather than being wired directly into GUI branches.

Implemented after this note:

- `ui/scene_list.py`: added `select_all()` and `clear_selection()`.
- `ui/main_window.py`: top action row now has `Batch Image`, `Batch Video`, `Batch Edit`, `All`, `Clear`; the old main-row `Process voice` button is removed.
- `ui/main_window.py`: `Batch Edit` runs slideshow for selected `slideshow` scenes that have ready source images.
- `ui/dialogs/preview_dialog.py`: added `Gen Edit` and `gen_edit_requested`.
- `ui/scene_row.py`: replaced the disabled Voice asset button with an Edit asset button.
- `tests/test_ui_batch_edit_structure.py`: added UI smoke coverage for selection helpers and button structure.

### Update before commit prep

1. **Canonical app-level `visual_type`**
   - `core/schema.py`
     - Canonical values are now `Image`, `Video`, `slideshow`.
     - Legacy aliases `image_grok`, `image`, `video_grok`, `video` are accepted at load time and normalized.
     - Scene check-back metadata is preserved: `scene_type`, `visual_technique`, `characters_in_scene`, `core_idea_illustration`.
   - `core/project.py`
     - `Project.load()`, `reload()`, and `reset_to_design()` persist normalized scene schema back to `<stem>_edited.json` when aliases or AI keys are migrated.
   - Runtime/GUI/process paths now branch on `Image` / `Video` instead of provider-specific `image_grok` / `video_grok`.
   - `slideshow` remains unchanged and stays outside provider/model selection.

2. **Project data normalized**
   - `project 1/project_S4.json` and `project 1/project_S4_edited.json` now use the canonical schema:
     - `meta.version`, no root `version`.
     - no root `settings`.
     - root `character`.
     - `visual_type` values are `Image` / `Video`.

### What changed

1. **Project schema moved generation config into `meta`**
   - `core/schema.py`
     - Root `version` migrates into `meta.version`.
     - Legacy root `settings` is accepted as input and migrated into `meta`, but is not dumped.
     - Root `character` is supported.
     - Voice settings now live in `meta` with legacy fallback.
     - Scene `visual_type` is app-level (`Image`, `Video`, `slideshow`), with legacy alias migration.
   - `voice/fish_tts.py`
     - Reads voice config from `meta` first, then legacy `settings`.

2. **Worker task contract + QProcess launcher**
   - `workers/task_contract.py`
     - Typed `GenerateTask`, `CdpConfig`, `TaskOptions`, `WorkerEvent`.
     - Default CDP URL is `http://127.0.0.1:9222`.
     - Stable worker markers: `TASK START`, `EVENT`, `TASK DONE`, `TASK FAILED`.
   - `workers/process_launcher.py`
     - `GenerateProcess` wraps `QProcess`, streams stdout, parses worker markers, handles partial lines.
   - `workers/generate_worker.py`
     - CLI entrypoint with dry-run path and real Grok image routing.

3. **Grok worker-local CDP/image flow**
   - `engines/grok/cdp_worker.py`
     - Worker process owns Patchright/CDP.
     - Stale Patchright/Playwright `node.exe` cleanup is opt-in via `STORY_VIDEO_KILL_STALE_CDP=1`.
     - Default behavior does not kill Brave or driver processes.
     - Reuses existing Grok tab or opens `https://grok.com/imagine`.
   - `engines/grok/image_worker_flow.py`
     - Runs `batch_image` and `single_image` in one worker process per task.
     - Loads project JSON readonly and emits events only; GUI owns project state and thumbnail updates.
     - Supports text-to-image and image-with-refs paths.

4. **GUI/CDP separation**
   - `ui/connection_panel.py`
     - No `engines.grok`, no Patchright, no tab/page ownership.
     - Provider/model/CDP health panel only.
     - Default CDP URL: `http://127.0.0.1:9222`.
   - `ui/main_window.py`
     - Batch image and single image regen now create `GenerateTask` and run `GenerateProcess`.
     - GUI updates `state.json`, warnings, thumbnails from worker events.
     - Stop kills the image worker process; GUI marks any active scene as failed if the worker exits before terminal scene events.
     - Image generation is blocked while other active workers run to avoid state races.
     - Grok video generation is deferred until video worker refactor.
     - Single-scene slideshow remains available as an offline render/tool flow.

5. **Prompt settings call sites**
   - `workers/batch_image.py` and `workers/batch_video.py`
     - Read generation defaults directly from `scenes_json.meta`, not `scenes_json.settings`.

### Static verification run

- `.venv\Scripts\python.exe -m pytest tests/test_schema_meta.py tests/test_fish_tts_config.py -v` → 6 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_task_contract.py tests/test_worker_cli_noop.py tests/test_process_event_parser.py -v` → 20 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_worker_settings_meta.py -v` → 2 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_grok_cdp_worker.py -v` → 3 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_worker_cli_noop.py tests/test_generate_worker_routing.py tests/test_image_worker_flow_paths.py -v` → 9 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_process_event_parser.py tests/test_task_contract.py -v` → 16 passed.
- `.venv\Scripts\python.exe -m py_compile ui\main_window.py ui\connection_panel.py` → passed.
- `rg -n "GrokImageEngine|GrokVideoEngine|GrokConnection|engines\.grok|patchright|image_engine|video_engine|connection_panel\.connection" ui` → no matches.
- `.venv\Scripts\python.exe -m pytest tests -v` → 40 passed.
- `.venv\Scripts\python.exe -m py_compile core\schema.py core\project.py render\visual_fit.py render\composite.py workers\batch_video.py workers\render_worker.py workers\single_video.py ui\scene_row.py ui\dialogs\preview_dialog.py ui\main_window.py` → passed.
- `rg -n "visual_type.*(image_grok|video_grok)" "project 1" core workers engines ui render tests` → only alias compatibility tests remain.

### Live test checklist for this refactor

- [ ] Open Brave with CDP `9222`, logged into Grok.
- [ ] Run the app and load a project using the new `meta` schema.
- [ ] Click **Check CDP**; confirm health log, without GUI tab selection.
- [ ] Batch image 2 scenes; confirm one worker process starts, Grok tab opens/reuses, files appear in `sources/picN.jpg`, rows become ready, thumbnails refresh.
- [ ] Preview dialog → Gen Image for one scene; confirm `single_image` task runs as a new process and updates only that scene.
- [ ] Use reference images with image gen; confirm refs upload flow still works.
- [ ] Kill/stop image process mid-run; confirm GUI remains responsive and Stop state resets.
- [ ] Reload project; confirm `sources/` scan reconciles generated files.
- [ ] Try Grok video; confirm it is clearly deferred.
- [ ] Try single-scene slideshow; confirm offline render still works.

---

## Session 2026-05-03

### Commits landed on `main` (in order)

| SHA | Title |
|---|---|
| `58e1f35` | Grok typing: per-char variance + minimal human mimic (~+15% time) |
| `12ee475` | Sprint 3 patch: multi-ref image generation support |
| `a96dfbf` | UI: move RefImagesPanel beside Log |
| `f7f78e3` | Sprint 3 patch: GrokImageRefEngine + Stop All button |

## Session 2026-05-04

### Commits landed on `main`

| SHA | Title |
|---|---|
| `e2f1a35` | Sprint 3 patch: sync image-with-refs wait pattern + 30s initial wait |

Branch ahead `origin/main` by **11 commits** — **not pushed yet**, awaiting live verification.

### What was built today (2026-05-04)

**Sync image-with-refs wait pattern** (`engines/grok/actions.py`, `engines/grok/image_ref_engine.py`)

Root cause of remaining bug: ref-upload preview makes Grok's Download
button visible from T=0, so the previous `_wait_download_button()`
returned ready immediately → engine downloaded the **ref**, not the
generated image.

- `wait_video_ready` default `initial_wait_s`: **20 → 30s**
- New action `wait_image_ready(initial_wait_s=30, timeout_ms=120000)` — mirrors video pattern (fixed sleep → poll until "Generating X%" overlay gone AND download button visible)
- `image_ref_engine._wait_download_button` replaced with `_wait_image_ready(initial_wait_s=30, timeout_s=120)`. Inlined (not a call to the action) so `_check_stop()` runs every 1s in the initial sleep + every 2s in poll → Stop All stays responsive.

**Static verification today**: defaults verified, `_check_stop` count 10 → 11 (extra in sleep loop), method rename clean.

### What was built

1. **Human-like typing patch** (`engines/grok/actions.py`)
   - Per-char `random.uniform(15, 60)` ms (was fixed delay)
   - 80–150ms pause after `.,!?;:`
   - 3% micro-hiccup (40–100ms)
   - ~+15% total typing time vs baseline `fast`

2. **Multi-ref image generation** (state + UI + dispatch)
   - `core/project.py` — `image_refs` (list, max 5) + `use_refs_for_image` (bool) state, persisted in `state.json`
   - `engines/grok/actions.py::upload_ref_if_present` — accepts `ref_paths: list[Path]`, scaled timeout per file
   - `engines/grok/runner.py` — handler dispatches list-vs-scalar to `ref_paths` / `ref_path`
   - `ui/refs_panel.py` *(new)* — `RefImagesPanel` widget, browse/remove, 280–400px width
   - `ui/main_window.py` — panel mounted bottom-right beside Log (7:3 split); window default 1400×850

3. **GrokImageRefEngine + Stop All** (today's last commit)
   - `engines/grok/image_ref_engine.py` *(new)* — linear flow: ensure_at → set_mode → upload_refs → set_aspect → fill_prompt → click_submit → wait download button → download → back. 10 stop-checkpoints.
   - `workers/batch_image.py` + `workers/single_image.py` — dispatch ref engine when `use_refs_for_image` ON + refs non-empty; fallback to old engine otherwise (or when list empty).
   - `ui/main_window.py` — `🛑 Stop All` button (red), `_active_workers` registry, `_register_worker` / `_unregister_worker`, `_on_stop_all` confirm dialog. Wrapped 7 `worker.start()` sites: batch image/video, single image/video, voice align, render, export.

### Static verification (run today)

- `py_compile` clean on every touched file
- Headless `MainWindow()` build OK — Stop All button, registry, refs panel all present
- Dispatch matrix verified: `(use_refs, refs)` → `(False,*)`, `(True,[])`, `(True,[a,b])` route as expected
- Stop All registry mechanics: register → start → request_stop → worker exits → `finished` signal auto-removes from list

---

## ⏭ Live test checklist

Run `run.bat`, connect Brave to Grok logged-in tab, load a project, then:

### Priority tests

- [ ] **Test 1 (NEW priority) — image-with-refs 30s wait fixes ref-download bug**
  - Add 2 refs, tick "Use refs", click batch ảnh 1 scene
  - Watch log: `wait_image_ready: initial sleep 30s with stop checks...`
  - Verify: NO Download click within first 30s
  - After 30s: `Polling for image ready...` then `Image ready (overlay gone, download visible)` → download click → save
  - Verify output `picN.jpg` is the **generated image** (not the ref)
  - Visual eyeball: result has scene composition, not the ref photo

- [ ] **Test 2 — single regen with refs (original bug)**
  - Add 2 refs, tick "Use refs", click regen on 1 scene row
  - Verify: NO download spam, NO Brave restart loop, single image saved correctly

- [ ] **Test 3 — Stop All while running**
  - Start batch ảnh on 5 scenes; mid-run click 🛑 Stop All → confirm Yes
  - Verify: confirm dialog shows correct count, all workers stop within 1-3s (incl. during 30s initial wait), Brave alive

- [ ] **Test 4 — Stop All when idle**
  - Click 🛑 Stop All with nothing running → expect info dialog "Không có worker nào đang chạy"

- [ ] **Test 5 — untick refs falls back to text-to-image**
  - 2 refs added but checkbox UNTICK → batch ảnh
  - Verify: old 4-candidate masonry + Claude pick flow runs; NO upload step

- [ ] **Test 6 — tick refs but list empty**
  - Tick "Use refs", remove all refs → batch ảnh
  - Verify log: "Use refs enabled nhưng list trống — fallback text-to-image"; old flow runs no crash

### Secondary tests (lower priority)

- [ ] **Test 7 — Video flow with new 30s initial wait**
  - Trigger I2V batch on 1 scene; watch log: `Đợi 30s cho overlay xuất hiện...` (was 20s)
  - Verify polling proceeds normally, video downloads OK

- [ ] **Test 8 — full image-with-refs flow visual**
  - Watch Brave: ensure_at /imagine → mode Image → upload preview N refs → aspect re-applies (Original → 16:9) → human typing → submit → /post URL → 30s wait → download → back

- [ ] **Typing patch visual** — type a 200-char prompt, observe variable cadence + punctuation pauses

- [ ] **UI re-layout** — refs panel sits beside Log, not beside Dự án; window resize keeps ratio

### If a test fails

- Note the failing case here under a `## Issue YYYY-MM-DD` heading
- Decide: rollback the offending commit, or write a follow-up patch
- Don't push to `origin/main` until all priority tests pass

### After all tests pass

- [ ] Push branch to `origin/main` (11 commits ahead)
- [ ] Tag `v0.3.0` (closes Sprint 3 per patch doc)
- [ ] Move on to Sprint Kdenlive

---

## Session 2026-05-07

### Commits landed on `main` (pushed)

| SHA | Title |
|---|---|
| `2cc0167` | UI: ignore wheel events on scene-row + preview-dialog combos |
| `584cdb3` | core+grok: imagePrompt optional, faster ref-upload timeouts |
| `55694cf` | test_live: switch fixture to "The Gift of Mimamoru" + drop stale reports |
| `4c015fa` | chore: drop legacy BUILD_LOG_SPRINT3_FINAL.md, refresh local permissions |

### What was built / fixed today

1. **Combo wheel-event bug** (`ui/scene_row.py`, `ui/dialogs/preview_dialog.py`)
   - Symptom: scrolling the scene list silently flipped `visual_type` (e.g. `image_grok` → `video_grok` → `slideshow`) and persisted to `scenes_edited.json` because `QComboBox` grabs the wheel event under the cursor by default.
   - Fix: `NoWheelComboBox(QComboBox)` with `wheelEvent(e): e.ignore()` — applied to `visual_combo` + `effect_combo` in both files.
   - Click-to-open + arrow-keys still work; only passive hover-scroll is neutered.

2. **Schema + Grok timeouts** (`core/schema.py`, `engines/grok/actions.py`)
   - `Scene.imagePrompt`: required (`min_length=1`) → `Optional[str]` so video-only scenes (slideshow / video_grok with videoPrompt) validate without dummy text.
   - `upload_ref_if_present`: base wait 60s→30s, per-extra-ref 15s→5s, fallback sleep mirrors the new schedule (was 15s × N regardless).

3. **Test fixture swap** (`test_live/`)
   - Replaced `Rainy Cafe` placeholder `scenes.json` with full "The Gift of Mimamoru" project (63 scenes); added `naomi_1_scenes.json` alternate fixture.
   - Removed `VERIFY_REPORT.md` + `voice/BUG_FIX_VOICE_MAPPING_V2.md` (one-off notes).

4. **Cleanup**: deleted legacy `BUILD_LOG_SPRINT3_FINAL.md` (this file is the active one); refreshed `.claude/settings.local.json` permissions.

### Kdenlive export verified (no code change)

Manual trace of `render/kdenlive_export.py` + dry-run on `test_live/` (63 scenes, 7 video-ready, 63 image-ready, no voice, 2 BGM files):

- **Trigger**: only the "📤 Export Kdenlive XML" button → `_on_export_kdenlive` (main_window.py:958). Output fixed to `<root>/export.kdenlive`. No auto-export elsewhere.
- **`<producer>` set written**: 63 visuals (mp4 if `video.status==ready`, else jpg from image), `audio_voice` (only `voice_files[0]`), `audio_bgm` (only first sorted file in `bgm/`).
- **Caveats found** (not fixed today):
  - Multi-voice projects lose every file after `voice_files[0]`.
  - `bgm/` second+ files ignored.
  - Scenes without ready visual silently skipped (only logged).
  - Effects/transitions/colors not exported (already in SPEC).

### Resume hint

Working tree clean, `origin/main` at `4c015fa`. The Kdenlive caveats above are candidates for the next session if multi-voice / multi-BGM projects matter.

---

## Session 2026-05-07 (cont.) — Patch A + Patch B (UI + project naming)

User feedback drove this round; spec lives in repo-root `claude_change_edit.md` (6 issues, 4 actionable). Audit of current code first, then 2 patches landed back-to-back. Not committed yet — awaiting live test of the new flow.

### Audit findings (no code change for these)

- **CDP/Brave restart on regen** — false alarm. `kill_and_relaunch_brave` has exactly one call site (`workers/_retry.py:56`), only fires on gen-factory exception. Click → kill is actually first-attempt failure → retry kill. Skipped per user instruction.
- **`scenes_edited.json` auto-loaded on project open** — already implemented at `core/project.py:99–104`; first-load auto-clones `scenes.json` → `scenes_edited.json`, then reads from edited as source of truth.
- **Slideshow dispatch** — already implemented; `main_window._regen_one_video` (line 586) routes by `visual_type` field, no `videoPrompt` involvement.

### Patch A — Per-row Gen-lẻ + split Re-gen button

**Goal:** clicking 🖼/🎬 on a scene row should always open an editable prompt + Gen flow, even when the asset hasn't been generated. The unified PreviewDialog gets two action buttons (Gen Image / Gen Animation) instead of one ambiguous Re-gen.

Files changed:

- `ui/scene_row.py` — dropped `preview_image_clicked` / `preview_video_clicked` signals; 🖼 + 🎬 always enabled and route to `edit_clicked`. `_apply_asset` updates tooltip per status; voice button stays disabled.
- `ui/scene_list.py` — removed the two now-dead signals + their forwarding wires.
- `ui/dialogs/preview_dialog.py` — replaced `regen_requested` with `gen_image_requested` + `gen_animation_requested`; UI button "🔄 Save & Re-gen" → "🖼 Save & Gen Image" + "🎞 Save & Gen Animation".
- `ui/main_window.py` — dropped `_show_preview_image` / `_show_preview_video` / `_on_preview_regen` and the `PreviewImageDialog` / `PreviewVideoDialog` imports. `_show_preview_dialog` now wires `gen_image_requested → _regen_one`, `gen_animation_requested → _regen_one_video` (which already auto-dispatches video_grok vs slideshow by `visual_type`).
- Deleted `ui/dialogs/preview_image.py`, `ui/dialogs/preview_video.py` — orphan after the refactor.

Verification: AST parse + headless import smoke-test pass on all four modified UI modules. No live test yet.

### Patch B — Flexible project file naming + lazy subdir creation

**Goal:** user can select any `<stem>.json` from any folder; companions derived from stem; subfolders created on-demand by writers (no eager `ensure_dirs`).

Files changed:

- `core/paths.py` (rewrite) — `ProjectPaths(scenes_file: Path)` takes a file, derives:
  - `scenes_json` / `scenes_original` → `<stem>.json`
  - `scenes_edited` → `<stem>_edited.json`
  - `state_json` → `<stem>_state.json`
  - `legacy_state_json` → `state.json` (for one-shot fallback only)
  Subdirs (sources/voice/bgm/temp/thumbnails/renders), `voice_mapping.json`, `final.mp4` keep fixed names at root. `ensure_dirs()` is a no-op kept for API stability — every writer in repo (`render/*.py`, `workers/*.py`, `core/thumbnail.py`, `engines/grok/actions.py`) already calls `mkdir(parents=True, exist_ok=True)` on its own target (verified via grep).
- `core/project.py` — `Project.load(scenes_file: Path)` instead of `(project_dir)`. If a directory is passed, falls back to `<dir>/scenes.json` (preserves existing tests/scripts). Legacy state migration: only fires when `stem == "scenes"` AND `<stem>_state.json` doesn't exist AND `state.json` exists in same folder → loads from legacy, writes future state to `<stem>_state.json`. Legacy file kept as backup. **Critical:** migration is gated to stem="scenes" so a new project file in the same folder (e.g. `naomi_1_scenes.json`) does NOT inherit state from the old `scenes.json` project.
- `ui/main_window.py` — `_load_project()` passes the selected file path directly: `Project.load(scenes_path)`. Dialog caption updated to "Chọn file project (.json)".

Verification (live, against `test_live/` fixture):

1. `Project.load(Path("test_live"))` — legacy folder API → falls back to `scenes.json`, migrates state ✓
2. `Project.load(Path("test_live/scenes.json"))` — file API, stem="scenes" → migration triggers, loads 63 scenes ✓
3. `Project.load(Path("test_live/naomi_1_scenes.json"))` — custom stem → first-load clones edited file, fresh state (no inherit) ✓ (63 scenes)

Test artefacts cleaned up; `test_live/` returned to pre-test set (`scenes.json`, `scenes_edited.json`, `state.json`, `naomi_1_scenes.json`).

### Resume hint

Patches A + B uncommitted. Working tree includes:

- Modified: `ui/scene_row.py`, `ui/scene_list.py`, `ui/dialogs/preview_dialog.py`, `ui/main_window.py`, `core/paths.py`, `core/project.py`
- Deleted: `ui/dialogs/preview_image.py`, `ui/dialogs/preview_video.py`
- Pre-existing untracked: `claude_change_edit.md` (the spec), `docs/fast_mode_spec.md`, `test_live/assets_to_generate.md`, `test_live/file_rename_map.md`, `test_live/renamed/`, `.claude/settings.local.json` mod, `SPRINT3_FINAL_FIX.md` deletion.

**Open items:**

- Live UI test required: open `test_live/scenes.json` in the running app, click 🖼/🎬 on a row before any asset exists → confirm PreviewDialog opens with empty prompt editable; Save & Gen Image / Animation triggers correct worker; voice button stays disabled.
- `README.md:71` and `SPEC.md:162-163, 1391` still mention `preview_image` / `preview_video` dialogs — update next session.
- `claude_change_edit.md` issue #1 (CDP kill on regen) was deferred (root cause is retry on first-attempt failure). If user reports it again with logs, revisit `workers/_retry.py:54-61` to add a CDP health-check before kill.

---

## Session 2026-05-09 — Retry/Cancel popup + Fast Mode

Two patches landed back-to-back, both uncommitted, awaiting live test.

### Patch 1: Retry/Cancel popup simplification

User asked for simpler popup logic when a scene's gen exhausts the 3-attempt retry. Spec ratified: only Retry / Cancel (drop Skip / Abort).

Files changed:

- `ui/main_window.py:_ask_user_decision` — popup giờ 2 buttons (Retry / Cancel). Text giải thích rõ "Retry → +3 attempts; fail tiếp dừng hẳn".
- `workers/batch_image.py:_gen_one` — bỏ nhánh `skip`. `cancel` → `_abort=True` + `_mark_failed("user_cancel")`. `retry` → run_with_retry vòng 2 (3 attempts); fail tiếp → `_abort=True` + `_mark_failed("retry_exhausted")`. Defensive abort cho path `outcome.ok=False` không qua popup.
- `workers/batch_video.py:_gen_one_grok` — đối xứng batch_image, warn_code=`grok_no_video`.

Rationale (user): scene fail = browser/network/Grok DOM issue → retry flow đã handle bằng kill+relaunch Brave; nếu retry vòng 2 vẫn fail thì user muốn dừng cả batch để gen lại sau (cần full chain done, không skip rồi tiếp).

### Patch 2: Fast Mode (per-scene paste-prompt re-gen)

Spec rewritten as `docs/fast_mode_spec.md` v2 (simplified from v1). Drops batch + scene_row checkbox; only PreviewDialog + single workers. 8 file touched.

Key design points:
- Transient (no persist).
- `fast_mode=True` → `actions._fast_paste_prompt` thay `human_type`: paste line-by-line via `keyboard.insert_text` + Shift+Enter, sleep 5s with stop check (5×1s).
- Stop responsiveness: plumbed `stop_event: asyncio.Event | None` qua `actions.fill_prompt` → `_fast_paste_prompt`. Engines stash stop_event in config; runner reads from config; ref_engine passes `self._stop_event` directly.
- Signal payload: `gen_image_requested(str, bool)` / `gen_animation_requested(str, bool)`. No sync signal needed.
- Slideshow branch ignores fast_mode (no Grok involvement).

Files changed:

1. `engines/grok/actions.py` — `fill_prompt(... fast_mode=False, stop_event=None)`; new helper `_fast_paste_prompt(page, text, stop_event)`.
2. `engines/grok/runner.py` — `fill_prompt` action reads `config["fast_mode"]` + `config["stop_event"]`.
3. `engines/grok/engine.py` — `GrokImageEngine.gen_image` + `GrokVideoEngine.gen_video` pump `settings["fast_mode"]` + `settings["stop_event"]` into config.
4. `engines/grok/image_ref_engine.py` — `gen_image_with_refs(... fast_mode=False)` passes both `fast_mode` and `self._stop_event` into `A.fill_prompt`.
5. `ui/dialogs/preview_dialog.py` — added `QCheckBox("⚡ Fast")` in btns row; signal payload extended to `(str, bool)`; `_on_gen_image` / `_on_gen_animation` emit checkbox state.
6. `ui/main_window.py` — `_regen_one` + `_regen_one_video` accept `fast_mode: bool = False`, pass to worker constructors. PyQt auto-binds the bool from signal payload.
7. `workers/single_image.py` — `__init__` accepts `fast_mode`, sets `settings["fast_mode"]` + `settings["stop_event"]`, passes `fast_mode` to `gen_image_with_refs`.
8. `workers/single_video.py` — same shape; `settings["fast_mode"]` + `settings["stop_event"]` before `gen_video`.

### Static verification (run today)

- `py_compile` clean on 8 touched files.
- Signature checks: `actions.fill_prompt` has `fast_mode` + `stop_event`; `_fast_paste_prompt` exists; both PyQt signals have `(QString, bool)` payload; both single workers accept `fast_mode`.

### Live test checklist (Fast Mode)

- [ ] Mở dialog 1 scene → tick ⚡ → Gen Image (no refs) → log show paste behavior, ảnh ra OK.
- [ ] Tick ⚡ → Gen Image (có refs) → đi qua `image_ref_engine` cùng hành vi.
- [ ] Tick ⚡ → Gen Video (video_grok) → OK; (slideshow) → fast_mode bị bỏ qua, slideshow render bình thường.
- [ ] Untick → human_type chạy như cũ, không regression.
- [ ] Mở lại dialog → checkbox reset OFF (transient).
- [ ] Bấm Stop trong lúc 5s settle cuối → worker thoát ≤ 1s.
- [ ] Batch ảnh / batch video → log không thấy `fast paste`, vẫn human_type.

### Live test checklist (Retry/Cancel)

- [ ] Force fail 1 scene 3 lần (vd ngắt mạng) → popup hiện ra → Cancel → batch dừng, scene marked `user_cancel`.
- [ ] Force fail 1 scene 3 lần → Retry → +3 attempts → nếu thành công: tiếp scene kế; nếu fail: batch dừng, scene marked `retry_exhausted`.

### Resume hint

Working tree includes:
- Uncommitted: `BUILD_LOG.md`, `ui/main_window.py`, `workers/batch_image.py`, `workers/batch_video.py`, `engines/grok/actions.py`, `engines/grok/runner.py`, `engines/grok/engine.py`, `engines/grok/image_ref_engine.py`, `ui/dialogs/preview_dialog.py`, `workers/single_image.py`, `workers/single_video.py`, `docs/fast_mode_spec.md` (v2 rewrite).
- Patch A/B từ session 2026-05-07 vẫn chưa commit (xem hint phía trên).

Khi nào live test xong, gom 3 patch (retry/cancel + fast_mode + Patch A/B) thành commits riêng.

---

## Known limitations

- All verification across both sessions was static (compile + headless `MainWindow()` instantiation + signature checks). The two real bug classes — (a) single regen with refs producing download spam, (b) ref-image being downloaded instead of generated image — are both unreachable in the new code paths. **Live confirmation still required**, especially Test 1 (the 30s wait fix).
- Patch markdowns at repo root (`PATCH_HUMAN_TYPING.md`, `PATCH_REF_IMAGES.md`, `PATCH_REF_PANEL_MOVE.md`, `PATCH_IMAGE_REF_ENGINE_AND_STOP_ALL.md`, `PATCH_SYNC_WAIT_IMAGE_VIDEO.md`) — archive to `docs/history/` once Sprint 3 closes.
- `.claude/settings.local.json` and deleted `BUILD_LOG_SPRINT3_FINAL.md` still in `git status` — not part of this patch series; address separately.
- `gen_image_with_refs(wait_timeout_s=60)` kwarg is now dead (timing handled inside `_wait_image_ready`). Cosmetic — clean up in a later commit if desired.
