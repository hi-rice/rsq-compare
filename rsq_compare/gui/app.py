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

def _excepthook(exc_type, exc, tb):
    from rsq_compare.runtime import log_error
    try:
        path=log_error(exc_type,tb)
        message=f'작업을 완료하지 못했습니다. 입력과 파일 권한을 확인하세요.\n오류 종류: {exc_type.__name__}\n로그: {path}'
    except OSError:
        message=f'작업을 완료하지 못했습니다. 오류 종류: {exc_type.__name__} (로그 저장 불가)'
    if QApplication.instance():
        QMessageBox.critical(None,'작업 오류',message)
    else:
        sys.__excepthook__(exc_type,exc,tb)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    sys.excepthook = _excepthook
    app = QApplication(argv)
    from rsq_compare import APP_NAME,APP_VERSION
    from rsq_compare.runtime import icon_path
    from PySide6.QtGui import QIcon
    app.setOrganizationName('NDMI');app.setApplicationName(APP_NAME);app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(icon_path())))
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('hi-rice.RSQCompare.Desktop')
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
