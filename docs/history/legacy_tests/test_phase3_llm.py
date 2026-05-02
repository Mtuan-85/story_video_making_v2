"""Phase 3 — verify LLM fallback path actually invokes Claude CLI."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.llm_fallback import claude_align_scene


def make_words(text: str, t0: float = 0.0, dt: float = 0.4) -> list[dict]:
    out = []
    t = t0
    for w in text.split():
        out.append({"word": w, "start": round(t, 2), "end": round(t + dt, 2)})
        t += dt
    return out


# Build a small whisper transcript and a scene whose story matches mid-window.
whisper = make_words(
    "Welcome everyone today we will see a calm morning kitchen scene with steam"
    " and warm sunlight and an open notebook on the wooden table"
)
scene = {
    "id": "SCENE-X",
    "story_en": "calm morning kitchen scene with steam and warm sunlight",
}

print(f"Whisper has {len(whisper)} words.")
print(f"Scene story: '{scene['story_en']}'")

result = asyncio.run(claude_align_scene(
    scene=scene,
    whisper_words=whisper,
    search_start_idx=0,
    search_end_idx=len(whisper) - 1,
))

print("\n=== LLM result ===")
for k, v in result.items():
    print(f"  {k}: {v}")

assert result["id"] == "SCENE-X"
if result["is_silent"]:
    raise AssertionError(f"LLM returned silent unexpectedly: {result}")

assert result["method"] == "llm", f"method={result['method']}"
assert result["voice_in"] is not None
assert result["voice_out"] is not None
assert result["voice_out"] > result["voice_in"]
assert 0 <= result["word_indices"][0] <= result["word_indices"][1] < len(whisper)
print("\nPASS — LLM fallback path works end-to-end")
