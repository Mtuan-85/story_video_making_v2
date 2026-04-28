"""
Run all Tier 1 tests in sequence.
Usage: python tests/run_tier1.py
"""
import subprocess
import sys
from pathlib import Path

TESTS = [
    "tests/test_01_schema.py",
    "tests/test_02_voice_mapping.py",
    "tests/test_03_project.py",
]


def main():
    print()
    print("#" * 70)
    print("# TIER 1: Smoke test core/ (offline, no Brave needed)")
    print("#" * 70)
    print()

    failed = []
    for test in TESTS:
        if not Path(test).exists():
            print(f"SKIP {test} (not found)")
            continue

        print(f">>> Running {test}")
        result = subprocess.run(
            [sys.executable, test],
            capture_output=False,
        )
        if result.returncode != 0:
            failed.append(test)
        print()

    print("#" * 70)
    if failed:
        print(f"# TIER 1 FAILED ({len(failed)} test(s))")
        for t in failed:
            print(f"#   - {t}")
        sys.exit(1)
    else:
        print("# TIER 1 ALL PASS")
    print("#" * 70)


if __name__ == "__main__":
    main()
