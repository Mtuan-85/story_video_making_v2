# Sprint 2 — Phase 1: Voice-First Alignment Logic

> **Priority**: HIGHEST — bug đang ảnh hưởng output (scenes bị speed up).
> **Build first, before UI improvements.**

---

## Vấn đề hiện tại

### Logic hiện tại (SAI)

```
1. Load scenes.json (có duration mỗi scene)
2. Whisper transcribe voice.mp3
3. Claude CLI map segments → scenes
4. Scene voice_in/voice_out = lấy từ Whisper transcript
5. Render: scene timing = voice_out - voice_in
   → Visual phải SPEED UP để khớp voice ngắn hơn
```

→ Bug: voice override scene duration → scene bị nén → render xấu.

### Logic ĐÚNG (voice-first nhưng tôn trọng design)

```
1. scenes.json có duration là DESIGN INTENT
2. Whisper transcribe → segments với word timestamps
3. Claude CLI nhóm segments thành VOICE PHASES (theo silence > 0.5s)
4. Claude CLI map phases → scenes group (theo story similarity)
5. Adjust durations PER PHASE giữ tỉ lệ thiết kế:
   - Phase voice duration = ground truth
   - Tổng scenes durations trong phase scale theo voice duration
   - Scale factor áp dụng đều cho tất cả scenes trong phase
6. Render: scene timing = duration_adjusted (giữ tỉ lệ thiết kế)
```

---

## Concept Voice Phase

Voice phase = đoạn voice liên tục, định bằng silence threshold. Ví dụ:

```
Voice mp3 (45s):
  T=0-12s: [Phase 1] "Morning kitchen + coffee pours"
  [silence 1s]
  T=13-30s: [Phase 2] "Open window + how to make coffee 6 steps"
  [silence 0.7s]
  T=31-45s: [Phase 3] "Sit down + book + morning slow"

Mỗi phase chứa N scenes:
  Phase 1 (12s): SCENE-01 (kitchen, 8s) + SCENE-02 (coffee pour, 5s) = 13s design
    → Scale factor = 12/13 = 0.92
    → SCENE-01 adjusted = 8 × 0.92 = 7.4s
    → SCENE-02 adjusted = 5 × 0.92 = 4.6s
```

→ Giữ tỉ lệ thiết kế, chỉ scale theo voice thực tế.

---

## Implementation

### Module: rewrite `voice/voice_aligner.py`

Backup file cũ thành `voice/voice_aligner_v1_legacy.py` (KHÔNG dùng nữa).

