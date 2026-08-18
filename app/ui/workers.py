from __future__ import annotations

import traceback
from threading import Event
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot


class TaskWorker(QObject):
    progress = Signal(object)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, function: Callable[[Callable[[], bool], Callable[..., None]], Any]):
        super().__init__()
        self.function = function
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            value = self.function(self.cancel_event.is_set, lambda *args: self.progress.emit(args))
            self.result.emit(value)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

