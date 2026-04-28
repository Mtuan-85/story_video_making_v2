# SMOKE TEST PROMPT - Make UI runnable

> Goal: User wants to launch the PyQt6 app and click through:
> Connect Brave -> Load scenes.json -> Gen 1 image -> See image saved.
>
> Don't expand scope. Only do these 3 things, then stop and verify.

# ============================================================
# TASK 1: Create voice/__init__.py
# ============================================================

Create empty file: voice/__init__.py
(Just `touch` it - empty file. Required so `import voice.fish_tts` works.)

# ============================================================
# TASK 2: Cleanup VoiceModelSyntax from core/schema.py
# ============================================================

Decision from user: REMOVE VoiceModelSyntax from schema entirely.
Reason: voice_emotion_syntax field is NOT in scenes.json schema. The
voice/fish_tts.py standalone tool can use Literal["s1", "s2"] directly
without sharing an enum from core/schema.py.

Steps:
1. Open core/schema.py
2. Remove the VoiceModelSyntax class/enum (currently at line ~26)
3. Remove its import at top of file
4. Remove any reference in Settings model (if any)
5. Verify no other file imports it:
       grep -rn "VoiceModelSyntax" .
   If found in voice/fish_tts.py: replace with `Literal["s1", "s2"]`
   inline. Don't break fish_tts.py - it's a standalone tool that should
   work independently.
6. Run quick test:
       python -c "from core.schema import ScenesJson; print('OK')"

# ============================================================
# TASK 3: Create main.py entry point
# ============================================================

Create file: main.py at project root.

Look at ui/main_window.py first - if it has a `run()` function, just
call it. Otherwise wire up QApplication + qasync manually.

Skeleton (adjust based on what exists in ui/main_window.py):

```python
"""Story Video Maker - PyQt6 entry point."""
import sys
import asyncio
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
```

Verify:
   python main.py
Window should launch without crashes. Don't need to test full flow yet.

# ============================================================
# DONE CRITERIA
# ============================================================

After all 3 tasks:
1. `python -c "from core.schema import ScenesJson; print('OK')"` passes
2. `python -c "import voice.fish_tts"` passes
3. `python main.py` launches a PyQt6 window without exceptions

Stop after these 3 tasks. Do NOT build voice_split, composite, subtitle,
state_writer - those are Sprint 2/3, user wants to test UI flow first.

Append to BUILD_LOG.md: "Phase Smoke Test prep complete - voice/__init__,
schema cleanup, main.py done".
