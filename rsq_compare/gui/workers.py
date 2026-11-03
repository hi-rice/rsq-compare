"""오래 걸릴 수 있는 작업(파일 읽기, 저장)을 별도 스레드에서 실행.

화면(메인 스레드)에서 직접 파일을 읽으면 그동안 창이 '응답 없음'이 될 수 있다.
그래서 작업을 QThread로 보내고, 끝나면 신호(Signal)로 결과를 돌려받는다.
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str, str)  # (짧은 메시지, 상세 traceback)
    progress = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    @Slot()
    def run(self):
        try:
            res = self._fn(*self._args, progress=self.progress.emit, **self._kwargs)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e) or e.__class__.__name__, traceback.format_exc())
        else:
            self.finished.emit(res)


class _Relay(QObject):
    """메인 스레드에 사는 중계자. 작업 스레드의 신호를 받아 메인 스레드에서 콜백을 실행한다.
    (화면 위젯은 반드시 메인 스레드에서만 건드려야 하기 때문)"""

    def __init__(self, on_done, on_fail, on_progress, parent=None):
        super().__init__(parent)
        self._d, self._f, self._p = on_done, on_fail, on_progress

    @Slot(object)
    def done(self, res):
        if self._d:
            self._d(res)

    @Slot(str, str)
    def fail(self, msg, detail):
        if self._f:
            self._f(msg, detail)

    @Slot(str)
    def prog(self, msg):
        if self._p:
            self._p(msg)


class JobRunner(QObject):
    """작업 1개를 스레드로 실행하고 정리까지 맡는 도우미."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: list[tuple[QThread, Worker, _Relay]] = []

    def busy(self) -> bool:
        return any(t.isRunning() for t, _w, _r in self._jobs)

    def start(self, fn, *args, on_done=None, on_fail=None, on_progress=None, **kwargs):
        th = QThread()
        wk = Worker(fn, *args, **kwargs)
        wk.moveToThread(th)
        relay = _Relay(on_done, on_fail, on_progress, parent=self)
        th.started.connect(wk.run)
        wk.finished.connect(relay.done)
        wk.failed.connect(relay.fail)
        wk.progress.connect(relay.prog)
        wk.finished.connect(th.quit)
        wk.failed.connect(th.quit)
        th.finished.connect(self._cleanup)  # JobRunner(메인 스레드)의 슬롯 → 메인 스레드에서 정리
        self._jobs.append((th, wk, relay))
        th.start()

    @Slot()
    def _cleanup(self):
        keep = []
        for t, w, r in self._jobs:
            if t.isFinished():
                w.deleteLater()
                t.deleteLater()
                r.deleteLater()
            else:
                keep.append((t, w, r))
        self._jobs = keep

    def wait_all(self, ms: int = 5000):
        for t, _w, _r in list(self._jobs):
            t.quit()
            t.wait(ms)
