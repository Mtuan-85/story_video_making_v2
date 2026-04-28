"""
dump_ui_logic.py - Extract UI logic code for review.

Run: python dump_ui_logic.py

Output: prints all relevant code about checkboxes, buttons, and selection
counter logic. Paste output to Claude for analysis.
"""

import re
from pathlib import Path


# Keywords to find in UI code
KEYWORDS = [
    # Checkbox related
    r"QCheckBox",
    r"checkbox",
    r"checkBox",
    r"stateChanged",
    r"toggled",
    r"isChecked",
    r"setChecked",
    r"isSelected",
    r"setSelected",

    # Button enable logic
    r"setEnabled",
    r"batch.*button",
    r"batch_image",
    r"batch_video",
    r"btn_batch",

    # Counter
    r"selected_count",
    r"selected_scenes",
    r"đã chọn",
    r"selected/total",
    r"update_counter",
    r"update_count",

    # Signal connections
    r"\.connect\(",
    r"emit",

    # Selection methods
    r"def.*select",
    r"def.*toggle",
    r"def.*update",
]


def find_relevant_lines(file_path: Path, keywords: list[str]) -> list[tuple[int, str]]:
    """Find lines matching any keyword."""
    if not file_path.exists():
        return []

    lines = file_path.read_text(encoding="utf-8").splitlines()
    relevant = []

    pattern = re.compile("|".join(keywords), re.IGNORECASE)

    for i, line in enumerate(lines, start=1):
        if pattern.search(line):
            relevant.append((i, line))

    return relevant


def extract_function(file_path: Path, func_name: str, context_lines: int = 30) -> str:
    """Extract a function definition and its body."""
    if not file_path.exists():
        return ""

    lines = file_path.read_text(encoding="utf-8").splitlines()
    result = []

    in_func = False
    base_indent = None
    func_lines = 0

    for i, line in enumerate(lines):
        stripped = line.lstrip()

        if not in_func:
            # Look for function definition
            if re.match(rf"\s*(async\s+)?def\s+{func_name}\b", line):
                in_func = True
                base_indent = len(line) - len(stripped)
                result.append((i + 1, line))
                func_lines += 1
        else:
            # Already in function, check if still in body
            if line.strip() == "":
                result.append((i + 1, line))
                func_lines += 1
                continue

            current_indent = len(line) - len(stripped)
            if current_indent <= base_indent and func_lines > 1:
                # Function ended
                break

            result.append((i + 1, line))
            func_lines += 1

            if func_lines > context_lines * 3:
                result.append((i + 1, "    # ... (truncated)"))
                break

    return "\n".join(f"{n:4d} | {l}" for n, l in result)


def print_section(title: str):
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)
    print()


def main():
    project_root = Path(".")

    # Find all Python files in ui/ and workers/
    ui_files = list((project_root / "ui").rglob("*.py"))
    worker_files = list((project_root / "workers").rglob("*.py")) if (project_root / "workers").exists() else []

    all_files = ui_files + worker_files

    if not all_files:
        print("ERROR: No ui/*.py or workers/*.py files found.")
        print("       Make sure you run this from D:\\Projects\\story_video_making\\")
        return

    print_section("FILES SCANNED")
    for f in all_files:
        print(f"  - {f}")

    # ----------------------------------------------------------------
    # 1. Find ALL checkbox-related lines
    # ----------------------------------------------------------------
    print_section("1. CHECKBOX REFERENCES")

    checkbox_keywords = [
        r"QCheckBox",
        r"\.checkbox",
        r"_checkbox",
        r"isChecked",
        r"setChecked",
        r"stateChanged",
        r"toggled\(",
    ]

    for f in all_files:
        matches = find_relevant_lines(f, checkbox_keywords)
        if matches:
            print(f"\n--- {f} ---")
            for ln, line in matches:
                print(f"  {ln:4d} | {line}")

    # ----------------------------------------------------------------
    # 2. Find batch button references
    # ----------------------------------------------------------------
    print_section("2. BATCH BUTTON ENABLE LOGIC")

    button_keywords = [
        r"batch_image",
        r"batch_video",
        r"btn_batch",
        r"Batch ảnh",
        r"Batch video",
        r"setEnabled",
    ]

    for f in all_files:
        matches = find_relevant_lines(f, button_keywords)
        if matches:
            print(f"\n--- {f} ---")
            for ln, line in matches:
                print(f"  {ln:4d} | {line}")

    # ----------------------------------------------------------------
    # 3. Find counter logic
    # ----------------------------------------------------------------
    print_section("3. COUNTER / SELECTION LOGIC")

    counter_keywords = [
        r"selected_count",
        r"selected_scenes",
        r"đã chọn",
        r"Đã chọn",
        r"update.*count",
        r"count.*selected",
        r"refresh.*select",
        r"on_check",
        r"on_select",
    ]

    for f in all_files:
        matches = find_relevant_lines(f, counter_keywords)
        if matches:
            print(f"\n--- {f} ---")
            for ln, line in matches:
                print(f"  {ln:4d} | {line}")

    # ----------------------------------------------------------------
    # 4. Find ALL signal connections
    # ----------------------------------------------------------------
    print_section("4. SIGNAL CONNECTIONS (.connect)")

    for f in all_files:
        matches = find_relevant_lines(f, [r"\.connect\("])
        if matches:
            print(f"\n--- {f} ---")
            for ln, line in matches:
                print(f"  {ln:4d} | {line}")

    # ----------------------------------------------------------------
    # 5. Try to extract specific functions
    # ----------------------------------------------------------------
    print_section("5. KEY FUNCTIONS (FULL CODE)")

    target_functions = [
        "update_selected_count",
        "update_count",
        "refresh_buttons",
        "on_checkbox_changed",
        "on_scene_toggled",
        "_update_batch_buttons",
        "_count_selected",
        "selected_scenes",
        "get_selected_scene_ids",
    ]

    for f in all_files:
        for func in target_functions:
            code = extract_function(f, func)
            if code:
                print(f"\n--- {f} :: {func}() ---")
                print(code)

    # ----------------------------------------------------------------
    # 6. Find scene_row.py specifically (likely has checkbox)
    # ----------------------------------------------------------------
    print_section("6. SCENE_ROW.py FULL DUMP (if exists)")

    scene_row_candidates = [
        project_root / "ui" / "scene_row.py",
        project_root / "ui" / "scene_list.py",
        project_root / "ui" / "scenes.py",
    ]

    for candidate in scene_row_candidates:
        if candidate.exists():
            print(f"\n--- {candidate} (full file) ---")
            content = candidate.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), start=1):
                print(f"  {i:4d} | {line}")
            print()

    print()
    print("=" * 78)
    print("  DONE - paste this output to Claude for analysis")
    print("=" * 78)


if __name__ == "__main__":
    main()
