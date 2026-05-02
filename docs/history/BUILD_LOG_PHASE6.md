# BUILD LOG — Phase 6 Wire Render + UI Realign

**Started**: 2026-05-01
**Goal**: Wire Plan D render path + UI dialog manual realign + render duration override (per `PHASE6_FINAL.md`)

---

## Schema migration gap

`PHASE6_FINAL.md` doesn't mention this — but production code paths still use the **v3.0 Pydantic VoiceMapping** (Sprint 2 phase grouping schema):

- `core/voice_mapping.py` — defines v3.0 (with `phases`, `scale_factor`)
- `core/project.py` — `model_validate(data)` v3.0
- `workers/voice_align_worker.py` — calls Sprint 2 `align_voice_file` (per-file phase grouping)
- `workers/render_worker.py` — consumes v3.0 `VoiceMapping`
- `ui/main_window.py` — typed against `VoiceMapping`
- `ui/dialogs/voice_align_review.py` — typed against `VoiceMapping`

`align_voice_to_scenes()` (Plan D) emits a **v4.0 dict** — NOT compatible with v3.0 Pydantic.

→ Must migrate schema BEFORE wiring render worker.

---

## Steps

- [x] **0. Schema migration prep** — read all v3.0 consumers, plan migration
- [x] **1a. Replace `core/voice_mapping.py` v3.0 → v4.0 Pydantic schema** — validated against test_live/voice_mapping.json
- [x] **1b. Verify `core/project.py` load/save still works** — Project.load picks up v4.0 cleanly
- [x] **1c. Update `workers/voice_align_worker.py` to call `align_voice_to_scenes`** — emits VoiceMapping v4.0; legacy `align_voice_file` block removed from voice_aligner.py
- [x] **1d. Update `ui/main_window.py` handlers for v4.0 mapping** — `_on_voice_align_done` already type-checks VoiceMapping; v4.0 model passes the same isinstance check
- [x] **1e. Update `ui/dialogs/voice_align_review.py` for v4.0 fields** — placeholder rewrite (table per scene with score color, voice_in/voice_out spin, matched_text); full feature dialog at Step 4
- [x] **1f. Wire `workers/render_worker.py` → Plan D path** — 4-pass; composite_v2 + assemble_v2 + ass_generator wired; BGM mixing TODO
- [x] **2. Test render Plan D end-to-end** — `test_live/final_v6.mp4` (26.68s) renders with karaoke ASS; frame_03.jpg shows yellow `\kf` highlight on `window`. Fix: `_STATIC_VISUAL_TYPES` no longer includes `slideshow` (file-extension fallback handles both)
- [x] **3. Build `voice/realign_helper.py`** — move_tail_to_next + move_head_to_previous; verified score 60→100 / 55→100 on synthesized mismatches
- [x] **4. Rewrite `ui/dialogs/voice_align_review.py`** — Scene cards w/ Script/Voice diff, color-coded score, render mode dropdown, Move HEAD/TAIL buttons, Re-align button. Reads whisper_words from `project_root/whisper_words.json`
- [ ] **5. Schema add `render_mode`/`render_duration`/`custom_duration` fields**
- [x] **6. Update `composite_v2` + `ass_generator` to read `render_duration`** — composite_v2 fits visual to render_duration, pads voice tail with silence when render>voice; ass_generator cursor cumulative on render_duration. Baseline E2E (mode=voice) passes — 26.68s
- [x] **7. E2E test all 5 cases from spec**
  - Test 1 — Plan D wired render: PASS (`test_phase6_render.py` → final_v6.mp4 26.68s with karaoke)
  - Test 2 — Review dialog UI: smoke import + manual GUI test pending
  - Test 3 — Move TAIL/HEAD fuzzy shrink: PASS (synthesized mismatch SC-02 60→100, SC-04 55→100)
  - Test 4 — Render duration override custom 8s on 5.98s voice: PASS (`test_phase6_override.py`, pad 2.02s silence)
  - Test 5 — Re-align all signal: wired (`re_align_requested`), GUI test pending

---

## Active step: DONE — manual GUI verification + commit pending

## Resume cheatsheet

- Test wired pipeline E2E: `python test_phase6_render.py` (uses `test_live/`).
- Re-run alignment only: `python verify_audit.py`.
- Phase 6 step 1 done: schema v4.0 + voice_align_worker + render_worker + dialog placeholder all wired.
- Pending: realign helper (move HEAD/TAIL), full review dialog rewrite, render_duration override.

## Notes / decisions

- v4.0 schema flattens phases — voice_files now only carry `file/duration/offset`; scenes live at top-level `voice_mapping["scenes"]`.
- Render worker reads voice_mapping as raw dict (skip Pydantic in worker) to avoid schema coupling. Project still validates on load.
- Existing v3.0 `voice_mapping.json` files (e.g. `test_run/`) need a one-time re-run of alignment to produce v4.0. The audit already wrote v4.0 to `test_live/voice_mapping.json` (backup at `.v3.bak`).

## Resume hints

- After re-launch: `cat BUILD_LOG_PHASE6.md` to find next unchecked step.
- Tests: `python verify_audit.py` re-runs Plan D align on `test_live/`.
- Plan D end-to-end test script: `python test_phase5_render.py` (composite_v2 + assemble_v2 path).
- Wired UI render is at `workers/render_worker.py` — call from app via "Render final" button.

