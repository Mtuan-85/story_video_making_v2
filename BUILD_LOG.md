# Build Log — Sprint 3 Final Patches

> Resume hint: open this file first when you return. Pending live-test
> checklist is at the bottom. Static checks all pass.

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
