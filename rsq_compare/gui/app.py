"""프로그램 시작점. 예상치 못한 오류도 한국어 안내창으로 보여주고 로그 파일에 남긴다."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from rsq_compare.core.plots import setup_korean_font
from rsq_compare.gui.main_window import MainWindow
from rsq_compare.gui.workers import JobRunner

LOG_FILE = Path.home() / "rsq_compare_오류기록.log"


def _excepthook(exc_type, exc, tb):
    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{detail}")
    except OSError:
        pass
    if QApplication.instance():
        box = QMessageBox(QMessageBox.Critical, "예상치 못한 오류",
                          f"처리 중 오류가 발생했습니다. 프로그램은 계속 사용할 수 있습니다.\n\n{exc}\n\n"
                          f"상세 내용은 '자세히' 버튼 또는 다음 파일에 기록됩니다:\n{LOG_FILE}")
        box.setDetailedText(detail)
        box.exec()
    else:
        sys.__excepthook__(exc_type, exc, tb)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    sys.excepthook = _excepthook
    app = QApplication(argv)
    app.setApplicationName("RSQ 회차 비교 도구")
    setup_korean_font()
    runner = JobRunner()
    win = MainWindow(runner)
    win.show()
    # 시작 시 폴더를 인수로 받을 수 있음: python run_app.py "D:\data\test"
    if len(argv) > 1 and Path(argv[1]).is_dir():
        win.open_folder(Path(argv[1]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
