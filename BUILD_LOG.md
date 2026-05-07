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

## Known limitations

- All verification across both sessions was static (compile + headless `MainWindow()` instantiation + signature checks). The two real bug classes — (a) single regen with refs producing download spam, (b) ref-image being downloaded instead of generated image — are both unreachable in the new code paths. **Live confirmation still required**, especially Test 1 (the 30s wait fix).
- Patch markdowns at repo root (`PATCH_HUMAN_TYPING.md`, `PATCH_REF_IMAGES.md`, `PATCH_REF_PANEL_MOVE.md`, `PATCH_IMAGE_REF_ENGINE_AND_STOP_ALL.md`, `PATCH_SYNC_WAIT_IMAGE_VIDEO.md`) — archive to `docs/history/` once Sprint 3 closes.
- `.claude/settings.local.json` and deleted `BUILD_LOG_SPRINT3_FINAL.md` still in `git status` — not part of this patch series; address separately.
- `gen_image_with_refs(wait_timeout_s=60)` kwarg is now dead (timing handled inside `_wait_image_ready`). Cosmetic — clean up in a later commit if desired.
