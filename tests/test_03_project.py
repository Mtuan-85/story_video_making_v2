"""
Test 1.3 - Project class (uses Project.load classmethod)
Run: python tests/test_03_project.py
"""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.project import Project


def main():
    print("=" * 60)
    print("TEST 1.3: Project.load() classmethod")
    print("=" * 60)

    # Setup test project folder
    test_dir = Path("test_project")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()

    # Copy scenes.json
    shutil.copy("examples/scenes_voice_test.json", test_dir / "scenes.json")

    # Test load (state.json se duoc tao tu dong lan dau)
    print(f"Loading from: {test_dir}")
    p = Project.load(test_dir)

    print()
    print(f"Loaded: {len(p.scenes)} scenes")
    print(f"Project paths root: {p.paths.root}")
    print(f"Scenes JSON: {p.paths.scenes_json}")
    print(f"State JSON: {p.paths.state_json}")
    print()

    # Verify state.json duoc tao
    assert p.paths.state_json.exists(), "state.json should be auto-created"
    print(f"OK: state.json auto-created")

    # Test scene access
    scene_01 = p.scene("SCENE-01")
    print(f"\nSCENE-01:")
    print(f"  visual_type: {scene_01.visual_type}")
    print(f"  duration: {scene_01.duration}")

    # Test scene_index (1-based)
    idx = p.scene_index("SCENE-03")
    print(f"\nSCENE-03 index (1-based): {idx}")
    assert idx == 3, f"Expected 3, got {idx}"

    # Test get_scene_state
    state_01 = p.get_scene_state("SCENE-01")
    print(f"\nSCENE-01 initial state:")
    print(f"  image.status: {state_01['image']['status']}")
    print(f"  video.status: {state_01['video']['status']}")
    print(f"  voice.status: {state_01['voice']['status']}")
    assert state_01["image"]["status"] == "pending"

    # Test mutation
    print()
    print("Test mutation: set SCENE-01 image to 'ready'...")
    p.update_scene_state("SCENE-01", "image", {
        "status": "ready",
        "path": "sources/pic1.jpg",
    })

    # Re-read state to verify persistence
    state_01_after = p.get_scene_state("SCENE-01")
    assert state_01_after["image"]["status"] == "ready"
    assert state_01_after["image"]["path"] == "sources/pic1.jpg"
    print(f"OK: state persisted")

    # Test reload to verify file is correct
    print()
    print("Reloading project to verify state persistence...")
    p2 = Project.load(test_dir)
    state_01_reloaded = p2.get_scene_state("SCENE-01")
    assert state_01_reloaded["image"]["status"] == "ready"
    print(f"OK: state.json reload correct")

    # Test add_warning
    print()
    p.add_warning("SCENE-02", "test_warning", "This is a test warning")
    warnings = p.get_scene_state("SCENE-02").get("warnings", [])
    assert len(warnings) == 1
    print(f"OK: warning added")

    print()
    print("PASS")
    print()
    print(f"Note: keeping {test_dir}/ for next tests")


if __name__ == "__main__":
    main()
