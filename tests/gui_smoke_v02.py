"""v0.2 화면 자동 점검(오프스크린): .dis 후보 전환, 구간 필터, 통계 표시를 확인하고 캡처한다.

사용법: python tests/gui_smoke_v02.py <원본 .dis와 T07 포함 .dis가 함께 있는 폴더> <캡처 폴더>
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication  # noqa: E402

from rsq_compare.core.plots import setup_korean_font  # noqa: E402
from rsq_compare.gui.main_window import MainWindow  # noqa: E402
from rsq_compare.gui.workers import JobRunner  # noqa: E402

data, shots = Path(sys.argv[1]), Path(sys.argv[2])
shots.mkdir(parents=True, exist_ok=True)
app = QApplication([])
setup_korean_font()
runner = JobRunner()
w = MainWindow(runner)
w.resize(1500, 920)
w.show()


def pump(cond, timeout=60):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.time() - t0 > timeout:
            raise TimeoutError
    for _ in range(30):
        app.processEvents()


def shot(name):
    pump(lambda: True)
    w.grab().save(str(shots / name))


w.open_folder(data)
pump(lambda: w.sd is not None and not runner.busy())
print("DIS 후보:", [w.cmb_dis.itemText(i) for i in range(w.cmb_dis.count())])
print("사용 중:", w.sd.dis_path.name, "|", w.lbl_dis.text())
print("목록:", [w.lst.item(i).text() for i in range(w.lst.count())])
w.tabs.setCurrentIndex(1)
shot("1_원본dis_비교그래프.png")

# T07 포함 .dis 로 전환
old = w.sd
w.cmb_dis.setCurrentIndex(1)
pump(lambda: w.sd is not old and not runner.busy())
print("전환 후 사용 중:", w.sd.dis_path.name, "|", w.lbl_dis.text())
print("목록:", [w.lst.item(i).text() for i in range(w.lst.count())])
print(w.m_stat_sum._df.to_string())
w.tabs.setCurrentIndex(1)
shot("2_T07포함dis_비교그래프.png")
w.tabs.setCurrentIndex(0)
shot("3_T07포함dis_요약표.png")

# 상세: T01 구간 필터
w.lst.setCurrentRow(0)
w.tabs.setCurrentIndex(2)
pump(lambda: True)
print("구간 선택지:", [w.cmb_section.itemText(i) for i in range(w.cmb_section.count())])
w.detail_tabs.setCurrentIndex(1)
shot("4_T01_전체_구간음영.png")
w.cmb_section.setCurrentIndex(2)  # 횡단 섹션
pump(lambda: True)
print("횡단 섹션 필터 행 수:", len(w.m_detail._df), "| 구간 값:", set(w.m_detail._df.iloc[:, 1]))
shot("5_T01_횡단섹션만.png")
w.detail_tabs.setCurrentIndex(0)
shot("6_T01_횡단섹션_표.png")
w.detail_tabs.setCurrentIndex(2)
shot("7_T01_vel_구간경계.png")
w.tabs.setCurrentIndex(3)
shot("8_점검내역.png")
print("OK")
