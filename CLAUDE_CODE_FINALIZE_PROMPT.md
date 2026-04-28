# SPRINT 1 - FINALIZE PROMPT

> Paste this prompt to Claude Code session at D:\Projects\story_video_making\
> after running `claude --dangerously-skip-permissions`

---

Sprint 1 build is incomplete. Audit shows you finished 6/12 modules.
Need to: (a) build 7 missing files, (b) cleanup 2 legacy items.

# CONTEXT FILES (read first)
1. D:\Projects\story_video_making\MIGRATION_PLAN.md
2. D:\Projects\story_video_making\SPEC.md
3. D:\Projects\gen_video_grok\story_render.py (READ-ONLY reference)
4. D:\Projects\gen_video_grok\grok-story-factory\pipeline_state.py (READ-ONLY)

# ============================================================
# PART A: CLEANUP (do FIRST before building new modules)
# ============================================================

## A1. Remove VoiceModelSyntax from core/schema.py

The field voice_emotion_syntax was REMOVED from the schema in our final
design. The leftover VoiceModelSyntax enum in core/schema.py is dead code
and causes confusion.

Action:
- Open core/schema.py
- Remove the VoiceModelSyntax class/enum entirely
- Remove any imports or type hints referencing it
- Verify no other file in the codebase imports VoiceModelSyntax:
    grep -r "VoiceModelSyntax" .
- If found, remove those references too

## A2. Remove FlowRunner from engines/grok/engine.py

FlowRunner was a legacy declarative-flow pattern from MASTER_grok_automation.md.
The new design uses adapter pattern via Protocol (see engines/base.py).

Action:
- Open engines/grok/engine.py
- Remove FlowRunner class entirely
- Keep GrokImageEngine and GrokVideoEngine
- Remove related imports (FlowRunner-specific helpers)
- Verify nothing else imports FlowRunner:
    grep -r "FlowRunner" .

## A3. Clean stale build artifacts

Run these commands:
    Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem -Recurse -Include "*.bak.*","*.tmp" | Remove-Item

# ============================================================
# PART B: BUILD MISSING MODULES
# ============================================================

Build these 7 files in order. After each, run a quick import test:
    python -c "from <module> import *; print('OK')"

## B1. core/voice_mapping.py
Per MIGRATION_PLAN section 2.2.

Schema:
    VoiceFileMapping: file (str), scenes (list[str])
    VoiceMapping: version, voice_files (list[VoiceFileMapping])

Methods:
    get_file_for_scene(scene_id) -> str | None
    get_scene_index_in_file(scene_id) -> int | None

Use Pydantic v2 pattern matching core/schema.py style.

## B2. voice/__init__.py
Empty file. Just create it.

## B3. voice/voice_split.py
Per MIGRATION_PLAN section 9.

Functions:
    detect_silences(audio_path, threshold_db=-30, min_duration=0.3) -> list[dict]
    find_boundaries(silences, expected_count) -> list[float]
    split_audio_file(audio_path, scene_ids, output_dir) -> dict

Implementation: use ffmpeg silencedetect filter via subprocess.

For audio with N scenes:
- N == 1: copy file as-is to scene_<id>.mp3
- N > 1: detect silences -> pick top (N-1) longest -> use as boundaries
- If silences < N-1: fallback to equal-time split + add warning

Returns:
    {"ok": bool, "scene_files": {scene_id: Path}, "warnings": [str]}

## B4. render/composite.py
Per MIGRATION_PLAN section 8.1.

Reference: D:\Projects\gen_video_grok\story_render.py function composite_scene
(lines 548-628). Copy 95% of that logic, with these modifications:
- Replace hard-coded 1080x1920 with aspect_ratio parameter (16:9 -> 1920x1080,
  9:16 -> 1080x1920)
- Add speed-match logic: if visual is video and clip_dur/audio_dur ratio is
  in [0.7, 1.4] -> setpts stretch. Else freeze tail or trim with warning.

Async function signature:
    async def composite_scene(
        visual_path: Path,
        visual_type: str,
        voice_path: Path | None,
        subtitle_frames_dir: Path | None,
        duration_sec: float,
        aspect_ratio: str,
        output_path: Path,
    ) -> dict

Returns: {"ok": bool, "warnings": list[str], "duration_actual": float}

## B5. render/assemble.py
Per MIGRATION_PLAN section 8.2.

Reference: D:\Projects\gen_video_grok\story_render.py function assemble_final
(lines 776-849). Copy 100% of that logic.

Hard-cut concat (NO xfade - causes VLC freeze).
Pre-process: normalize fps/resolution/sar/audio sample rate before concat.

Async function:
    async def assemble_scenes(
        scene_videos: list[Path],
        output_path: Path,
        aspect_ratio: str,
        fps: int = 30,
    ) -> Path

## B6. render/subtitle.py
Per MIGRATION_PLAN section 10. Phase 1 = SEGMENT-LEVEL karaoke (NOT word-level).

Reference: D:\Projects\gen_video_grok\story_render.py function
render_subtitle_frames (lines 275-419). Copy Pillow rendering logic but
ADJUST timing source from word-level to phrase-level.

Functions:
    split_text_to_phrases(text, max_words=5) -> list[str]
    estimate_phrase_timings(phrases, total_duration) -> list[dict]
    render_subtitle_frames(text, audio_duration, aspect_ratio, output_dir,
                           fps=30, font_path=None) -> Path
    get_duration(audio_path) -> float    # ffprobe wrapper

Style spec (copy from Parenting Tips):
    SUB_FONT_SIZE = 44
    SUB_PHRASE_SIZE = 5  # max 5 words/line
    SUB_POSITION_Y = 0.85  # 85% from top
    COLOR_UNREAD = (255, 255, 255, 230)
    COLOR_READ = (255, 215, 0, 255)  # yellow #FFD700
    COLOR_SHADOW = (0, 0, 0, 180)

Font path default: try assets/fonts/Montserrat-ExtraBold.ttf first, else
fallback to D:\Projects\gen_video_grok\fonts\ if exists, else PIL default.

## B7. runtime/state_writer.py
Per MIGRATION_PLAN section 12.1.

Reference: D:\Projects\gen_video_grok\grok-story-factory\pipeline_state.py.
Copy 100% of that logic.

This module is for tracking PIPELINE-LEVEL state (which task is running,
overall progress) - separate from project state.json (which tracks scene-level
status). Used by workers to write progress that UI dashboard can read.

Class:
    StateWriter(state_path: Path)
        write_task(task_name, status, **details)
        read() -> dict

## B8. main.py
PyQt6 entry point.

Skeleton:
    import sys
    from PyQt6.QtWidgets import QApplication
    from qasync import QEventLoop
    import asyncio
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

# ============================================================
# PART C: SAVE PROGRESS
# ============================================================

After each module, append to D:\Projects\story_video_making\BUILD_LOG.md:

    ## Module <name>: <status>
    Files: <list>
    Tests: <quick import test result>
    Notes: <issues, decisions>
    Timestamp: <iso>

# ============================================================
# RULES
# ============================================================

- Do NOT pause for permission. Run in auto mode.
- Stop ONLY if test fails 3 times consecutively or unrecoverable error.
- Use Vietnamese for log messages and UI labels, English for code.
- Atomic write pattern (tmp + os.replace) for any JSON file write.
- After all modules built, run audit script:
    python tests\audit.py
  And confirm all 12 modules show OK.

START with PART A cleanup, then PART B in order B1 -> B8.
