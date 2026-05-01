# Phase 1 — Voice Prep + Whisper Multi-File

> **Goal**: Build voice file scanning + Whisper multi-file transcribe với global timestamps.
> **Effort**: 2-3h
> **Dependency**: openai-whisper (đã có)

---

## Module structure

### File mới

```
voice/
  ├── voice_scanner.py        # NEW — scan voice folder, sort + offset
  └── whisper_runner.py       # MODIFY — support multi-file
```

### `voice/voice_scanner.py` (NEW)

```python
"""
Scan voice folder, return sorted list with cumulative offsets.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from loguru import logger as log


@dataclass
class VoiceFileMeta:
    path: Path
    name: str
    duration: float       # seconds
    offset: float         # cumulative offset in global timeline
    
    def to_dict(self):
        return {
            "file": self.name,
            "duration": self.duration,
            "offset": self.offset,
        }


def get_audio_duration(audio_path: Path) -> float:
    """Use ffprobe to get duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def scan_voice_folder(voice_dir: Path) -> list[VoiceFileMeta]:
    """
    Scan voice folder, return sorted voice files với cumulative offsets.
    
    Sort by filename (ascending). Common conventions supported:
    - voice1.mp3, voice2.mp3, ...
    - voice_01.mp3, voice_02.mp3, ...
    - 01.mp3, 02.mp3, ...
    """
    if not voice_dir.exists():
        raise FileNotFoundError(f"Voice folder not found: {voice_dir}")
    
    # Find all mp3/wav/m4a files
    audio_files = []
    for ext in [".mp3", ".wav", ".m4a"]:
        audio_files.extend(voice_dir.glob(f"*{ext}"))
    
    if not audio_files:
        raise ValueError(f"No audio files in {voice_dir}")
    
    # Sort by name
    audio_files.sort(key=lambda f: f.name)
    
    log.info(f"Found {len(audio_files)} voice file(s):")
    for f in audio_files:
        log.info(f"  - {f.name}")
    
    # Calculate offsets
    result = []
    cursor = 0.0
    
    for f in audio_files:
        duration = get_audio_duration(f)
        meta = VoiceFileMeta(
            path=f,
            name=f.name,
            duration=duration,
            offset=cursor,
        )
        result.append(meta)
        log.info(f"  {f.name}: {duration:.2f}s (offset {cursor:.2f}s)")
        cursor += duration
    
    log.info(f"Total voice duration: {cursor:.2f}s")
    return result


def get_total_voice_duration(voice_files: list[VoiceFileMeta]) -> float:
    """Sum all durations."""
    if not voice_files:
        return 0.0
    last = voice_files[-1]
    return last.offset + last.duration


def voice_files_changed(
    voice_dir: Path, 
    cached_meta: list[dict],
) -> bool:
    """Detect if voice folder content changed since last scan.
    
    Compare:
    - File count
    - File names
    - File durations (in case file replaced with same name)
    """
    if not voice_dir.exists():
        return bool(cached_meta)
    
    current = scan_voice_folder(voice_dir)
    
    if len(current) != len(cached_meta):
        return True
    
    for cur, cached in zip(current, cached_meta):
        if cur.name != cached.get("file"):
            return True
        if abs(cur.duration - cached.get("duration", 0)) > 0.01:
            return True
    
    return False
```

### `voice/whisper_runner.py` (MODIFY)

