# Story Video Maker — Build Log

> Resumable log of Sprint 1 build progress. Each completed module gets one
> entry below. To resume after a closed session, read this file top-to-bottom.

**Source spec:** `SPEC.md` §16 (Sprints) + Appendix A (Build order).
**Sprint 1 goal:** Load scenes.json → batch gen images → re-gen per scene →
make video Grok / Slideshow / Ken Burns per scene → preview → state persist.

---

## Environment

- Working dir: `D:\Projects\story_video_making`
- Python: 3.11.15 (uv-managed at `.venv/`)
- Package manager: `uv`
- Installed deps so far: pydantic, loguru, patchright, pyqt6, qasync, pillow, opencv-python, numpy
- Reference impls under `grok_automation/` (read-only) and `slideshow_v4/` (do NOT modify per SPEC §3)

## Sprint 1 progress (Appendix A steps)

| # | Module | Status |
|---|---|---|
| 1 | core/schema.py + core/project.py | ✅ COMPLETE |
| 2 | engines/base.py | ✅ COMPLETE |
| 3 | engines/grok/* | ✅ COMPLETE |
| 4 | workers/batch_image.py + single_image.py | ✅ COMPLETE |
| 5 | ui/main_window.py + scene_list + scene_row + connection_panel | ✅ COMPLETE |
| 6 | ui/dialogs/* (preview_image, preview_video, prompt_editor) | ✅ COMPLETE |
| 7 | runtime/estimator.py | ✅ COMPLETE |
| 8 | workers/batch_video.py + single_video.py | ✅ COMPLETE |
| 9 | render/ken_burns.py | ✅ COMPLETE |
| 10 | slideshow_v4/ (already in place) + render/slideshow.py wrap | ✅ COMPLETE |
| 11 | workers/slideshow_worker.py + ken_burns_worker.py | ✅ COMPLETE |
| 12 | ── SPRINT 1 DONE ── | ✅ |

---

## Module 1 — `core/schema.py` + `core/project.py`

**Status:** ✅ COMPLETE

**Scaffolding created:**
- `pyproject.toml` (Python 3.11+, all Sprint 1-3 deps listed; hatchling build)
- `core/__init__.py` (re-exports Project, ProjectPaths, schema models)
- `core/paths.py` (ProjectPaths — image_path/video_path/voice_*/etc.)
- `core/schema.py` (Pydantic v2: Meta, Settings, Scene, ScenesJson)
- `core/project.py` (Project class — load/state/persist/reconcile)

**Schema additions vs SPEC §4.5:** added `voice_volume`, `voice_model_syntax`, scene-level `emotion` because existing `voice/fish_tts.py` + `voice/scenes_voice_test.json` already use these (SPEC oversight).

**Tests run:**
- Validate `examples/scenes_template_simple.json` + `voice/scenes_voice_test.json` → both OK
- Reject: voice_batch_id<1, bad visual_type, no story, duration>60, duplicate scene id → all rejected
- Project.load creates state.json with 6 pending scenes, all subdirs (sources/, voice/, bgm/, temp/) created
- update_scene_state persists; set_selected_visual persists; add_warning persists
- Reload from disk → state preserved
- Backup rotation: 7 writes → 5 .bak files kept (verified)
- Reconcile: drop scene from scenes.json → reload drops from state
- clear_warnings, reset_scene scoped correctly

**Result:** ALL TESTS PASSED (8 assertions)

---

## Module 2 — `engines/base.py`

**Status:** ✅ COMPLETE

**Files created:**
- `engines/__init__.py` (re-exports Protocols)
- `engines/base.py` (3 `@runtime_checkable` Protocols)

**Surface:**
- `EngineConnection`: connect / disconnect / is_connected
- `ImageEngine`: gen_image / pick_best
- `VideoEngine`: gen_video

**Tests run:** import + introspection + isinstance check via duck-typed stub.
**Result:** OK — Stub passes `isinstance(stub, EngineConnection)`.

---

## Module 3 — `engines/grok/*`

**Status:** ✅ COMPLETE

