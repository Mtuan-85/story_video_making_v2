"""Animation library: 7 animations (4 entry + 3 emphasis).

Each animation:
  - Class with name, default_duration, default_sound class attrs
  - __init__(params: dict)
  - transform(sticker, t_local, duration) -> StickerTransform

Composition rule (renderer):
  entry → idle → optional emphasis (emphasis composes on top of idle)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

from PIL import Image, ImageFilter

from easing import (
    ease_in_out_cubic,
    ease_out_back,
    ease_out_bounce,
    ease_out_cubic,
    triangle_wave,
)


@dataclass
class Layer:
    """Extra render layer (eg glow halo)."""
    image: Image.Image  # RGBA
    offset: Tuple[float, float]  # offset in original-image coords from sticker.position
    blend_mode: str  # "normal" | "screen"
    opacity: float


@dataclass
class StickerTransform:
    offset: Tuple[float, float] = (0.0, 0.0)
    scale: float = 1.0
    rotation_deg: float = 0.0
    opacity: float = 1.0
    extra_layers: List[Layer] = field(default_factory=list)


def compose_transforms(base: StickerTransform, top: StickerTransform) -> StickerTransform:
    """Combine emphasis on top of base idle. Emphasis adds offset/scale,
    multiplies opacity, appends layers."""
    return StickerTransform(
        offset=(base.offset[0] + top.offset[0], base.offset[1] + top.offset[1]),
        scale=base.scale * top.scale,
        rotation_deg=base.rotation_deg + top.rotation_deg,
        opacity=base.opacity * top.opacity,
        extra_layers=base.extra_layers + top.extra_layers,
    )


# ============================================================
# Entry animations
# ============================================================

class FadeIn:
    name = "fade_in"
    default_duration = 0.5
    default_sound = "ding"
    category = "entry"

    def __init__(self, params: dict):
        self.params = params or {}

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        p = max(0.0, min(1.0, t_local / duration if duration > 0 else 1.0))
        return StickerTransform(opacity=ease_out_cubic(p))


class ScalePop:
    name = "scale_pop"
    default_duration = 0.6
    default_sound = "pop"
    category = "entry"

    def __init__(self, params: dict):
        params = params or {}
        self.start_scale = float(params.get("start_scale", 0.5))
        self.overshoot = float(params.get("overshoot", 1.1))

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        p = max(0.0, min(1.0, t_local / duration if duration > 0 else 1.0))
        eased = ease_out_back(p)
        scale = self.start_scale + (1.0 - self.start_scale) * eased
        opacity = min(1.0, p * 2)
        return StickerTransform(scale=scale, opacity=opacity)


class SlideIn:
    """Generic slide-in. direction in params: left|right|top|bottom."""
    default_duration = 0.6
    default_sound = "swoosh"
    category = "entry"

    def __init__(self, params: dict):
        params = params or {}
        self.direction = params.get("direction", "left")
        self.distance = params.get("distance")  # None -> auto from sticker size

    @property
    def name(self):
        return f"slide_in_{self.direction}"

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        p = max(0.0, min(1.0, t_local / duration if duration > 0 else 1.0))
        eased = ease_out_cubic(p)

        if self.distance is None:
            if self.direction in ("left", "right"):
                distance = sticker.size[0] + 50
            else:
                distance = sticker.size[1] + 50
        else:
            distance = float(self.distance)

        remain = 1.0 - eased
        if self.direction == "left":
            offset = (-distance * remain, 0.0)
        elif self.direction == "right":
            offset = (distance * remain, 0.0)
        elif self.direction == "top":
            offset = (0.0, -distance * remain)
        elif self.direction == "bottom":
            offset = (0.0, distance * remain)
        else:
            offset = (0.0, 0.0)

        return StickerTransform(offset=offset, opacity=min(1.0, p * 3))


class DropIn:
    name = "drop_in"
    default_duration = 0.8
    default_sound = "pop"
    category = "entry"

    def __init__(self, params: dict):
        params = params or {}
        self.start_offset_y = float(params.get("start_offset_y", -150))
        self.bounce = bool(params.get("bounce", True))

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        p = max(0.0, min(1.0, t_local / duration if duration > 0 else 1.0))
        eased = ease_out_bounce(p) if self.bounce else ease_out_cubic(p)
        offset_y = self.start_offset_y * (1.0 - eased)
        opacity = min(1.0, p * 4)
        return StickerTransform(offset=(0.0, offset_y), opacity=opacity)


# ============================================================
# Emphasis animations
# ============================================================

class Pulse:
    name = "pulse"
    default_duration = 0.4
    default_sound = "ding"
    category = "emphasis"

    def __init__(self, params: dict):
        params = params or {}
        self.scale_peak = float(params.get("scale_peak", 1.08))
        self.cycles = int(params.get("cycles", 1))

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        if duration <= 0 or self.cycles < 1:
            return StickerTransform()
        cycle_dur = duration / self.cycles
        cycle_p = (t_local % cycle_dur) / cycle_dur
        intensity = triangle_wave(cycle_p)
        scale = 1.0 + (self.scale_peak - 1.0) * intensity
        return StickerTransform(scale=scale)


class Glow:
    name = "glow"
    default_duration = 0.6
    default_sound = "ding"
    category = "emphasis"

    def __init__(self, params: dict):
        params = params or {}
        self.color = tuple(params.get("color", (255, 180, 50)))
        self.blur_radius = int(params.get("blur_radius", 25))
        self.intensity_peak = float(params.get("intensity_peak", 0.85))
        self.blend_mode = params.get("blend_mode", "auto")
        # Cache the blurred glow layer per sticker (id-based key).
        # Glow image only depends on sticker.image + color + radius; opacity
        # changes per frame. GaussianBlur(25) costs ~50ms — rebuild only once.
        self._cached_glow: dict = {}

    def _get_glow_layer(self, sticker):
        key = id(sticker)
        cached = self._cached_glow.get(key)
        if cached is None:
            cached = build_glow_layer(sticker.image, self.color, self.blur_radius)
            self._cached_glow[key] = cached
        return cached

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        if duration <= 0:
            return StickerTransform()
        p = max(0.0, min(1.0, t_local / duration))
        intensity = triangle_wave(p) * self.intensity_peak

        if intensity <= 0.01:
            return StickerTransform()

        glow_img = self._get_glow_layer(sticker)
        resolved_blend = "normal" if self.blend_mode == "auto" else self.blend_mode
        layer = Layer(
            image=glow_img,
            offset=(-self.blur_radius, -self.blur_radius),
            blend_mode=resolved_blend,
            opacity=intensity,
        )
        return StickerTransform(extra_layers=[layer])


class Shake:
    name = "shake"
    default_duration = 0.4
    default_sound = "flip"
    category = "emphasis"

    def __init__(self, params: dict):
        params = params or {}
        self.amplitude = float(params.get("amplitude", 6))
        self.frequency = float(params.get("frequency", 12))

    def transform(self, sticker, t_local: float, duration: float) -> StickerTransform:
        if duration <= 0:
            return StickerTransform()
        p = max(0.0, min(1.0, t_local / duration))
        decay = (1.0 - p)
        angle = t_local * self.frequency * 2 * math.pi
        offset_x = self.amplitude * decay * math.sin(angle)
        offset_y = self.amplitude * decay * math.sin(angle * 1.3)
        return StickerTransform(offset=(offset_x, offset_y))


# ============================================================
# Glow helper
# ============================================================

def build_glow_layer(sticker_rgba: Image.Image, color, radius: int) -> Image.Image:
    """Build a blurred tinted halo from sticker alpha."""
    if sticker_rgba.mode != "RGBA":
        sticker_rgba = sticker_rgba.convert("RGBA")
    w, h = sticker_rgba.size
    alpha = sticker_rgba.split()[3]

    cw, ch = w + radius * 2, h + radius * 2
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    color_solid = Image.new("RGBA", (w, h), (*color, 255))
    color_solid.putalpha(alpha)

    canvas.paste(color_solid, (radius, radius), color_solid)
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius))
    return canvas


# ============================================================
# Registry
# ============================================================

ENTRY_REGISTRY = {
    "fade_in": FadeIn,
    "scale_pop": ScalePop,
    "drop_in": DropIn,
}

EMPHASIS_REGISTRY = {
    "pulse": Pulse,
    "glow": Glow,
    "shake": Shake,
}

SLIDE_DIRECTIONS = {"slide_in_left", "slide_in_right", "slide_in_top", "slide_in_bottom"}


def build_animation(anim_type: str, params: dict):
    """Factory: instantiate animation class by string type."""
    params = dict(params or {})

    if anim_type in SLIDE_DIRECTIONS:
        direction = anim_type.replace("slide_in_", "")
        params.setdefault("direction", direction)
        return SlideIn(params)

    if anim_type in ENTRY_REGISTRY:
        return ENTRY_REGISTRY[anim_type](params)

    if anim_type in EMPHASIS_REGISTRY:
        return EMPHASIS_REGISTRY[anim_type](params)

    raise ValueError(f"Unknown animation type: {anim_type}")


DEFAULTS = {
    "fade_in": {"duration": 0.5, "sound": "ding"},
    "scale_pop": {"duration": 0.6, "sound": "pop"},
    "slide_in_left": {"duration": 0.6, "sound": "swoosh"},
    "slide_in_right": {"duration": 0.6, "sound": "swoosh"},
    "slide_in_top": {"duration": 0.6, "sound": "swoosh"},
    "slide_in_bottom": {"duration": 0.6, "sound": "swoosh"},
    "drop_in": {"duration": 0.8, "sound": "pop"},
    "pulse": {"duration": 0.4, "sound": "ding"},
    "glow": {"duration": 0.6, "sound": "ding"},
    "shake": {"duration": 0.4, "sound": "flip"},
}

ALL_ANIMATIONS = list(DEFAULTS.keys())
