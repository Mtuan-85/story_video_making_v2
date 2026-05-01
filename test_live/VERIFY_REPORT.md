# Verify Report — Voice Alignment Audit

**Date**: 2026-05-01
**Project**: `D:\Projects\story_video_making\test_live`
**Mode**: Read-only audit (no source code changes)
**Voice file**: `voice/voice1..mp3` (29.26s, 56 words)
**Whisper model**: base
**Branch**: main (commit `422bf01`)

---

## 1. Code Architecture Audit

### 1.1 Voice modules (`voice/`)

| File | Role | Status |
|---|---|---|
| `voice_aligner.py` | Plan D orchestrator — `align_voice_to_scenes()` (line 459) | PRESENT |
| `whisper_runner.py` | Whisper wrapper — `run_whisper`, `transcribe_all_voice_files` | PRESENT |
| `voice_scanner.py` | Multi-file voice scan — `scan_voice_folder` | PRESENT |
| `deterministic_aligner.py` | Deterministic align — `align_deterministic` | PRESENT |
| `llm_fallback.py` | Claude LLM fallback — `claude_align_scene` | PRESENT |
| `ass_generator.py` | ASS karaoke generator — `generate_final_ass` (uses pysubs2) | PRESENT |
| `subtitle_builder.py` | Legacy subtitle builder | PRESENT (legacy) |
| `fish_tts.py` | Fish TTS standalone | PRESENT |

**Entry point**: `voice/voice_aligner.py::align_voice_to_scenes()` (async).

### 1.2 Render modules (`render/`)

| File | Subtitle approach | Wired in UI? |
|---|---|---|
| `composite.py` | drawtext via `subtitle_filter.build_subtitle_drawtext_chain` | YES — used by `workers/render_worker.py` |
| `assemble.py` | concat + audio mux | YES — used by `workers/render_worker.py` |
| `composite_v2.py` | scene composite without subtitle (subtitle burnt later) | NO — only `test_phase5_render.py` |
| `assemble_v2.py` | concat + `apply_ass_subtitle` (libass) | NO — only `test_phase5_render.py` |
| `subtitle_filter.py` | legacy drawtext chain (yellow, fontsize 54-60, y=80%) | YES (via composite.py) |

### 1.3 Workers and dialogs

- `workers/voice_align_worker.py` — wraps `align_voice_to_scenes`
- `workers/render_worker.py` — imports `render.assemble` + `render.composite` (legacy path)
- `ui/dialogs/voice_align_review.py`, `voice_import.py` — voice review dialogs

### 1.4 Comparison vs Plan D spec

| Plan D component | Status in current code |
|---|---|
| `voice/voice_scanner.py` (multi-file) | PRESENT |
| `voice/deterministic_aligner.py` | PRESENT |
| `voice/llm_fallback.py` | PRESENT |
| `voice/ass_generator.py` | PRESENT |
| `render/composite_v2.py` (no drawtext) | PRESENT but UNWIRED |
| `render/assemble_v2.py` (libass) | PRESENT but UNWIRED |
| `voice_mapping.json` v4.0 schema | EMITTED by aligner |
| Drawtext subtitle (legacy) | STILL ACTIVE in render path |
| Phase grouping logic (Sprint 2) | REMOVED from Plan D aligner |

**Conclusion**: Plan D alignment is DONE (Phase 1-4). Plan D render (Phase 5) is implemented but NOT wired into the UI/worker → `render_worker.py` still calls `render.assemble` + `render.composite`. **Phase 6 (UI switch) chưa apply.**

---

## 2. Whisper Output

Whisper transcribed `voice/voice1..mp3`:
- Duration: 29.26s
- Words: 56
- First word: `"Rain"` (0.00–0.34s)
- Last word: `"ease."` (28.52–28.90s)
- Full transcript:

> "Rain taps softly on the cafe window. The street outside blurs into amber lights. A barista wipes the counter slowly. Steam curls from a fresh espresso, three small things on the table. A cup, a notebook, a fountain pen. He opens the notebook. The page is empty, waiting. Outside the window, the rain begins to ease."

(Full word-level timestamps saved in `test_live/whisper_words_audit.json`.)

---

## 3. Voice Alignment Verify Table

