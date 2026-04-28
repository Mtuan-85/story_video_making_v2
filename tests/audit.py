"""
Audit script - kiem tra cau truc code Claude Code da build.
Run: python tests/audit.py
"""
from pathlib import Path
import sys
import importlib
import inspect


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def check_file(path: Path, must_exist: bool = True):
    exists = path.exists()
    status = "OK" if exists == must_exist else "MISSING"
    print(f"  [{status}] {path}")
    return exists


def show_module_contents(module_path: str):
    try:
        mod = importlib.import_module(module_path)
        members = [
            name for name in dir(mod)
            if not name.startswith("_")
        ]
        print(f"  Public members: {members}")

        # Show classes with their __init__ signature
        for name in members:
            obj = getattr(mod, name)
            if inspect.isclass(obj):
                try:
                    sig = inspect.signature(obj.__init__)
                    print(f"    class {name}{sig}")
                except (ValueError, TypeError):
                    print(f"    class {name}(<no signature>)")
            elif inspect.isfunction(obj):
                try:
                    sig = inspect.signature(obj)
                    print(f"    def {name}{sig}")
                except (ValueError, TypeError):
                    print(f"    def {name}(<no signature>)")
    except ImportError as e:
        print(f"  IMPORT ERROR: {e}")
    except Exception as e:
        print(f"  ERROR: {e}")


def main():
    sys.path.insert(0, str(Path(__file__).parent.parent))

    section("1. FILE STRUCTURE")
    files_to_check = [
        ("core/__init__.py", True),
        ("core/schema.py", True),
        ("core/project.py", True),
        ("core/voice_mapping.py", True),  # Should exist per MIGRATION_PLAN
        ("engines/__init__.py", True),
        ("engines/base.py", True),
        ("engines/grok/__init__.py", True),
        ("engines/grok/selectors.py", True),
        ("engines/grok/actions.py", True),
        ("engines/grok/engine.py", True),
        ("render/__init__.py", True),
        ("render/ken_burns.py", True),
        ("render/composite.py", True),
        ("render/assemble.py", True),
        ("render/subtitle.py", True),
        ("voice/__init__.py", True),
        ("voice/fish_tts.py", True),
        ("voice/voice_split.py", True),
        ("runtime/state_writer.py", True),
        ("runtime/estimator.py", True),
        ("ui/__init__.py", True),
        ("ui/main_window.py", True),
        ("workers/__init__.py", True),
        ("main.py", True),
    ]
    for path_str, must in files_to_check:
        check_file(Path(path_str), must)

    section("2. MODULE: core.schema")
    show_module_contents("core.schema")

    section("3. MODULE: core.voice_mapping")
    show_module_contents("core.voice_mapping")

    section("4. MODULE: core.project")
    show_module_contents("core.project")

    section("5. MODULE: engines.base")
    show_module_contents("engines.base")

    section("6. MODULE: engines.grok.engine")
    show_module_contents("engines.grok.engine")

    section("7. MODULE: render.ken_burns")
    show_module_contents("render.ken_burns")

    section("8. MODULE: render.composite")
    show_module_contents("render.composite")

    section("9. MODULE: render.subtitle")
    show_module_contents("render.subtitle")

    section("10. MODULE: voice.voice_split")
    show_module_contents("voice.voice_split")

    section("11. MODULE: runtime.state_writer")
    show_module_contents("runtime.state_writer")

    section("DONE")
    print()
    print("Copy toan bo output nay paste cho Claude (mac kep do dai)")


if __name__ == "__main__":
    main()
