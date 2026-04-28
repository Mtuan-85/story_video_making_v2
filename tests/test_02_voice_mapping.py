"""
Test 1.2 - Voice mapping load
Run: python tests/test_02_voice_mapping.py
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.voice_mapping import VoiceMapping


def main():
    print("=" * 60)
    print("TEST 1.2: Voice mapping")
    print("=" * 60)

    json_path = Path("examples/voice_mapping_test.json")
    if not json_path.exists():
        print(f"FAIL: File not found: {json_path}")
        sys.exit(1)

    data = json.load(open(json_path, encoding="utf-8"))
    vm = VoiceMapping(**data)

    print(f"OK: {len(vm.voice_files)} voice file(s)")
    for vf in vm.voice_files:
        print(f"  File: {vf.file}")
        print(f"  Scenes: {vf.scenes}")
    print()

    test_scene = "SCENE-03"
    file_for_scene = vm.get_file_for_scene(test_scene)
    order = vm.get_scene_index_in_file(test_scene)

    print(f"Lookup test:")
    print(f"  {test_scene} -> file: {file_for_scene}")
    print(f"  {test_scene} -> order in file: {order}")
    print()

    assert file_for_scene == "voice/voice_full.mp3", "Wrong file"
    assert order == 2, f"Wrong order, expected 2 got {order}"

    print("PASS")


if __name__ == "__main__":
    main()