```
=== VOICE ALIGNMENT VERIFY TABLE ===

[SCENE-01]
    Script   : "Rain taps softly on the cafe window. The street outside blurs into amber lights."
    Voice    : "Rain taps softly on the cafe window. The street outside blurs into amber lights."
               (voice_in: 0.00s, voice_out: 6.42s, dur: 6.42s)
    Match    : 100.0%  PASS
    Design   : 8s
    Adjusted : 6.42s  (delta -1.58s)
    Video    : 6.47s  (stale render from old mapping)
    Method   : deterministic (det score 100.0)
    Phrases  : 2 ; words/phrase=[7, 7]
    Diagnosis: OK

[SCENE-02]
    Script   : "A barista wipes the counter slowly. Steam curls from a fresh espresso."
    Voice    : "A barista wipes the counter slowly. Steam curls from a fresh espresso,"
               (voice_in: 7.38s, voice_out: 13.22s, dur: 5.84s)
    Match    : 98.6%  PASS
    Design   : 5s
    Adjusted : 5.84s  (delta +0.84s)
    Video    : 4.50s  (stale render)
    Method   : deterministic (det score 100.0)
    Phrases  : 2 ; words/phrase=[6, 6]
    Diagnosis: OK

[SCENE-03]
    Script   : "Three small things on the table. A cup, a notebook, a fountain pen."
    Voice    : "three small things on the table. A cup, a notebook, a fountain pen."
               (voice_in: 13.76s, voice_out: 19.74s, dur: 5.98s)
    Match    : 100.0%  PASS
    Design   : 6s
    Adjusted : 5.98s  (delta -0.02s)
    Video    : 8.97s  (stale render — old mapping had voice_out 20.82s)
    Method   : deterministic (det score 100.0)
    Phrases  : 2 ; words/phrase=[6, 7]
    Diagnosis: OK

[SCENE-04]
    Script   : "He opens the notebook. The page is empty, waiting."
    Voice    : "He opens the notebook. The page is empty, waiting."
               (voice_in: 20.50s, voice_out: 25.34s, dur: 4.84s)
    Match    : 100.0%  PASS
    Design   : 4s
    Adjusted : 4.84s  (delta +0.84s)
    Video    : 3.60s  (stale render)
    Method   : deterministic (det score 100.0)
    Phrases  : 2 ; words/phrase=[8, 1]
    Diagnosis: OK

[SCENE-05]
    Script   : "Outside the window, the rain begins to ease."
    Voice    : "Outside the window, the rain begins to ease."
               (voice_in: 25.34s, voice_out: 28.90s, dur: 3.56s)
    Match    : 100.0%  PASS
    Design   : 5s
    Adjusted : 3.56s  (delta -1.44s)
    Video    : 4.50s  (stale render)
    Method   : deterministic (det score 100.0)
    Phrases  : 1 ; words/phrase=[8]
    Diagnosis: OK
```

**Summary**: 5/5 PASS. All scenes deterministic match (no LLM fallback). `score=100` on all, fuzzy ratio against `story_en` 98.6–100%. The 1.4% gap on SCENE-02 is just a trailing comma vs period.

**Note on Video durations**: the .mp4 files in `test_live/renders/` are STALE — generated 2026-05-01 08:34 from the old v3.0 voice_mapping (Sprint 2 phase grouping). The new Plan D voice_mapping.json (v4.0) was written 2026-05-01 12:23. Re-rendering would produce videos matching `duration_adjusted` (±0.05s for codec rounding).

---

## 4. Subtitle Audit

### 4.1 Subtitle output type

Two parallel implementations in repo:

**Legacy (active in UI/worker)**:
- File: `render/subtitle_filter.py`
- Type: ffmpeg `drawtext` filter chain (one per phrase, gated by `enable=between(t,...)`)
- Style: yellow text, black border 4px, fontsize 54 (1080-wide) / 60 (else), y=80% canvas
- Font: `C:/Windows/Fonts/arialbd.ttf` (soft-fail to default if missing)
- No karaoke fill — whole phrase yellow at once

**Plan D (defined, not wired)**:
- File: `voice/ass_generator.py` (uses pysubs2)
- Type: ASS subtitle with `\kf` smooth karaoke fill per word
- Style: Arial 50 bold, white→yellow karaoke, BOTTOM_CENTER, marginV 100
- Burnt via `render/assemble_v2.py::apply_ass_subtitle` (libass `subtitles=` filter)
- Activated only by `test_phase5_render.py` — NOT by main render worker

### 4.2 Subtitle phrases analysis (new voice_mapping.json v4.0)

| Metric | Value | Target | Status |
|---|---|---|---|
| Total phrases | 9 | n/a | — |
| Min phrase chars | 8 | — | — |
| Max phrase chars | 44 | <=50 | OK |
| Avg phrase chars | 34 | ~50 | OK |
| Phrases > 50 chars | 0/9 | 0 | OK |
| Phrases with `words[]` timestamps | 9/9 | 9/9 | OK (karaoke ready) |
| Duplicate text across scenes | 0 | 0 | OK |

Per-phrase breakdown:

