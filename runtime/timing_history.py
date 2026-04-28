"""Append-only JSONL log of measured action durations.

Each line: {"action": "gen_image", "duration_sec": 47.2, "ts": "..."}.
The estimator periodically rolls these into refreshed baselines.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from loguru import logger as log

DEFAULT_HISTORY_PATH = Path("runtime") / "timing_history.jsonl"


def append(path: Path, action: str, duration_sec: float) -> None:
    """Atomically append one record. Creates parent dir if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "action": action,
        "duration_sec": float(duration_sec),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load(path: Path) -> list[dict]:
    """Load all records. Skips malformed lines."""
    path = Path(path)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception as e:
                log.warning(f"timing_history.jsonl line {line_no} bad: {e}")
    return out


def filter_by_action(records: Iterable[dict], action: str) -> list[float]:
    return [
        float(r["duration_sec"])
        for r in records
        if r.get("action") == action and isinstance(r.get("duration_sec"), (int, float))
    ]


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile. p in [0, 100]. Empty list → 0."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (p / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + frac * (s[hi] - s[lo])
