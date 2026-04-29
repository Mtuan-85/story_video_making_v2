"""
fish_tts.py — Fish Audio TTS Tool
Du an: Story Video Making

USAGE:
    # 1. Cai SDK:
    uv pip install fish-audio-sdk

    # 2. Set API key:
    set FISH_API_KEY=your_key                  # Windows CMD
    $env:FISH_API_KEY = "your_key"             # PowerShell

    # 3. List voice models dang co:
    python voice\\fish_tts.py --list-voices --self
    python voice\\fish_tts.py --list-voices --voice-language vi

    # 4. Gen TTS tu scenes.json:
    python voice\\fish_tts.py test_run\\scenes.json


FISH AUDIO MODEL CONCEPT:

    A. TTS Engine (S1 / S2):
       - KHONG select qua TTSConfig parameter
       - Fish Audio tu route based on emotion syntax trong text:
            "(happy) Hello!"     -> S1 path (parenthesis tag)
            "[warm tone] Hello!" -> S2 path (bracket tag)

    B. Voice Model (reference_id):
       - 32-char hex ID, vd: "d5c98734e99c4cc4b51e176460f1537c"
       - Pass qua reference_id trong TTSConfig
       - List qua --list-voices o script nay


EMOTION SYNTAX:

    S1 (parenthesis) - fixed tag list (happy, sad, calm, ...)
    S2 (bracket)     - free-form natural language [warm narrator tone]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime


# ============================================================================
# Load + validate scenes.json
# ============================================================================

def load_scenes(json_path: Path) -> dict:
    if not json_path.exists():
        raise FileNotFoundError(f"Khong tim thay file: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if "scenes" not in data or not data["scenes"]:
        raise ValueError("File JSON phai co truong 'scenes' va co du lieu")

    # Auto-detect language: check meta.language hoac fallback story_vi
    lang = data.get("meta", {}).get("language", "vi")
    story_field = f"story_{lang}"

    for scene in data["scenes"]:
        # voice_batch_id no longer in project schema — default to 1.
        scene.setdefault("voice_batch_id", 1)
        # Try story_<lang> first, fallback to story_vi or story_en
        story = scene.get(story_field) or scene.get("story_vi") or scene.get("story_en")
        if not story or not story.strip():
            raise ValueError(f"Scene {scene.get('id', '?')} thieu story (story_{lang}/story_vi/story_en)")

    return data


# ============================================================================
# Emotion application
# ============================================================================

def apply_emotion(scene: dict, syntax: str = "s2", lang: str = "vi") -> str:
    """Apply emotion tag vao story field theo language."""
    # Try story_<lang> first, fallback to whatever exists
    story_field = f"story_{lang}"
    story = (scene.get(story_field) or scene.get("story_vi") or scene.get("story_en") or "").strip()
    emotion = scene.get("emotion", "").strip()

    if ("(" in story and ")" in story) or ("[" in story and "]" in story):
        return story

    if emotion:
        if syntax == "s1":
            return f"({emotion}) {story}"
        else:
            return f"[{emotion}] {story}"

    return story


# ============================================================================
# TTS Generation
# ============================================================================

def generate_tts(
    scenes_json: Path,
    output_dir: Path = Path("voice_output"),
    voice_id: str | None = None,
    emotion_syntax: str = "s2",
    speed: float = 1.0,
    volume: int = 0,
    temperature: float = 0.7,
    top_p: float = 0.7,
    output_format: str = "mp3",
    mp3_bitrate: int = 192,
    latency: str = "balanced",
    force: bool = False,
    api_key: str | None = None,
):
    """Pipeline gen TTS chinh."""

    try:
        from fishaudio import FishAudio
        from fishaudio.types import TTSConfig, Prosody
        from fishaudio.utils import save
    except ImportError:
        raise RuntimeError(
            "Chua cai fish-audio-sdk. Chay: uv pip install fish-audio-sdk"
        )

    print(f"Load: {scenes_json}")
    data = load_scenes(scenes_json)
    scenes = data["scenes"]
    settings = data.get("settings", {})

    # Detect language tu meta
    lang = data.get("meta", {}).get("language", "vi")

    # Override config tu scenes.json settings
    if not voice_id and settings.get("voice_model_id"):
        sid = settings["voice_model_id"]
        if sid and sid != "PUT_FISH_AUDIO_VOICE_ID_HERE":
            voice_id = sid

    # Warning: voice_id giong API key (dau hieu confused)
    if voice_id and api_key and voice_id == api_key:
        print()
        print("=" * 60, file=sys.stderr)
        print("WARNING: voice_model_id == API key", file=sys.stderr)
        print("Day la 2 thu KHAC NHAU mac du cung 32-char hex:", file=sys.stderr)
        print("  - API key: lay tu fish.audio/app/api-keys", file=sys.stderr)
        print("  - Voice ID: lay tu fish.audio/m/{id}", file=sys.stderr)
        print("Bo qua voice_model_id, dung default voice...", file=sys.stderr)
        print("Chay --list-voices --self de xem voice ID dung", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print()
        voice_id = None

    if speed == 1.0 and settings.get("voice_speed"):
        speed = float(settings["voice_speed"])

    if volume == 0 and settings.get("voice_volume") is not None:
        volume = int(settings["voice_volume"])

    if settings.get("voice_emotion_syntax"):
        emotion_syntax = settings["voice_emotion_syntax"]

    print(f"  Total scenes: {len(scenes)}")
    print(f"  Voice ID: {voice_id or '(default voice)'}")
    print(f"  Language: {lang}")
    print(f"  Emotion syntax: {emotion_syntax}")
    print(f"  Speed: {speed}x, Volume: {volume:+d}")

    batches = {}
    for scene in scenes:
        bid = scene.get("voice_batch_id", 1)
        batches.setdefault(bid, []).append(scene)

    print(f"\nBatches: {len(batches)}")
    for bid in sorted(batches.keys()):
        scene_ids = [s["id"] for s in batches[bid]]
        print(f"  Batch {bid}: {len(scene_ids)} scenes ({', '.join(scene_ids)})")

    client = FishAudio(api_key=api_key) if api_key else FishAudio()

    output_dir.mkdir(parents=True, exist_ok=True)
    batch_files = {}

    for batch_id in sorted(batches.keys()):
        batch_scenes = batches[batch_id]
        output_path = output_dir / f"batch_{batch_id}.mp3"

        print(f"\n--- Batch {batch_id} ---")

        if not force and output_path.exists():
            print(f"  Skip (exists): {output_path.name}")
            print(f"  Use --force to re-gen")
            batch_files[batch_id] = output_path
            continue

        full_text = " ".join(apply_emotion(s, emotion_syntax, lang) for s in batch_scenes)
        print(f"  Text length: {len(full_text)} chars")

        config_kwargs = {
            "format": output_format,
            "latency": latency,
            "temperature": temperature,
            "top_p": top_p,
            "prosody": Prosody(speed=speed, volume=volume),
        }
        if voice_id:
            config_kwargs["reference_id"] = voice_id
        if output_format == "mp3":
            config_kwargs["mp3_bitrate"] = mp3_bitrate

        config = TTSConfig(**config_kwargs)

        try:
            print(f"  Generating...")
            audio = client.tts.convert(text=full_text, config=config)
            save(audio, str(output_path))

            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"  Saved: {output_path.name} ({size_mb:.2f} MB)")
            batch_files[batch_id] = output_path

        except Exception as e:
            err_msg = str(e)
            # Auto-retry khong voice_id neu Reference not found
            if "Reference not found" in err_msg and voice_id:
                print(f"  WARNING: voice_id '{voice_id[:8]}...' khong ton tai", file=sys.stderr)
                print(f"  Retry voi DEFAULT voice (no reference_id)...", file=sys.stderr)
                try:
                    config_kwargs.pop("reference_id", None)
                    config_retry = TTSConfig(**config_kwargs)
                    audio = client.tts.convert(text=full_text, config=config_retry)
                    save(audio, str(output_path))
                    size_mb = output_path.stat().st_size / (1024 * 1024)
                    print(f"  Saved (default voice): {output_path.name} ({size_mb:.2f} MB)")
                    batch_files[batch_id] = output_path
                    voice_id = None  # update for manifest
                except Exception as e2:
                    print(f"  RETRY FAILED: {e2}", file=sys.stderr)
                    raise
            else:
                print(f"  ERROR: {e}", file=sys.stderr)
                raise

    # Manifest
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "voice_config": {
            "voice_id": voice_id,
            "emotion_syntax": emotion_syntax,
            "speed": speed,
            "volume": volume,
            "temperature": temperature,
            "top_p": top_p,
        },
        "batches": [],
    }
    for bid in sorted(batches.keys()):
        scenes_in_batch = batches[bid]
        manifest["batches"].append({
            "batch_id": bid,
            "file": batch_files[bid].name if bid in batch_files else None,
            "scenes": [
                {
                    "scene_id": s["id"],
                    "order_in_batch": idx,
                    "raw_story": (s.get(f"story_{lang}") or s.get("story_vi") or s.get("story_en") or ""),
                    "emotion": s.get("emotion", ""),
                    "expected_duration_sec": s.get("duration"),
                }
                for idx, s in enumerate(scenes_in_batch)
            ],
        })

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nManifest: {manifest_path}")
    print(f"Done. Output: {output_dir}")
    return batch_files, manifest


# ============================================================================
# List Voice Models
# ============================================================================

def list_voices(
    api_key: str | None = None,
    self_only: bool = False,
    page_size: int = 20,
    page_number: int = 1,
    title_filter: str | None = None,
    language_filter: str | None = None,
    export_json: Path | None = None,
):
    """
    List voice models.

    SDK signature (theo Fish Audio docs):
        client.voices.list(
            page_size=10,
            page_number=1,
            title=...,
            tags=...,
            self_only=False,         # <-- TEN PARAMETER DUNG (khong phai 'self')
            author_id=...,
            language=...,
            sort_by="task_count",
        )
    """
    try:
        from fishaudio import FishAudio
    except ImportError:
        raise RuntimeError("Chua cai fish-audio-sdk. Chay: uv pip install fish-audio-sdk")

    client = FishAudio(api_key=api_key) if api_key else FishAudio()

    print(f"Listing voice models...")
    print(f"  self_only: {self_only}")
    print(f"  page_size: {page_size}, page_number: {page_number}")
    if title_filter:
        print(f"  title filter: {title_filter}")
    if language_filter:
        print(f"  language filter: {language_filter}")
    print()

    list_kwargs = {
        "page_size": page_size,
        "page_number": page_number,
        "self_only": self_only,    # CORRECT PARAM NAME
    }
    if title_filter:
        list_kwargs["title"] = title_filter
    if language_filter:
        list_kwargs["language"] = [language_filter]

    try:
        result = client.voices.list(**list_kwargs)
    except Exception as e:
        print(f"ERROR calling voices.list: {e}", file=sys.stderr)
        print(f"  list_kwargs: {list_kwargs}", file=sys.stderr)
        raise

    items = getattr(result, "items", None) or result.get("items", [])
    total = getattr(result, "total", None) or result.get("total", 0)

    print(f"Total voices: {total}")
    print(f"Showing: {len(items)} (page {page_number}, size {page_size})")
    print()
    print(f"{'#':<4}{'ID':<36}{'Title':<32}{'Languages':<14}{'State':<10}")
    print("-" * 100)

    voices_data = []
    for i, item in enumerate(items, 1):
        # Helper get attr/dict-key
        def gv(obj, key, default=""):
            return getattr(obj, key, None) or (obj.get(key, default) if isinstance(obj, dict) else default)

        vid = gv(item, "_id") or gv(item, "id")
        title = gv(item, "title", "")
        langs = gv(item, "languages", []) or []
        state = gv(item, "state", "")
        tags = gv(item, "tags", []) or []
        description = gv(item, "description", "")

        langs_str = ",".join(langs) if isinstance(langs, list) else str(langs)
        tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)

        title_disp = title[:30] + ".." if len(title) > 30 else title
        langs_disp = langs_str[:12] + ".." if len(langs_str) > 12 else langs_str

        print(f"{i:<4}{vid:<36}{title_disp:<32}{langs_disp:<14}{state:<10}")

        voices_data.append({
            "id": vid,
            "title": title,
            "description": description,
            "languages": langs if isinstance(langs, list) else [langs_str],
            "tags": tags if isinstance(tags, list) else [tags_str],
            "state": state,
        })

    print()
    print("Tip: copy ID 32 chars de dat vao scenes.json -> settings.voice_model_id")
    print("     hoac dung --voice-id de truyen truc tiep")

    if export_json:
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "filter": {
                "self_only": self_only,
                "title": title_filter,
                "language": language_filter,
            },
            "total": total,
            "voices": voices_data,
        }
        export_json.parent.mkdir(parents=True, exist_ok=True)
        export_json.write_text(
            json.dumps(export_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nExported to: {export_json}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fish Audio TTS Tool - Story Video Making",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
    # List voice cua minh:
    python voice\\fish_tts.py --list-voices --self

    # Filter language Vietnamese, save ra file:
    python voice\\fish_tts.py --list-voices --voice-language vi --export-voices voices_vi.json

    # Search title:
    python voice\\fish_tts.py --list-voices --voice-title "vietnamese"

    # Gen TTS:
    python voice\\fish_tts.py test_run\\scenes.json
    python voice\\fish_tts.py test_run\\scenes.json --voice-id ABC --speed 1.1
    python voice\\fish_tts.py test_run\\scenes.json --force
        """
    )

    parser.add_argument("--list-voices", action="store_true",
                        help="List voice models thay vi gen TTS")

    parser.add_argument("scenes_json", type=Path, nargs="?",
                        help="Path den scenes.json")
    parser.add_argument("--output-dir", type=Path, default=Path("voice_output"))
    parser.add_argument("--voice-id", type=str, default=None,
                        help="Voice reference_id (32-char hex)")
    parser.add_argument("--emotion-syntax", choices=["s1", "s2"], default="s2",
                        help="Emotion tag syntax. Default s2 (bracket).")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--volume", type=int, default=0)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.7)
    parser.add_argument("--force", action="store_true",
                        help="Force re-gen, ngay ca khi batch_*.mp3 da ton tai")

    # List voices specific
    parser.add_argument("--self", dest="self_only", action="store_true",
                        help="Chi list voice cua minh")
    parser.add_argument("--page-size", type=int, default=20,
                        help="So voice/trang. Max 100.")
    parser.add_argument("--page-number", type=int, default=1)
    parser.add_argument("--voice-title", type=str, default=None,
                        help="Filter title")
    parser.add_argument("--voice-language", type=str, default=None,
                        help="Filter language, vd: vi, en")
    parser.add_argument("--export-voices", type=Path, default=None,
                        help="Export ket qua list voices ra file JSON")

    parser.add_argument("--api-key", type=str, default=None)

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("FISH_API_KEY")
    if not api_key:
        print("ERROR: Chua co API key.", file=sys.stderr)
        print('  PowerShell: $env:FISH_API_KEY = "your_key"', file=sys.stderr)
        print('  CMD:        set FISH_API_KEY=your_key', file=sys.stderr)
        sys.exit(1)

    try:
        if args.list_voices:
            list_voices(
                api_key=api_key,
                self_only=args.self_only,
                page_size=args.page_size,
                page_number=args.page_number,
                title_filter=args.voice_title,
                language_filter=args.voice_language,
                export_json=args.export_voices,
            )
        else:
            if not args.scenes_json:
                print("ERROR: Phai cung cap scenes.json (hoac dung --list-voices)", file=sys.stderr)
                parser.print_help()
                sys.exit(1)

            generate_tts(
                scenes_json=args.scenes_json,
                output_dir=args.output_dir,
                voice_id=args.voice_id,
                emotion_syntax=args.emotion_syntax,
                speed=args.speed,
                volume=args.volume,
                temperature=args.temperature,
                top_p=args.top_p,
                force=args.force,
                api_key=api_key,
            )
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