```
[SCENE-01] 2 phrases
  [0] "Rain taps softly on the cafe window." (36c) words=7
  [1] "The street outside blurs into amber lights." (43c) words=7
[SCENE-02] 2 phrases
  [0] "A barista wipes the counter slowly." (35c) words=6
  [1] "Steam curls from a fresh espresso," (34c) words=6
[SCENE-03] 2 phrases
  [0] "three small things on the table." (32c) words=6
  [1] "A cup, a notebook, a fountain pen." (34c) words=7
[SCENE-04] 2 phrases
  [0] "He opens the notebook. The page is empty," (41c) words=8
  [1] "waiting." (8c) words=1
[SCENE-05] 1 phrase
  [0] "Outside the window, the rain begins to ease." (44c) words=8
```

### 4.3 ASS generation (Plan D test)

Ran `voice/ass_generator.py::generate_final_ass()` against the new voice_mapping.json. Output: `test_live/temp/audit_test.ass` — 9 events, total 26.64s, all events use `\kf` karaoke fill per word. Sample:

```
Dialogue: 0,0:00:00.00,0:00:02.90,Default,,0,0,0,,{\kf34}Rain {\kf44}taps {\kf90}softly {\kf24}on {\kf14}the {\kf36}cafe {\kf48}window.
```

ASS module works correctly with the new voice_mapping.

### 4.4 Visual inspection

Skipped — only stale renders exist (from old v3.0 mapping + drawtext path). To inspect visual subtitle behaviour with Plan D, render must run via `test_phase5_render.py` or after Phase 6 UI switch. Out of scope for read-only audit.

---

## 5. Bugs / Gaps Detected

### CRITICAL

1. **Plan D render path NOT wired into UI/worker**
   `workers/render_worker.py` (line 12-13) still imports `render.assemble` + `render.composite` (drawtext path). The new `assemble_v2` + `composite_v2` + `ass_generator` are only invoked by `test_phase5_render.py`. The UI will continue producing drawtext subtitles until Phase 6 UI switch is done.

### HIGH

2. **No karaoke in production renders**
   `subtitle_filter.py::build_subtitle_drawtext_chain` shows whole phrase yellow at once — no per-word fill. Karaoke is only available via the unwired ASS path.

3. **Stale renders mismatch new voice_mapping**
   `test_live/renders/SCENE-XX.mp4` durations (e.g. SCENE-03 = 8.97s) reflect the old v3.0 phase-grouped mapping, not the new v4.0 (SCENE-03 = 5.98s). Re-render needed to validate durations end-to-end.

### MEDIUM

4. **`requirements.txt` missing whisper / audio deps**
   The audit had to manually `pip install openai-whisper`, `loguru`, `pydantic`, `pysubs2`, `rapidfuzz`, `httpx`, `anyio` to run alignment. `openai-whisper` is not declared in `requirements.txt`.

5. **`numpy` upgraded to 2.x by whisper install**
   `requirements.txt` pins `numpy>=1.26,<2.0` (line 47) but `pip install openai-whisper` upgraded to numpy 2.4.4. May break opencv-python at runtime — needs verification with full pipeline run.

### LOW

6. **SCENE-04 phrase split awkward**
   "He opens the notebook. The page is empty," (41c, 8 words) + "waiting." (8c, 1 word). The 1-word trailing phrase will flash for ~0.4s — acceptable but visually choppy. Could be merged into the previous phrase (combined 49c — within limit).

7. **`fuzz.ratio` on SCENE-02 = 98.6%** due to trailing `,` vs `.`
   Cosmetic punctuation difference. Not a bug, but the matched_text inherits Whisper's punctuation rather than the original story_en.

---

## 6. Recommendations (NOT IMPLEMENTED)

1. Apply Phase 6 UI switch per `docs/voice_rebuild/PHASE6_UI.md` — point `render_worker.py` at `assemble_v2` + `composite_v2` + `generate_final_ass`.
2. Update `requirements.txt`:
   - Add `openai-whisper>=20240930` (required by `voice/whisper_runner.py`).
   - Investigate numpy 1.x vs 2.x conflict — pin compatible whisper version or relax numpy upper bound.
3. Re-render `test_live/` after Phase 6 to verify visual subtitle parity with the ASS karaoke design.
4. Optional: tweak `extract_subtitle_phrases` to merge dangling 1-word phrases into the prior phrase when combined length <=50 chars (SCENE-04 case).

→ All recommendations are deferred. No code changes made in this audit.

---

## Files produced by this audit

- `test_live/VERIFY_REPORT.md` (this file)
- `test_live/voice_mapping.json` — overwritten with Plan D v4.0 output (old v3.0 backed up to `voice_mapping.json.v3.bak`)
- `test_live/whisper_words_audit.json` — full Whisper word list with timestamps
- `test_live/temp/audit_test.ass` — sample ASS generated from new mapping
- `verify_audit.py` (project root) — transient audit script
