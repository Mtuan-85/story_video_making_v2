# Learning: Render Must Follow Master Voice Timeline

Date: 2026-05-25

## Problem

The legacy render path built one mp4 per scene:

```text
scene visual + voice atrim(start=voice_in, duration=voice_out-voice_in)
  -> renders/SCENE-XX.mp4
  -> concat all scene mp4s
```

This looked logical but damaged narration pacing. Natural gaps between matched
scene windows existed in `master_voice.wav`, but per-scene `atrim` removed those
gaps before concat. The final video therefore sounded too tight between scenes.

## Decision

Final render must be timeline-native:

```text
voice_matching_timeline.json
  -> visual-only scene/gap/pause segments
  -> concat visuals
  -> mux continuous master_voice.wav in final pass
```

Voice is never split per scene in the final render path.

## Current Implementation

- `render/timeline_visual.py`
  - builds `scene`, `freeze_gap`, and `beat_pause` segments
  - renders every segment visual-only
  - concats into `temp/final_video_only.mp4`
- `workers/render_worker.py`
  - requires `voice/voice_matching_timeline.json`
  - requires `voice/master_voice.wav`
  - uses legacy `voice_mapping.json` only for ASS phrase data if present
- `render/bgm_mixer.py`
  - muxes master voice
  - applies `loudnorm=I=-16:TP=-1.5:LRA=11`
  - burns ASS if present
  - mixes sorted BGM at `-17dB` with 2s fade

## Guardrail

Do not reintroduce a fallback that converts timeline items back into
per-scene voice slices. If render has no `voice_matching_timeline.json` or no
`master_voice.wav`, fail early and ask the user to run Process Voice.

## Next Step

Generate subtitle phrases directly from `voice_matching_timeline.json` so ASS is
also timeline-native and no longer depends on legacy `voice_mapping.json`.
