"""Easing functions for animations."""
import math


def clamp01(t: float) -> float:
    return max(0.0, min(1.0, t))


def linear(t: float) -> float:
    return clamp01(t)


def ease_out_cubic(t: float) -> float:
    """Fast start, slow end. Natural for entry."""
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    """Slow start, fast middle, slow end."""
    t = clamp01(t)
    if t < 0.5:
        return 4 * t ** 3
    return 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float) -> float:
    """Overshoot at end."""
    t = clamp01(t)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_out_bounce(t: float) -> float:
    """Multi-bounce at end."""
    t = clamp01(t)
    n1 = 7.5625
    d1 = 2.75
    if t < 1 / d1:
        return n1 * t * t
    elif t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def triangle_wave(t: float) -> float:
    """0 -> 1 -> 0 in [0,1]. Used for pulse/glow."""
    t = clamp01(t)
    if t < 0.5:
        return ease_in_out_cubic(t * 2)
    return ease_in_out_cubic((1 - t) * 2)
