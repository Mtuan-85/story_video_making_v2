from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _method_body(source: str, method_name: str) -> str:
    marker = f"    def {method_name}("
    start = source.index(marker)
    next_method = source.find("\n    def ", start + len(marker))
    if next_method == -1:
        return source[start:]
    return source[start:next_method]


def test_unified_preview_connects_error_signal_before_loading_source() -> None:
    source = (ROOT / "ui" / "dialogs" / "preview_dialog.py").read_text(encoding="utf-8")
    body = _method_body(source, "_load_video")

    assert body.index("errorOccurred.connect(self._on_media_error)") < body.index("setSource(")


def test_focused_video_preview_does_not_depend_on_qt_multimedia_backend() -> None:
    source = (ROOT / "ui" / "dialogs" / "video_preview_dialog.py").read_text(encoding="utf-8")

    assert "QMediaPlayer" not in source
    assert "QVideoWidget" not in source
    assert "QAudioOutput" not in source
    assert "cv2.VideoCapture" in source


def test_focused_video_preview_limits_gui_frame_size() -> None:
    source = (ROOT / "ui" / "dialogs" / "video_preview_dialog.py").read_text(encoding="utf-8")

    assert "PREVIEW_MAX_HEIGHT = 420" in source
    assert "cv2.resize" in source


def test_focused_video_playback_uses_clock_and_avoids_per_tick_seek() -> None:
    source = (ROOT / "ui" / "dialogs" / "video_preview_dialog.py").read_text(encoding="utf-8")
    advance_body = _method_body(source, "_advance_frame")

    assert "QElapsedTimer" in source
    assert "_play_clock.elapsed()" in advance_body
    assert "CAP_PROP_POS_FRAMES" not in advance_body