```python
"""
Whisper transcription with multi-file support and global timestamps.
"""

import asyncio
import whisper
from pathlib import Path
from loguru import logger as log

from voice.voice_scanner import VoiceFileMeta


# Singleton model (load once, reuse)
_whisper_model = None


def get_whisper_model(model_name: str = "base"):
    """Lazy-load Whisper model (singleton)."""
    global _whisper_model
    if _whisper_model is None:
        log.info(f"Loading Whisper model: {model_name}")
        _whisper_model = whisper.load_model(model_name)
    return _whisper_model


def transcribe_single_file(
    voice_path: Path,
    offset: float = 0.0,
    language: str = "en",
    model_name: str = "base",
) -> list[dict]:
    """
    Transcribe single audio file, return words with global timestamps.
    
    Returns:
        list of word dicts: [{word, start, end, source_file}, ...]
        Timestamps are GLOBAL (offset added).
    """
    model = get_whisper_model(model_name)
    
    log.info(f"Transcribing {voice_path.name} (offset={offset:.2f}s)...")
    
    result = model.transcribe(
        str(voice_path),
        language=language,
        word_timestamps=True,
        verbose=False,
    )
    
    # Extract words from segments với global timestamps
    all_words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            all_words.append({
                "word": w["word"].strip(),
                "start": round(w["start"] + offset, 3),
                "end": round(w["end"] + offset, 3),
                "source_file": voice_path.name,
            })
    
    log.info(f"  → {len(all_words)} words extracted")
    return all_words


async def transcribe_all_voice_files(
    voice_files: list[VoiceFileMeta],
    language: str = "en",
    model_name: str = "base",
) -> list[dict]:
    """
    Transcribe all voice files, return combined words with global timestamps.
    
    Run sequentially (Whisper not thread-safe, GIL issue).
    For better perf in future: use faster-whisper or batch.
    """
    
    all_words = []
    
    for vf in voice_files:
        # Run in thread to avoid blocking event loop
        words = await asyncio.to_thread(
            transcribe_single_file,
            vf.path,
            vf.offset,
            language,
            model_name,
        )
        all_words.extend(words)
    
    log.info(f"Total transcribed words: {len(all_words)}")
    return all_words
```

---

## Test plan

### Test 1: Scan single voice file

```python
voice_dir = Path("test_run/voice")
files = scan_voice_folder(voice_dir)
assert len(files) == 1
assert files[0].offset == 0.0
assert files[0].duration > 0
```

### Test 2: Scan multiple voice files

Bro tạo voice2.mp3 (giả lập, copy voice1):
```bash
copy voice1.mp3 voice2.mp3
```

```python
files = scan_voice_folder(Path("test_run/voice"))
assert len(files) == 2
assert files[0].offset == 0.0
assert files[1].offset == files[0].duration
```

### Test 3: Whisper single file with offset

```python
words = transcribe_single_file(
    voice_path=Path("test_run/voice/voice1.mp3"),
    offset=10.0,
    language="en",
)
# All timestamps should be >= 10.0 (offset added)
assert words[0]["start"] >= 10.0
```

### Test 4: Whisper all files

```python
import asyncio
voice_files = scan_voice_folder(Path("test_run/voice"))
words = asyncio.run(transcribe_all_voice_files(voice_files))
# Verify global timestamps continuous
for i in range(1, len(words)):
    assert words[i]["start"] >= words[i-1]["start"]
```

### Test 5: Detect file changes

```python
files_initial = scan_voice_folder(voice_dir)
cached = [vf.to_dict() for vf in files_initial]

# No change → False
assert voice_files_changed(voice_dir, cached) == False

# Add file → True
# (Add voice3.mp3 manually)
assert voice_files_changed(voice_dir, cached) == True
```

---

## Build order

1. Create `voice/voice_scanner.py` (1h)
2. Modify `voice/whisper_runner.py` (1h)
3. Test với voice mp3 hiện tại (30 phút)
4. Commit

**Total: ~2-3h**

---

## Confirm trước khi code

- [ ] `whisper` library đã install trong venv
- [ ] FFmpeg + ffprobe có trong PATH
- [ ] test_run/voice/voice1..mp3 ready cho test
- [ ] Sort by filename ascending — confirm OK (voice1 < voice2 < voice10 nếu naming convention số)
  - **Note**: `voice10` sort trước `voice2` (string sort). Nếu user dùng convention `voice01`, `voice02`, `voice10` thì OK. Mình recommend bro stick với `voice01.mp3` format.

→ Build xong test pass thì proceed Phase 2.
