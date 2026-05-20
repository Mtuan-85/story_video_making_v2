from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from workers.task_contract import GenerateTask, WorkerEvent, parse_worker_line


def collect_events_from_text(text: str) -> list[WorkerEvent]:
    events: list[WorkerEvent] = []
    for line in text.splitlines():
        event = parse_worker_line(line)
        if event is not None:
            events.append(event)
    return events


class GenerateProcess(QObject):
    event = pyqtSignal(object)
    log_line = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, task: GenerateTask, task_path: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.task = task
        self.task_path = Path(task_path)
        self._line_buffer = ""

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read_available_output)
        self.proc.finished.connect(self._on_finished)

    def start(self, dry_run: bool = False) -> None:
        self.task.save(self.task_path)
        args = ["-m", "workers.generate_worker", "--task", str(self.task_path)]
        if dry_run:
            args.append("--dry-run")
        self.proc.start(sys.executable, args)

    def kill(self) -> None:
        if self.is_running():
            self.proc.kill()

    def is_running(self) -> bool:
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def _read_available_output(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        if not data:
            return

        self._line_buffer += data
        lines = self._line_buffer.splitlines(keepends=True)

        if lines and not lines[-1].endswith(("\n", "\r")):
            self._line_buffer = lines.pop()
        else:
            self._line_buffer = ""

        for line in lines:
            self._emit_line(line.rstrip("\r\n"))

    def _emit_line(self, line: str) -> None:
        self.log_line.emit(line)
        event = parse_worker_line(line)
        if event is not None:
            self.event.emit(event)

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_available_output()
        if self._line_buffer:
            self._emit_line(self._line_buffer)
            self._line_buffer = ""
        self.finished.emit(exit_code)
