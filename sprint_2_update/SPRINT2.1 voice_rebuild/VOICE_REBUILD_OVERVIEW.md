# Voice Alignment Rebuild — Plan D (Hybrid Deterministic + LLM Fallback)

> **Goal**: Replace toàn bộ Whisper+Claude alignment hiện tại bằng Plan D approach.
> **Reason**: Bug phase boundary, mismatch SCENE-03/04, không stable.
> **Approach**: Deterministic fuzzy match (hot path) + LLM fallback (cold path).

---

## Tổng quan thay đổi

### Bỏ hoàn toàn

- ❌ Phase grouping logic (group_segments_into_phases)
- ❌ Claude CLI for full alignment
- ❌ Wizard `voice_import` (UI assign per scene)
- ❌ Drawtext subtitle filter
- ❌ `voice_mapping.json` schema v3.0 (phases, scale_factor)

### Build mới

- ✅ Multiple voice files support (sort by name + offset)
- ✅ Auto-watch voice folder, auto re-trigger alignment
- ✅ Deterministic fuzzy match với rapidfuzz
- ✅ LLM fallback per scene khi score < 75
- ✅ Single ASS file karaoke (libass + pysubs2)
- ✅ 2-pass render (composite no subtitle → assemble → apply ASS)
- ✅ Visual extend/speedup theo voice duration
- ✅ `voice_mapping.json` schema v4.0

---

## Phase breakdown (build sequentially)

| Phase | Module | Effort | File MD |
|---|---|---|---|
| 1 | Voice prep + Whisper multi-file | 2-3h | PHASE1_VOICE_PREP.md |
| 2 | Deterministic aligner (rapidfuzz) | 2-3h | PHASE2_DETERMINISTIC.md |
| 3 | LLM fallback + orchestrator | 1-2h | PHASE3_LLM_FALLBACK.md |
| 4 | Single ASS karaoke generation | 2-3h | PHASE4_ASS_KARAOKE.md |
| 5 | Render extend/speedup + 2-pass | 2-3h | PHASE5_RENDER.md |
| 6 | UI cleanup + auto-watch | 2h | PHASE6_UI.md |

**Total**: ~12-16h

---

## Build order

```
Day 1: Phase 1 + 2 (voice prep + deterministic)
  - Multi-file Whisper với offset
  - rapidfuzz fuzzy match
  - COMMIT: "Voice rebuild Phase 1+2: deterministic align"

Day 2: Phase 3 (LLM fallback)
  - Claude CLI per scene
  - Orchestrator (Plan D logic)
  - Test với voice mp3 hiện tại
  - COMMIT: "Voice rebuild Phase 3: LLM fallback"

Day 3: Phase 4 (ASS karaoke)
  - pysubs2 single ASS
  - Style Arial Bold 50px white→yellow
  - COMMIT: "Voice rebuild Phase 4: ASS karaoke"

Day 4: Phase 5 (Render)
  - Extend (freeze last frame for video, slow zoom for image)
  - Speedup (setpts for video)
  - 2-pass apply ASS
  - COMMIT: "Voice rebuild Phase 5: render"

Day 5: Phase 6 (UI cleanup)
  - Bỏ wizard voice_import
  - Auto-watch voice folder
  - Replace dialog Review (simplified)
  - COMMIT: "Voice rebuild Phase 6: UI"

Day 6: E2E test + tag
  - Test full flow
  - Tag v0.3.0
```

---

## Files MD để paste cho Claude Code

| Khi nào | Paste file |
|---|---|
| Phase 1 | `PHASE1_VOICE_PREP.md` |
| Phase 2 | `PHASE2_DETERMINISTIC.md` |
| Phase 3 | `PHASE3_LLM_FALLBACK.md` |
| Phase 4 | `PHASE4_ASS_KARAOKE.md` |
| Phase 5 | `PHASE5_RENDER.md` |
| Phase 6 | `PHASE6_UI.md` |

→ Sequential, từng phase một. KHÔNG paste cùng lúc.

---

## Critical configs

| Config | Value | Note |
|---|---|---|
| SCORE_THRESHOLD | 75 | Below = fallback LLM |
| MIN_ANCHOR_SIZE | 3 | Min words for anchor match |
| MAX_ANCHOR_SIZE | 7 | Max words for anchor match |
| SEARCH_WINDOW | 50 | Word lookahead for start anchor |
| ASS font | Arial Bold | tạm thời, đổi sau |
| ASS size | 50 | tạm thời, đổi sau |
| ASS karaoke | `\kf` smooth fill | smooth highlight |
| Voice file watch | Auto | Re-trigger khi folder thay đổi |

---

## Schema voice_mapping.json v4.0

```json
{
  "version": "4.0",
  "voice_files": [
    {"file": "voice1.mp3", "duration": 16.42, "offset": 0.0},
    {"file": "voice2.mp3", "duration": 13.46, "offset": 16.42}
  ],
  "total_voice_duration": 29.88,
  "scenes": [
    {
      "id": "SCENE-01",
      "voice_in": 0.0,
      "voice_out": 8.22,
      "duration_original": 8.0,
      "duration_adjusted": 8.22,
      "is_silent": false,
      "matched_text": "Rain taps softly on the cafe window. The street outside blurs into amber lights.",
      "method": "deterministic",
      "score": 92.5,
      "subtitle_phrases": [
        {
          "text": "Rain taps softly on the cafe window.",
          "start": 0.0,
          "end": 4.1,
          "words": [
            {"word": "Rain", "start": 0.0, "end": 0.5},
            {"word": "taps", "start": 0.5, "end": 0.9}
          ]
        }
      ]
    },
    {
      "id": "SCENE-03",
      "voice_in": 17.24,
      "voice_out": 24.26,
      "duration_original": 10.0,
      "duration_adjusted": 7.02,
      "is_silent": false,
      "matched_text": "Three small things on the table. A cup, a notebook, a fountain pen.",
      "method": "llm",
      "score": 85.0,
      "fallback_from_score": 64.2,
      "reasoning": "Story spans natural silence between phrases",
      "subtitle_phrases": [...]
    },
    {
      "id": "SCENE-04",
      "voice_in": null,
      "voice_out": null,
      "duration_original": 4.0,
      "duration_adjusted": 4.0,
      "is_silent": true,
      "method": "silent",
      "subtitle_phrases": []
    }
  ],
  "stats": {
    "total_scenes": 5,
    "deterministic_count": 4,
    "llm_fallback_count": 1,
    "silent_count": 0,
    "no_match_count": 0
  }
}
```

---

## Confirm trước khi bắt đầu

- [ ] Voice mp3 hiện tại ready (test_run/voice/)
- [ ] scenes.json có story_en đầy đủ
- [ ] Whisper đang work (đã verify)
- [ ] Claude CLI available (cho fallback)
- [ ] FFmpeg có libass (đã verify)
- [ ] Backup repo hiện tại trước khi rebuild

→ Bro tải file MD về, paste Phase 1 cho Claude Code khi sẵn sàng.
