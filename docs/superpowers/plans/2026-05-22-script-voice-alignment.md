# Script Voice Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scene.script` the canonical voice-alignment text and treat empty-script scenes as visual-only timeline anchors.

**Architecture:** Preserve the existing Whisper -> deterministic/LLM align -> `voice_mapping.json` -> render pipeline. Narrow the script selection surface to one field, and adjust freeze-pause calculation so silent anchor scenes consume their design duration before any extra freeze is added.

**Tech Stack:** Python 3.11, Pydantic, PyQt6, pytest, ffmpeg.

---

### Task 1: Schema and UI Script Field

**Files:**
- Modify: `core/schema.py`
- Modify: `ui/dialogs/preview_dialog.py`
- Test: `tests/test_schema_meta.py`
- Test: `tests/test_voice_flow_logic.py`

- [x] Add `Scene.script`.
- [x] Keep legacy `story_en/story_vi` optional for old files.
- [x] For legacy files without `script`, populate `script` from `story_en` or `story_vi`.
- [x] Change preview dialog story editor to show and save `script`.

### Task 2: Alignment Reads Script Only

**Files:**
- Modify: `ui/main_window.py`
- Modify: `voice/deterministic_aligner.py`
- Modify: `voice/llm_fallback.py`
- Modify: `voice/realign_helper.py`
- Modify: `workers/voice_align_worker.py`
- Test: `tests/test_voice_flow_logic.py`

- [x] Pass `script` into `VoiceAlignWorker`.
- [x] Make deterministic alignment read only `scene["script"]`.
- [x] Make LLM fallback prompt use only `scene["script"]`.
- [x] Make manual realign helpers score against only `script`.
- [x] Empty `script` marks scene silent and does not advance the word cursor.

### Task 3: Empty Script Anchor Pause Math

**Files:**
- Modify: `voice/voice_aligner.py`
- Test: `tests/test_voice_flow_logic.py`

- [x] Calculate the MP3 gap between voiced scenes.
- [x] Subtract design durations of silent scenes between those voiced scenes.
- [x] Store only the residual as `freeze_pause_after`.

### Task 4: Documentation and Verification

**Files:**
- Create: `docs/voice_alignment_flow.md`

- [x] Document voice-led pipeline, canonical script field, empty-script anchors, visual timing, and render contract.
- [x] Run focused tests and py_compile on edited modules.