```python
"""
Voice-first alignment logic v2.

Workflow:
1. Whisper transcribe voice → words + segments
2. Group segments into voice phases (silence detection)
3. Claude CLI map phases → scene groups
4. Calculate scale factor per phase, apply to scene durations
5. Save voice_mapping.json with adjusted durations
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger as log


@dataclass
class WhisperWord:
    word: str
    start: float
    end: float


@dataclass
class WhisperSegment:
    text: str
    start: float
    end: float
    words: List[WhisperWord]


@dataclass
class VoicePhase:
    """Voice phase: đoạn voice liên tục, ngăn cách bởi silence > threshold."""
    phase_id: int
    start: float
    end: float
    duration: float  # = end - start
    text: str
    segments: List[WhisperSegment]
    
    def __str__(self):
        return f"Phase{self.phase_id}({self.start:.2f}-{self.end:.2f}s): \"{self.text[:50]}...\""


@dataclass
class ScenePhaseMapping:
    """Map 1 phase → list scenes, với scale factor."""
    phase: VoicePhase
    scene_ids: List[str]
    original_durations: List[float]
    scale_factor: float
    adjusted_durations: List[float]


def group_segments_into_phases(
    segments: List[WhisperSegment],
    silence_threshold: float = 0.5,
) -> List[VoicePhase]:
    """Group consecutive segments by silence threshold."""
    if not segments:
        return []
    
    phases = []
    current_segments = [segments[0]]
    
    for prev, curr in zip(segments, segments[1:]):
        gap = curr.start - prev.end
        
        if gap >= silence_threshold:
            phases.append(_build_phase(len(phases) + 1, current_segments))
            current_segments = [curr]
        else:
            current_segments.append(curr)
    
    if current_segments:
        phases.append(_build_phase(len(phases) + 1, current_segments))
    
    log.info(f"Grouped {len(segments)} segments into {len(phases)} phases")
    for p in phases:
        log.info(f"  {p}")
    
    return phases


def _build_phase(phase_id: int, segments: List[WhisperSegment]) -> VoicePhase:
    return VoicePhase(
        phase_id=phase_id,
        start=segments[0].start,
        end=segments[-1].end,
        duration=segments[-1].end - segments[0].start,
        text=" ".join(s.text.strip() for s in segments),
        segments=segments,
    )


async def call_claude_for_phase_mapping(
    phases: List[VoicePhase],
    scenes: List[dict],
) -> List[List[str]]:
    """
    Use Claude CLI to map phases → scenes.
    Returns list of scene_id lists, one per phase, in scene design order.
    """
    
    phases_desc = "\n".join(
        f"  Phase {p.phase_id} ({p.start:.2f}-{p.end:.2f}s, dur={p.duration:.2f}s): \"{p.text}\""
        for p in phases
    )
    
    scenes_desc = "\n".join(
        f"  {s['id']}: design_duration={s['duration']}s, story=\"{s.get('story_en', '')}\""
        for s in scenes
    )
    
    prompt = f"""You are mapping voice phases to scenes for a video project.

VOICE PHASES (from Whisper transcript, with timestamps):
{phases_desc}

SCENES (from project design, in order):
{scenes_desc}

Task: Group scenes by voice phase. Each phase contains 1+ scenes that match the phase's story content.

Rules:
1. Scenes must remain in original order (sequential).
2. Each phase's scenes' stories should match the phase's voice text.
3. If a scene has no matching voice (silent scene), put it alone in a "silent_phase" group.

Output JSON ONLY (no markdown, no commentary):
{{
  "mapping": [
    {{"phase_id": 1, "scenes": ["SCENE-01", "SCENE-02"]}},
    {{"phase_id": 2, "scenes": ["SCENE-03"]}},
    ...
  ]
}}
"""
    
    log.info("Calling Claude CLI for phase mapping...")
    
    def _run_claude():
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = ""  # force subscription mode
        return subprocess.run(
            ["claude", "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env=env,
        )
    
    result = await asyncio.to_thread(_run_claude)
    
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI failed (rc={result.returncode}): {result.stderr[:500]}"
        )
    
    text = result.stdout.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    
    data = json.loads(text)
    mapping = data["mapping"]
    
    return [entry["scenes"] for entry in mapping]


def calculate_scale_factor(
    phase: VoicePhase,
    scene_durations: List[float],
) -> ScenePhaseMapping:
    """Calculate scale factor for a phase to match voice duration."""
    total_design = sum(scene_durations)
    
    if total_design <= 0:
        scale_factor = 1.0
        adjusted = scene_durations[:]
    else:
        scale_factor = phase.duration / total_design
        adjusted = [d * scale_factor for d in scene_durations]
    
    return ScenePhaseMapping(
        phase=phase,
        scene_ids=[],
        original_durations=scene_durations,
        scale_factor=scale_factor,
        adjusted_durations=adjusted,
    )


def warn_extreme_scale(scale: float, phase_id: int) -> Optional[str]:
    """Warn if scale factor too extreme."""
    if scale < 0.5:
        return f"Phase {phase_id}: scale {scale:.2f} < 0.5 (voice quá ngắn so với design)"
    if scale > 1.5:
        return f"Phase {phase_id}: scale {scale:.2f} > 1.5 (voice quá dài so với design)"
    return None


async def align_voice_to_scenes_v2(
    voice_path: Path,
    scenes: List[dict],
    output_dir: Path,
    whisper_model: str = "base",
    language: str = "en",
    silence_threshold: float = 0.5,
) -> dict:
    """Main alignment function."""
    
    # Step 1: Whisper transcribe
    log.info(f"Whisper transcribing {voice_path.name}...")
    from voice.whisper_runner import run_whisper_async
    
    whisper_result = await run_whisper_async(
        voice_path, output_dir, whisper_model, language
    )
    segments = _parse_whisper_segments(whisper_result)
    
    # Step 2: Group into phases
    phases = group_segments_into_phases(segments, silence_threshold)
    
    # Step 3: Claude maps phases → scenes
    phase_to_scenes = await call_claude_for_phase_mapping(phases, scenes)
    
    # Step 4: Calculate scale per phase + adjusted durations
    scenes_dict = {s["id"]: s for s in scenes}
    voice_scenes = []
    voice_phases_meta = []
    warnings = []
    
    for phase, scene_ids in zip(phases, phase_to_scenes):
        if not scene_ids:
            continue
        
        scene_durs = [scenes_dict[sid]["duration"] for sid in scene_ids]
        mapping = calculate_scale_factor(phase, scene_durs)
        mapping.scene_ids = scene_ids
        
        warn = warn_extreme_scale(mapping.scale_factor, phase.phase_id)
        if warn:
            warnings.append(warn)
            log.warning(warn)
        
        voice_phases_meta.append({
            "phase_id": phase.phase_id,
            "start": phase.start,
            "end": phase.end,
            "duration": phase.duration,
            "scenes": scene_ids,
            "scale_factor": round(mapping.scale_factor, 3),
        })
        
        cursor = phase.start
        for sid, dur_orig, dur_adj in zip(
            scene_ids, mapping.original_durations, mapping.adjusted_durations
        ):
            voice_in = cursor
            voice_out = cursor + dur_adj
            cursor = voice_out
            
            scene_phrases = _extract_subtitle_phrases(
                phase.segments, voice_in, voice_out
            )
            
            voice_scenes.append({
                "id": sid,
                "voice_in": round(voice_in, 2),
                "voice_out": round(voice_out, 2),
                "duration_original": dur_orig,
                "duration_adjusted": round(dur_adj, 2),
                "scale_factor": round(mapping.scale_factor, 3),
                "phase_id": phase.phase_id,
                "subtitle_phrases": scene_phrases,
            })
    
    # Build final structure
    voice_duration = max((s.end for s in segments), default=0.0)
    full_transcript = " ".join(s.text.strip() for s in segments)
    
    return {
        "version": "3.0",
        "voice_files": [{
            "file": str(voice_path.relative_to(voice_path.parent.parent)),
            "duration": voice_duration,
            "transcript": full_transcript,
            "phases": voice_phases_meta,
            "scenes": voice_scenes,
        }],
        "warnings": warnings,
    }


def _parse_whisper_segments(whisper_json: dict) -> List[WhisperSegment]:
    segments = []
    for seg in whisper_json.get("segments", []):
        words = [
            WhisperWord(w["word"], w["start"], w["end"])
            for w in seg.get("words", [])
        ]
        segments.append(WhisperSegment(
            text=seg["text"],
            start=seg["start"],
            end=seg["end"],
            words=words,
        ))
    return segments


def _extract_subtitle_phrases(
    segments: List[WhisperSegment],
    voice_in: float,
    voice_out: float,
) -> List[dict]:
    phrases = []
    for seg in segments:
        if seg.end < voice_in or seg.start > voice_out:
            continue
        start = max(seg.start, voice_in)
        end = min(seg.end, voice_out)
        if end - start < 0.3:
            continue
        phrases.append({
            "text": seg.text.strip(),
            "start": round(start, 2),
            "end": round(end, 2),
        })
    return phrases
```