**Files created (7):**
- `engines/grok/__init__.py` (re-exports GrokConnection, GrokImageEngine, GrokVideoEngine)
- `engines/grok/selectors.py` (21 DOM constants, `^=` prefix matching)
- `engines/grok/browser.py` (GrokConnection — CDP attach + tab list/select)
- `engines/grok/actions.py` (23 atomic async actions)
- `engines/grok/flows.py` (4 declarative flows)
- `engines/grok/runner.py` (FlowRunner — universal executor + claude pick hook)
- `engines/grok/claude_picker.py` (CLI subprocess vision picker)
- `engines/grok/engine.py` (high-level Protocol implementations)

**Reference materials provided by user:** `D:\Projects\story_video_making\grok_automation\` — has `MASTER_grok_automation.md`, working code (selectors/actions/flows/runner), examples. Refactored into adapter pattern per SPEC §6 (no copy-paste; preserved working logic + quirks).

**Refactors vs reference:**
- `download_to(page, output_path)` — replaces legacy `output/{project}/{project}_{prefix}{counter}.{ext}` naming. Workers pass `projects/{name}/sources/picN.jpg` directly.
- `upload_ref_if_present(page, Path | None)` — accepts Path directly (no ref_cache dict indirection).
- New `claude_picker.pick_best(candidates, prompt, topic, style)` — instruction template per SPEC §6 with topic+style priority. Always falls back to index 0 on any failure (CLI missing, parse fail, timeout, exception).

**Quirks preserved (per MASTER_grok_automation.md §15):**
- Canvas-based ready detection (Quirk 1)
- 2-step upload via direct file input (Quirk 2)
- 20s pre-poll for video (Quirk 3)
- Generation mode container anchor (Quirk 4)
- text-prefix aspect option matching (Quirk 5)
- `is-empty.is-editor-empty` verify (Quirk 6)
- `<div>` Back button (Quirk 9)
- Multiple "Generating X%" overlays (Quirk 10)

**Tests run:** import all modules; verify `isinstance` against engines.base Protocols (3/3 pass); flows registered (4); 21 selectors; 23 async actions; claude_picker._parse_choice handles JSON / markdown-fenced / digit fallback / OOR rejection.
**Result:** ALL imports + protocol conformance + parser tests pass.
**Not tested:** live Grok session (Tier 1 manual smoke test once UI runs).

---

## Module 4 — `workers/batch_image.py` + `workers/single_image.py`

**Status:** ✅ COMPLETE

**Files created:**
- `workers/__init__.py`
- `workers/_async_thread.py` (AsyncQThread — fresh asyncio loop per thread, stop_event, run_with_stop)
- `workers/batch_image.py` (BatchImageWorker)
- `workers/single_image.py` (SingleImageWorker)

**Signals:** scene_started / scene_finished / scene_failed / batch_progress / batch_done / log_message.

**Tests run (with FakeEngine):**
- 6/6 batch generation, all signals fire, state persists across reload
- force=False skip path: zero re-gen calls when scenes already ready
- single re-gen overwrites existing scene cleanly
- Exception path: status=failed + grok_no_image warning persisted

**Result:** ALL TESTS PASSED (4 scenarios).

---

## Module 5 — `ui/main_window.py` + `scene_list` + `scene_row` + `connection_panel`

**Status:** ✅ COMPLETE

**Files created:**
- `ui/__init__.py`
- `ui/connection_panel.py` (CDP URL + connect/disconnect + tab dropdown)
- `ui/scene_row.py` (per-scene 40px row: tick, status icons, regen/edit buttons)
- `ui/scene_list.py` (scrollable container, binds rows to Project)
- `ui/main_window.py` (assembles everything; batch image + single regen)

**Layout per SPEC §12.1.** Vietnamese labels: "Kết nối", "Dự án", "Batch ảnh", "Dừng", "Mở scenes.json", "Sửa prompts", etc. Status icons: ⏳ pending, 🔄 generating, ✓ ready, ❌ failed.

**Tests run (offscreen QApplication):**
- 6 rows render with mixed states (ready/generating/failed/pending)
- Tick toggle emits selected_visual_changed correctly
- refresh_row picks up state changes in place
- Batch button stays disabled until both project loaded + page_ready fired
- Warnings tooltip shows [code] msg

**Result:** ALL TESTS PASSED (6 assertions).

---

## Module 6 — `ui/dialogs/*`

**Status:** ✅ COMPLETE

**Files created:**
- `ui/dialogs/__init__.py`
- `ui/dialogs/preview_image.py` (PreviewImageDialog — 80% screen, path footer, Open folder + Re-gen buttons)
- `ui/dialogs/preview_video.py` (PreviewVideoDialog — QMediaPlayer + transport slider)
- `ui/dialogs/prompt_editor.py` (PromptEditorDialog — story_vi/en, image/video prompt, emotion, visual_type, voice_batch, duration; save vs save+regen)

**Modified:**
- `core/project.py`: added `update_scene_fields(scene_id, updates)` (Pydantic re-validation + atomic scenes.json write) and `save_scenes_json()`.
- `ui/main_window.py`: wired preview_image_clicked / preview_video_clicked / edit_clicked.

**Tests run (offscreen):** all 3 dialogs construct cleanly; PromptEditor populates from Scene + reads back via collected_updates(); Project.update_scene_fields round-trips through scenes.json (story/duration/visual_type/videoPrompt=None all survive reload).
**Result:** ALL TESTS PASSED (6 assertions).

---

## Module 7 — `runtime/estimator.py`

**Status:** ✅ COMPLETE

**Files created:**
- `runtime/__init__.py`
- `runtime/timing_history.py` (JSONL append/load + percentile helpers)
- `runtime/estimator.py` (Estimator + fmt_duration + DEFAULT_BASELINES per SPEC §15.1)

**Modified:**
- `workers/batch_image.py`: optional `estimator` kwarg; records `("gen_image", elapsed)` after each success.
- `ui/main_window.py`: owns `Estimator()`; batch button now pops confirm dialog with estimate before starting.

**Behavior:** baselines refresh from history when an action has ≥20 samples; rolling refresh every 20 new records.

**Tests run:**
- fmt_duration formats (s / phút / giờ phút)
- Default estimate for 50×gen_image: ~37 phút (P90: ~1 giờ 2 phút)
- Unknown action falls back to gen_image with warning
- 25 random samples → baselines update with computed avg/p50/p90
- <20 samples → defaults preserved (no premature refresh)
- End-to-end: BatchImageWorker writes 6 records to timing_history.jsonl

**Result:** ALL TESTS PASSED (7 assertions).

---

## Module 8 — `workers/batch_video.py` + `workers/single_video.py`

**Status:** ✅ COMPLETE

**Files created:**
- `workers/batch_video.py` (BatchVideoWorker — image-to-video, eligibility-gated)
- `workers/single_video.py` (SingleVideoWorker — re-gen one scene, validates eligibility)

**Modified:**
- `ui/main_window.py`: 2nd batch button "Batch video (I2V)"; replaced video preview re-gen stub with real SingleVideoWorker spawn.

**Eligibility:** `is_eligible(project, scene)` requires `visual_type == "video_grok"` + `videoPrompt` present + image already `ready` (I2V needs ref). Returns Vietnamese reason on rejection.

**Tests run:**
- Eligibility rules: SCENE-02 (video_grok+ref) eligible; SCENE-01 (image_grok) and SCENE-03 (no videoPrompt) rejected with correct reasons
- Missing image rejected: "chưa có ảnh ready để làm I2V"
- Batch run: 1 engine call, 5 skipped, state persists with `source_type="grok"`, path `sources/vid2.mp4`
- Single re-gen overwrites cleanly
- Ineligible single scene fails fast without engine call
- Engine exception → status=failed + grok_no_video warning persisted

**Result:** ALL TESTS PASSED (6 scenarios).

---

## Module 9 — `render/ken_burns.py`

**Status:** ✅ COMPLETE

**Files created:**
- `render/__init__.py`
- `render/ken_burns.py` (zoompan filter builder + ken_burns_self / ken_burns_continuation / extract_last_frame)

**Surface:**
- 4 directions: in / out / pan_left / pan_right
- Aspects: 16:9 → 1920×1080, 9:16 → 1080×1920
- 30 fps, h.264 + yuv420p output, no audio
- Pipeline: oversample to 2× canvas → zoompan → format yuv420p

**Tests run with REAL ffmpeg:**
- 16:9 zoom-in: ffprobe confirms 1920×1080, 60 frames @ 30fps (= 2.0s)
- 9:16 zoom-out: ffprobe confirms 1080×1920
- pan_left direction: video produced
- extract_last_frame: outputs valid PNG via -sseof
- Continuation chain: prev video → last frame → 1.5s ken_burns clip; ffprobe `1920,1080,1.500000`
- Aspect 4:3 → ValueError with Vietnamese message
- Missing source → FileNotFoundError

**Result:** ALL TESTS PASSED (7 assertions). Real videos rendered.

---

## Module 10 — `render/slideshow.py` (wrap `slideshow_v4/`)

**Status:** ✅ COMPLETE

**Files created:**
- `render/slideshow.py` (async wrapper around existing slideshow_v4 pipeline)

**slideshow_v4/** is already in place (per SPEC §3, "COPY NGUYÊN, không sửa") — wrapper does NOT modify any slideshow_v4 file.

**Surface:** `async render_slideshow(image_path, output_path, duration_sec, aspect_ratio, hint='', bg_method='auto', log_cb=None) -> Path`.

**Mechanism:**
- `tempfile.mkdtemp(prefix="slideshow_v4_")` per call (slideshow_v4 expects scene.png + .cache/ + movie/ folder layout)
- Lazy `sys.path` injection for slideshow_v4's bare imports
- `asyncio.to_thread` runs the sync 3-stage pipeline (preprocess → claude → render)
- Aspect → preset: 16:9 → "youtube" (1920×1080), 9:16 → "tiktok" (1080×1920)
- Cleanup temp dir after render

**Tests run:**
- Module imports OK, render_slideshow is coroutine
- Lazy import resolves `preprocess_scene`, `run_claude_analyze`, `validate_plan`, `render_video`
- `renderer.PRESETS` matches expected canvas sizes (youtube + tiktok)
- Aspect "4:3" → ValueError("aspect_ratio không hỗ trợ: 4:3")
- Missing source file → FileNotFoundError early

**Result:** ALL TESTS PASSED (5 assertions).
**Not CI-tested:** full end-to-end render (requires Claude CLI logged in + rembg model + real infographic image — Tier 2 manual smoke test).

---

## Module 11 — `workers/slideshow_worker.py` + `workers/ken_burns_worker.py`

**Status:** ✅ COMPLETE

**Files created:**
- `workers/slideshow_worker.py` (SlideshowWorker — wraps `render/slideshow.render_slideshow`; eligibility helper `is_slideshow_eligible`)
- `workers/ken_burns_worker.py` (KenBurnsWorker — `mode="self"` calls `ken_burns_self`, `mode="cont"` calls `ken_burns_continuation` against prev scene's video; eligibility helper `is_ken_burns_eligible`; `previous_scene_id` helper)

**Modified:**
- `ui/main_window.py`: `_regen_one_video` is now a dispatcher — switches by `scene.visual_type`:
  - `video_grok` → SingleVideoWorker (needs browser)
  - `slideshow_v4` → SlideshowWorker (offline, needs ready image)
  - `ken_burns_self` → KenBurnsWorker(mode=self) (offline, needs ready image)
  - `ken_burns_cont` → KenBurnsWorker(mode=cont) (offline, needs prev scene's video)
  - `image_grok` → friendly "không phải video" info dialog
- `ui/main_window.py`: `_show_prompt_editor`'s Save & Re-gen now dispatches by visual_type — `image_grok` → `_regen_one`, anything else → `_regen_one_video`.
- `_single_video_workers` registry retyped to `dict[str, AsyncQThread]` (any of the 3 video worker classes).

**Output state:**
- Slideshow: `source_type="slideshow"`, path `sources/vidN.mp4`.
- Ken Burns self: `source_type="ken_burns_self"`.
- Ken Burns cont: `source_type="ken_burns_cont"`.

**Warning codes added (extends SPEC §14.1):**
- `slideshow_render_failed` — generic slideshow_v4 wrapper failure.
- `ken_burns_render_failed` — generic ffmpeg/zoompan failure or eligibility refusal.

(Existing `slideshow_no_objects` from §14.1 kept — slideshow_v4 itself can still raise it; the wrapper just funnels its exceptions into `slideshow_render_failed` for now.)

**Eligibility rules:**
- slideshow: requires `image.status == ready` + `image.path`.
- ken_burns self: requires `image.status == ready`.
- ken_burns cont: requires there is a previous scene AND that scene's `video.status == ready` with a path that exists on disk.

**Tests run (real ffmpeg + temp project):**
- Eligibility helpers — 7 cases (slideshow OK / no image; KB self OK / no image; KB cont blocked on first scene / no prev video / OK after prev video ready)
- `previous_scene_id`: SCENE-01 → None, SCENE-02 → "SCENE-01"
- KB self render: SCENE-01 image (1024×768) → vid1.mp4, 10s @ 16:9, ~3s wall. State persists `status=ready`, `source_type="ken_burns_self"`, `path="sources/vid1.mp4"`. Estimator records `ken_burns_render`.
- KB cont render: SCENE-02 → vid2.mp4 derived from SCENE-01's last frame. State `source_type="ken_burns_cont"`. work_dir routed to `paths.temp_dir`.
- Failure path KB cont: reset SCENE-01 video → SCENE-02 cont fails fast with "scene trước (SCENE-01) chưa có video ready" + warning `ken_burns_render_failed` persisted.
- Failure path slideshow: SCENE-03 has no ready image → fails with "chưa có ảnh ready để render slideshow" + warning `slideshow_render_failed`.
- MainWindow constructs offscreen and exposes `_regen_one_video` + `_show_prompt_editor` dispatchers.

**Result:** ALL TESTS PASSED.
**Not CI-tested:** real slideshow_v4 end-to-end (needs Claude CLI + rembg + a real infographic source — Tier 2 manual smoke test).

---

## ✅ SPRINT 1 DONE — 2026-04-28

All 11 modules complete (Appendix A step 12 marker reached). Project status:
- core/: schema + project + paths
- engines/: base Protocols + grok adapter (browser/actions/flows/runner/claude_picker/engine)
- workers/: batch_image, single_image, batch_video, single_video, slideshow_worker, ken_burns_worker
- render/: ken_burns.py + slideshow.py (wrap of slideshow_v4/)
- runtime/: estimator.py + timing_history.py
- ui/: main_window + scene_list + scene_row + connection_panel + 3 dialogs

**Sprint 1 acceptance test** (manual, per SPEC §16) — to run with a live Grok session:
- [ ] Load scenes_template_simple.json → UI shows 6 scene rows
- [ ] Click "Batch ảnh" → 6 images generate, status icons update
- [ ] Re-gen 1 scene → that scene only updates
- [ ] Switch SCENE-03 → `slideshow_v4` (prompt editor → Save & Re-gen) → vid3.mp4 rendered offline
- [ ] Switch SCENE-04 → `ken_burns_self` → vid4.mp4 rendered offline
- [ ] Close + reopen app → state.json restores all status icons
- [ ] Force a fail → warning icon + tooltip + click-modal works

### Resume instructions (Sprint 2)

1. `cd D:\Projects\story_video_making`
2. Read this BUILD_LOG.md (top section + Sprint-1-done summary).
3. Read SPEC.md §16 Sprint 2 spec for the next module list.
4. Sprint 2 starts with voice gen (FishAudio TTS) — Appendix A step 13+.

---

## Resumption checklist (read this if resuming after close)

1. `cd D:\Projects\story_video_making`
2. `.venv\Scripts\activate`  (or use `.venv/Scripts/python.exe` directly)
3. Skim this BUILD_LOG.md table → find first row not COMPLETE
4. Re-run smoke tests for the most recent COMPLETE module to confirm nothing rotted
5. Read SPEC.md §16 + Appendix A to refresh build order
6. Continue from "Next" section above

---

## 2026-04-28 — Smoke Test prep complete

- Created `voice/__init__.py` (empty) so `import voice.fish_tts` works.
- Removed dead `VoiceModelSyntax` enum + `voice_model_syntax` field from `core/schema.py` (not in scenes.json schema; `voice/fish_tts.py` is standalone and uses its own literal).
- Created `main.py` entry point that delegates to `ui.main_window.run()`.
- Verified: `from core.schema import ScenesJson` ✓, `import voice.fish_tts` ✓, PyQt window launches and exits cleanly ✓.
