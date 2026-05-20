from pathlib import Path
from types import SimpleNamespace

from core.schema import Meta, Scene
from workers.batch_image import _build_image_settings
from workers.batch_video import _build_video_settings


class ScenesJsonWithoutSettings:
    def __init__(self) -> None:
        self.meta = Meta(
            project_id="p1",
            title="Meta Title",
            aspect_ratio="9:16",
            language="en",
            baseStyle="Meta Style",
            baseNegative="Meta Negative",
            image_quality="speed",
            video_resolution="480p",
            video_duration="6s",
            topic="Meta Topic",
        )

    @property
    def settings(self):
        raise AssertionError("worker settings helpers must read meta directly")

    def topic_for_prompt(self) -> str:
        return self.meta.topic or self.meta.title


def _project(tmp_path: Path):
    return SimpleNamespace(
        scenes_json=ScenesJsonWithoutSettings(),
        paths=SimpleNamespace(temp_dir=tmp_path / "tmp"),
    )


def test_build_image_settings_reads_generation_defaults_from_meta(tmp_path):
    project = _project(tmp_path)
    scene = Scene(
        id="1",
        visual_type="Image",
        story_en="Story",
        imagePrompt=None,
        duration=8,
    )
    output_path = tmp_path / "sources" / "pic1.jpg"

    settings = _build_image_settings(project, scene, output_path)

    assert settings["prompt"] == "\n\nStyle: Meta Style\n\nNegative: Meta Negative"
    assert settings["aspect"] == "9:16"
    assert settings["quality"] == "speed"
    assert settings["output_path"] == output_path
    assert settings["topic"] == "Meta Topic"
    assert settings["style"] == "Meta Style"
    assert settings["debug_dir"] == tmp_path / "tmp" / "candidates"


def test_build_video_settings_reads_generation_defaults_from_meta(tmp_path):
    project = _project(tmp_path)
    output_path = tmp_path / "sources" / "vid1.mp4"

    settings = _build_video_settings(project, output_path)

    assert settings == {
        "aspect": "9:16",
        "resolution": "480p",
        "duration": "6s",
        "output_path": output_path,
    }
