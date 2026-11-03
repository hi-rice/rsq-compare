"""화면 자동 점검(오프스크린): 폴더 열기 → 탭 캡처 → 체크 변경 → 저장."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rsq_compare.core.plots import setup_korean_font  # noqa: E402
from rsq_compare.gui.main_window import MainWindow  # noqa: E402
from rsq_compare.gui.workers import JobRunner  # noqa: E402

data, shots, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
app = QApplication([])
setup_korean_font()
runner = JobRunner()
w = MainWindow(runner)
w.resize(1500, 900)
w.show()
w.grab().save(str(shots / "00_empty.png"))


def pump(cond, timeout=30):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.time() - t0 > timeout:
            raise TimeoutError
    for _ in range(20):
        app.processEvents()


w.open_folder(data)
pump(lambda: w.sd is not None and not runner.busy())
print("records:", [r.label for r in w.sd.records])
print("list:", [w.lst.item(i).text() for i in range(w.lst.count())])
for i, name in enumerate(["summary", "compare", "detail", "checks"]):
    w.tabs.setCurrentIndex(i)
    pump(lambda: True)
    w.grab().save(str(shots / f"{i+1:02d}_{name}.png"))
# 체크 변경: T01, T04 해제
for i in range(w.lst.count()):
    if w.lst.item(i).text().startswith(("T01", "T04")):
        w.lst.item(i).setCheckState(Qt.Unchecked)
print("selected after uncheck:", w.selected_nums())
print(w.m_stat_sum._df.to_string())
print(w.m_stat_det._df.to_string())
w.tabs.setCurrentIndex(1)
pump(lambda: True)
w.grab().save(str(shots / "05_compare_after_uncheck.png"))
# 상세: T07 선택
w.lst.setCurrentRow(6)
w.tabs.setCurrentIndex(2)
pump(lambda: True)
print("detail label:", w.lbl_detail.text())
w.detail_tabs.setCurrentIndex(1)
pump(lambda: True)
w.grab().save(str(shots / "06_detail_T07_plot.png"))
w.detail_tabs.setCurrentIndex(2)
pump(lambda: True)
w.grab().save(str(shots / "07_detail_T07_vel.png"))
# 저장 (대화상자 대신 직접 호출)
from rsq_compare.core.export import export_all  # noqa: E402
res = {}
runner.start(export_all, w.sd, w.selected_nums(), out, on_done=lambda r: res.update(r),
             on_fail=lambda m, d: print("FAIL", m, d), on_progress=lambda m: None)
pump(lambda: bool(res) and not runner.busy(), timeout=120)
print("saved:", res["folder"], len(res["files"]))
