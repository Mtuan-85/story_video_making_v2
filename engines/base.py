"""Engine adapter Protocols (SPEC §6).

Goal: when Grok's DOM changes or we swap to a different image/video provider,
only files under engines/<provider>/ change. Orchestrator, UI, voice, and render
modules talk to these Protocols — never to a concrete engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EngineConnection(Protocol):
    """Lifecycle for a CDP-attached browser session (or any persistent backend)."""

    async def connect(self, cdp_url: str) -> None:
        """Attach to an existing browser via CDP. Raises on failure."""
        ...

    async def disconnect(self) -> None:
        """Release resources. Idempotent."""
        ...

    async def is_connected(self) -> bool:
        ...


@runtime_checkable
class ImageEngine(Protocol):
    """Generate and curate still images for one scene."""

    async def gen_image(
        self,
        prompt: str,
        settings: dict[str, Any],
        ref_image: Path | None = None,
    ) -> Path:
        """Generate one image and return the local path of the chosen variant.

        `settings` carries resolution / quality / aspect — engine-specific keys.
        `ref_image`, when provided, is used as a style/composition reference
        (image-to-image flow).
        """
        ...

    async def pick_best(
        self,
        candidates: list[Path],
        prompt: str,
        topic: str,
        style: str,
    ) -> int:
        """Choose the best candidate index given prompt + project topic + style.

        Implementations may delegate to a vision model (e.g. Claude Code CLI).
        """
        ...


@runtime_checkable
class VideoEngine(Protocol):
    """Generate one video clip for a scene (image-to-video)."""

    async def gen_video(
        self,
        prompt: str,
        ref_image: Path,
        settings: dict[str, Any],
    ) -> Path:
        """Image-to-Video. Returns local mp4 path."""
        ...
