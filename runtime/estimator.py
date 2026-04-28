"""Time estimator with self-improving baselines.

Per SPEC §15: defaults are conservative starter values; once we have ≥20
recorded samples for an action, refresh baselines from observed p50/p90/p99.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger as log

from runtime import timing_history

DEFAULT_BASELINES: dict[str, dict[str, float]] = {
    "gen_image": {"avg": 45, "p50": 40, "p90": 75, "p99": 120},
    "gen_video": {"avg": 180, "p50": 165, "p90": 240, "p99": 360},
    "slideshow_render": {"avg": 30, "p50": 25, "p90": 50, "p99": 90},
    "ken_burns_render": {"avg": 5, "p50": 4, "p90": 8, "p99": 15},
    "voice_gen_per_100chars": {"avg": 3, "p50": 2.5, "p90": 5, "p99": 10},
}

REFRESH_EVERY_N = 20  # rolling: refresh after this many new samples


def fmt_duration(seconds: float) -> str:
    """Vietnamese-friendly duration: '~38 phút' or '~1 giờ 12 phút'."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"~{s}s"
    minutes = s // 60
    if minutes < 60:
        return f"~{minutes} phút"
    hours = minutes // 60
    rem_min = minutes % 60
    if rem_min == 0:
        return f"~{hours} giờ"
    return f"~{hours} giờ {rem_min} phút"


class Estimator:
    """Estimate batch durations + record actuals.

    Usage:
        est = Estimator()  # defaults to runtime/timing_history.jsonl
        info = est.estimate_batch("gen_image", n=50)
        # → {"avg_sec": 2250, "p90_sec": 3750,
        #    "formatted_avg": "~38 phút", "formatted_p90": "P90: ~62 phút"}

        est.record_actual("gen_image", duration_sec=47.2)
    """

    def __init__(self, history_path: Path | None = None) -> None:
        self.history_path = Path(history_path) if history_path else timing_history.DEFAULT_HISTORY_PATH
        self.baselines: dict[str, dict[str, float]] = {
            k: dict(v) for k, v in DEFAULT_BASELINES.items()
        }
        self._records_since_refresh = 0
        self._refresh_from_history()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_batch(self, action: str, n: int) -> dict[str, Any]:
        b = self.baselines.get(action) or DEFAULT_BASELINES.get(action)
        if not b:
            log.warning(f"Estimator: action lạ '{action}', dùng gen_image làm fallback")
            b = DEFAULT_BASELINES["gen_image"]
        avg_sec = float(n) * b["avg"]
        p90_sec = float(n) * b["p90"]
        return {
            "n": n,
            "action": action,
            "avg_sec": avg_sec,
            "p90_sec": p90_sec,
            "formatted_avg": fmt_duration(avg_sec),
            "formatted_p90": f"P90: {fmt_duration(p90_sec)}",
            "summary": (
                f"~{n} item × {fmt_duration(b['avg'])[1:]} = "
                f"{fmt_duration(avg_sec)}  (P90: {fmt_duration(p90_sec)})"
            ),
        }

    def record_actual(self, action: str, duration_sec: float) -> None:
        if duration_sec <= 0:
            return
        timing_history.append(self.history_path, action, duration_sec)
        self._records_since_refresh += 1
        if self._records_since_refresh >= REFRESH_EVERY_N:
            self._refresh_from_history()
            self._records_since_refresh = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_from_history(self) -> None:
        records = timing_history.load(self.history_path)
        if not records:
            return

        actions_seen: set[str] = {r.get("action") for r in records if r.get("action")}
        refreshed_any = False
        for action in actions_seen:
            samples = timing_history.filter_by_action(records, action)
            if len(samples) < 20:
                # Not enough data — keep defaults
                continue
            avg = sum(samples) / len(samples)
            p50 = timing_history.percentile(samples, 50)
            p90 = timing_history.percentile(samples, 90)
            p99 = timing_history.percentile(samples, 99)
            self.baselines[action] = {"avg": avg, "p50": p50, "p90": p90, "p99": p99}
            log.debug(
                f"Estimator refresh '{action}': n={len(samples)} "
                f"avg={avg:.1f}s p50={p50:.1f}s p90={p90:.1f}s p99={p99:.1f}s"
            )
            refreshed_any = True

        if refreshed_any:
            log.info(f"Estimator: đã cập nhật baselines từ {len(records)} record lịch sử")
