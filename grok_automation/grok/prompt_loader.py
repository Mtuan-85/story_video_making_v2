"""Load and normalize prompts JSON.

Schema:
    {"prompts": [
        "plain text prompt",
        {"text": "...", "ref": "filename.jpg"},
        ...
    ]}

Output: list of {"text": str, "ref": str | None}.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_prompts(json_path: Path) -> list[dict]:
    """Load prompts JSON, normalize to {text, ref} format.

    String item        → {"text": s, "ref": None}
    Object {text, ref} → {"text": obj["text"], "ref": obj.get("ref")}
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    raw = data.get("prompts", [])

    normalized: list[dict] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                raise ValueError(f"Prompt #{i+1} là chuỗi rỗng")
            normalized.append({"text": text, "ref": None})
        elif isinstance(item, dict):
            text = (item.get("text") or "").strip()
            if not text:
                raise ValueError(f"Prompt #{i+1} thiếu trường 'text'")
            ref = item.get("ref")
            normalized.append({"text": text, "ref": ref or None})
        else:
            raise ValueError(f"Prompt #{i+1} sai kiểu (chỉ chấp nhận string hoặc dict)")

    if not normalized:
        raise ValueError("Không có prompt nào trong JSON")

    return normalized