### Update render logic

`render/composite.py` cần dùng `duration_adjusted`:

```python
def composite_scene(scene_id, voice_mapping, scenes_json):
    voice_scene = next(
        s for s in voice_mapping["voice_files"][0]["scenes"]
        if s["id"] == scene_id
    )
    
    # CRITICAL: dùng duration_adjusted, KHÔNG phải voice_out - voice_in
    scene_duration = voice_scene["duration_adjusted"]
    voice_in = voice_scene["voice_in"]
    voice_out = voice_scene["voice_out"]
    
    # Visual: scale theo duration_adjusted
    # Voice slice: từ voice_in đến voice_out
    # ...
```

### Update voice_align_review dialog

Hiển thị thêm:
- Phase grouping rõ ràng
- Scale factor mỗi phase
- Warnings nếu scale > 1.5 hoặc < 0.5
- Allow user override scale factor (advanced, optional)

Layout mới:

```
Phase 1 (0.00s - 12.00s, voice_dur=12.0s)  Scale: 0.92  ✅
  ├─ SCENE-01: voice_in=0.0, voice_out=7.4, dur_adj=7.4 (orig 8.0)
  └─ SCENE-02: voice_in=7.4, voice_out=12.0, dur_adj=4.6 (orig 5.0)

Phase 2 (13.00s - 30.00s, voice_dur=17.0s)  Scale: 1.42  ⚠️
  ├─ SCENE-03: voice_in=13.0, voice_out=22.0, dur_adj=9.0 (orig 6.3)
  └─ SCENE-04: voice_in=22.0, voice_out=30.0, dur_adj=8.0 (orig 5.6)

Phase 3 (...)
```

### Backup voice_mapping cũ

Trước khi run alignment v2 lần đầu, backup:
```python
if voice_mapping_path.exists():
    backup = voice_mapping_path.with_suffix(".json.v2.bak")
    shutil.copy(voice_mapping_path, backup)
```

---

## Test Plan

### Test 1: Voice match design
- Voice mp3 hiện tại + scenes.json hiện tại
- Expected: 7 phases (mỗi đoạn voice riêng)
- Scale factors: gần 1.0
- Warnings: không có

### Test 2: Voice ngắn hơn design
- Cắt voice mp3 còn 30s
- Expected: scale factors < 1.0 (scenes bị nén)
- Warning nếu scale < 0.5

### Test 3: Voice dài hơn design
- Voice 60s, scenes design 45s
- Expected: scale factors > 1.0
- Warning nếu scale > 1.5

### Test 4: Edge case - silent scene
- Thêm SCENE-08 vào scenes.json không có matching voice
- Expected: SCENE-08 không có trong voice_mapping (skip)

### Test 5: Render verify
- Sau alignment, render final.mp4
- Verify tổng duration = voice duration
- Verify mỗi scene visible trong khoảng voice_in/voice_out

---

## Build Order

1. **voice/voice_aligner.py rewrite** (3-4h)
2. **render/composite.py update** (1h)
3. **ui/dialogs/voice_align_review.py update** (1-2h)
4. **End-to-end test** (1h)

**Total: ~6-8h**

---

## Confirm trước khi code

- [ ] Schema version bump 2.0 → 3.0
- [ ] Backup voice_mapping.json trước khi overwrite
- [ ] silence_threshold default = 0.5s
- [ ] Warnings extreme scale (< 0.5 hoặc > 1.5)
- [ ] Render dùng duration_adjusted

Build từng phần, test sau mỗi phần.
