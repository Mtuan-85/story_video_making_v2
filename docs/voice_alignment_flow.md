# Voice Alignment Flow

This project uses a voice-led timeline. The MP3/WAV/M4A/FLAC file in `voice/`
is the timing source. Scene `script` is the text source used to locate each
scene inside that voice file.

## Canonical Scene Text

- `scene.script` is the only field used by voice alignment.
- `story_en` and `story_vi` are legacy fields from the fork and are not used
  for matching voice.
- `meta.language` is passed to Whisper so transcription uses the right
  language. It does not choose between script fields.

## Alignment Pipeline

1. The UI scans `voice/` and starts `VoiceAlignWorker`.
2. `voice_aligner.align_voice_to_scenes()` scans audio files and computes
   cumulative offsets.
3. Whisper transcribes all voice files into a single global word list:
   `[{word, start, end, source_file}]`.
4. The deterministic aligner walks scenes in order.
5. For a scene with non-empty `script`, it fuzzy-matches that script against
   Whisper words starting from the current cursor.
6. A matched scene receives `voice_in`, `voice_out`, `matched_text`,
   `word_indices`, and subtitle phrases.
7. A scene with empty `script` is marked silent/no-voice. It keeps its design
   duration and does not consume Whisper words.
8. After all scenes are aligned, freeze pauses are calculated from gaps between
   voiced scenes, subtracting the design duration of silent scenes between
   them.
9. Render slices voice audio only during final composite using ffmpeg `atrim`.

## Empty Script Scenes as Anchors

Empty-script scenes are visual-only anchors in the timeline.

Example:

```text
scene-01 script -> voice 0s-5s
scene-02 script empty, design duration 4s
scene-03 script -> voice starts at 9s
```

The MP3 gap between scene-01 and scene-03 is `9 - 5 = 4s`. Because scene-02
already occupies 4s visually, scene-01 gets no extra freeze pause:

```text
residual_pause = max(0, mp3_gap - silent_design_between)
               = max(0, 4 - 4)
               = 0
```

If the MP3 gap were 6s, scene-01 would receive a 2s freeze tail. This prevents
double-counting silence while preserving the MP3 as the source of truth.

## Visual Timing

For voiced scenes, the visual is fit to `voice_out - voice_in`:

- Image: rendered/zoomed for the voice duration.
- Video: sped up if the voice is shorter than design duration, capped at 1.2x.
- Video: extended with frozen tail if the voice is longer than design duration.

For silent scenes, render uses the scene design duration and silent audio.

## Render Output

`voice_mapping.json` is the contract between alignment and render. Render does
not re-match text. It uses scene IDs to pair each visual asset with its
assignment, then slices the original voice files according to `voice_in` and
`voice_out`.
