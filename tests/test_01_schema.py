"""
Test 1.1 - Schema validation
Run: python tests/test_01_schema.py
"""
import json
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schema import ScenesJson


def main():
    print("=" * 60)
    print("TEST 1.1: Schema validation")
    print("=" * 60)

    json_path = Path("examples/scenes_voice_test.json")
    if not json_path.exists():
        print(f"FAIL: File not found: {json_path}")
        sys.exit(1)

    data = json.load(open(json_path, encoding="utf-8"))
    s = ScenesJson(**data)

    print(f"OK: loaded {len(s.scenes)} scenes")
    print(f"  Language: {s.meta.language}")
    print(f"  Aspect: {s.meta.aspect_ratio}")
    print(f"  Project: {s.meta.project_id}")
    print()
    print("Scenes:")
    for sc in s.scenes:
        story = (sc.story_en or sc.story_vi or "")[:50]
        print(f"  {sc.id}: type={sc.visual_type}, dur={sc.duration}s")
        print(f"    Story: {story}...")
    print()
    print("PASS")


if __name__ == "__main__":
    main()
