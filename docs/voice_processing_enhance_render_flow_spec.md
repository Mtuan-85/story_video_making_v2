# Voice Processing, Auto Enhance, and Render Flow Spec

## Goal

Split the final production flow into explicit stages so voice timing, scene rendering,
subtitle generation, and final mux can be tested independently.

The voice enhancement stage must be deterministic first. It should improve only clear
timing defects in generated voice, not restyle the whole narration.

## UI Stages

The final-process area should expose these controls in order:

1. `Voice Processing`
   - Build or copy the source beat voice into a raw master file.
   - Output: `voice/master_voice_raw.wav`.

2. `Auto Enhance Voice`
   - Analyze the raw voice word timing.
   - Insert missing natural pauses only where the voice is clearly too rushed.
   - Output preview file: `voice/master_voice_enhanced.wav`.
   - Output report: `voice/voice_enhance_report.json`.

3. `Whisper`
   - Dropdown source:
     - `Raw`: `voice/master_voice_raw.wav`
     - `Enhanced`: `voice/master_voice_enhanced.wav` when it exists
   - The selected source becomes the active voice source for matching, karaoke, and render.

4. `Render Scenes`
   - Render visual-only timeline.
   - Output: `temp/final_video_only.mp4`.
   - Save visual cache metadata: `temp/final_video_only.json`.

5. `Final Render`
   - Generate `final.ass` from the active voice mapping.
   - Burn karaoke subtitles.
   - Mux the active master voice and BGM.
   - Output: `final.mp4`.

## Active Voice Source Rule

Render must not guess which voice file to use.

The voice source used by render is the source selected during the latest successful
Whisper stage. If the user enhances voice but does not Whisper the enhanced file,
render still uses the last Whispered source.

State should record:

```json
{
  "voice_sources": {
    "raw": "voice/master_voice_raw.wav",
    "enhanced": "voice/master_voice_enhanced.wav"
  },
  "active_whisper_source": "raw",
  "active_master_voice": "voice/master_voice_raw.wav",
  "active_whisper_words": "voice/whisper_words_raw.json"
}
```

When the user selects `Enhanced` and runs Whisper successfully:

```json
{
  "active_whisper_source": "enhanced",
  "active_master_voice": "voice/master_voice_enhanced.wav",
  "active_whisper_words": "voice/whisper_words_enhanced.json"
}
```

## Whisper Word Format

The clean word timing file should be machine-readable and easy for diagnostics:

```json
{
  "source": "voice/master_voice_raw.wav",
  "duration": 6.14,
  "words": [
    {
      "i": 0,
      "word": "Why",
      "start": 0.0,
      "end": 0.28,
      "gap_after_ms": 0
    },
    {
      "i": 5,
      "word": "wait,",
      "start": 1.68,
      "end": 2.06,
      "gap_after_ms": 300
    }
  ]
}
```

`gap_after_ms` is computed from the next word start minus the current word end.

## Auto Enhance Algorithm

The initial version should not call AI. It should only patch obvious timing defects.

Inputs:

- Active raw voice file.
- Clean Whisper word timing.
- Beat timing and `pause_after_sec`.
- Script text, used only for punctuation and sentence grouping.

Global profile:

- Median sentence speaking rate.
- Median word duration.
- Existing pause distribution after punctuation.
- Beat-end pause distribution.

Conservative rules:

- Do not touch normal word gaps.
- Do not stretch the full voice globally.
- Prefer `insert_pause` over `atempo`.
- Only use `slow_down_range` for clear fast outliers.

Operations:

```json
{
  "version": "voice_pacing_operations.v1",
  "source": "voice/master_voice_raw.wav",
  "operations": [
    {
      "type": "insert_pause",
      "after_word_i": 16,
      "insert_ms": 420,
      "reason": "missing_sentence_pause"
    },
    {
      "type": "slow_down_range",
      "start_word_i": 30,
      "end_word_i": 44,
      "tempo": 0.96,
      "reason": "sentence_fast_outlier"
    }
  ]
}
```

Thresholds:

- Missing sentence pause:
  - Word ends with `.`, `?`, or `!`
  - Current `gap_after_ms < 180`
  - Target pause: `350-550ms`

- Missing strong clause pause:
  - Word ends with `:`, `;`, or long dash boundary
  - Current `gap_after_ms < 120`
  - Target pause: `250-400ms`

- Fast sentence outlier:
  - Sentence rate exceeds global median by a clear threshold
  - Use a mild tempo, usually `0.94-0.98`
  - Avoid tempo below `0.90` unless manually approved

- Beat end:
  - Respect `pause_after_sec` if the current end gap is too short.

## FFmpeg Application

The code, not Claude, converts operations to ffmpeg processing.

For `insert_pause`:

- Split audio at the anchor word end timestamp.
- Insert generated silence of `insert_ms`.
- Concatenate segments.

For `slow_down_range`:

- Split audio into before/range/after.
- Apply `atempo=<tempo>` only to the range.
- Concatenate.

After processing:

- Output `voice/master_voice_enhanced.wav`.
- Write `voice/voice_enhance_report.json`.
- Do not change the active render source until Whisper is run on the enhanced file.

## Render Split

`Render Scenes` builds only:

- `temp/final_video_only.mp4`
- `temp/final_video_only.json`

`Final Render` reuses visual cache when the manifest signature matches.
It then uses the active voice source from the latest Whisper stage.

This lets subtitle, BGM, and final audio tests run without re-rendering every scene.

## Future AI Option

An AI planner may be added later, but it must produce the same operations schema.
AI output is only a planning layer; ffmpeg execution remains deterministic code.
