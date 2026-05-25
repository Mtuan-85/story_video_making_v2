# Voice Alignment Flow

This project uses a voice-led timeline. The current render path treats
`voice/voice_matching_timeline.json` and `voice/master_voice.wav` as the trusted
source of timing.

## Canonical Inputs

- `{project_stem}_S5.json` is the beat/story source for Process Voice.
- `voice/beat-XX.mp3` are the per-beat TTS files.
- `voice/master_voice.wav` is the continuous narration track built from the beat
  files plus synthetic beat pauses.
- `voice/voice_matching_timeline.json` is the timing contract consumed by final
  render.
- `voice_mapping.json` is legacy. Render may still read it for ASS subtitle
  phrases, but it is not the final timing source.

## Matching Pipeline

1. Load `{project_stem}_S5.json` and validate scene references.
2. Probe all `voice/beat-XX.mp3` files and build an exact beat timeline.
3. Concatenate beat audio and synthetic `pause_after_sec` silence into
   `voice/master_voice.wav`.
4. Whisper transcribes `master_voice.wav` once, producing global word
   timestamps.
5. Match each scene inside its beat window. The scene cursor resets per beat.
6. Allocate explicit silent/gap regions into the same timeline.
7. Save `voice/voice_matching_timeline.json` and diagnostics.

Important rule: Whisper timestamps are already global in master-audio mode. Do
not add the beat offset again.

## Final Render Contract

`RenderWorker` requires both:

```text
voice/voice_matching_timeline.json
voice/master_voice.wav
```

The render flow is:

1. Build visual-only timeline segments from `voice_matching_timeline.json`.
2. Render `scene`, `freeze_gap`, and `beat_pause` segments without audio.
3. Hard-cut concat those visual segments into `temp/final_video_only.mp4`.
4. Final ffmpeg pass muxes the continuous `master_voice.wav`, applies voice
   loudnorm, burns ASS if available, and mixes optional BGM.

This avoids the old per-scene `atrim` behavior, where cutting voice into scene
clips removed natural narration gaps between scenes.

## Subtitle Status

ASS subtitles still come from legacy `voice_mapping.json` phrase data when that
file is available. The next clean step is to generate subtitle phrases directly
from `voice_matching_timeline.json` so subtitles no longer depend on the legacy
mapping.

Current ASS style:

- Font: Cambria, bold.
- Position: middle center.
- Margins: 100px left/right/vertical.
- Wrapping: handled by ASS within margins.
