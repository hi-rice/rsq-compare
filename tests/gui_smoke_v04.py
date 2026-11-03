"""v0.4 화면 점검(오프스크린): verify_v04.py가 만든 DB를 열어 지점·수위·외부 자료 화면을 캡처한다.
사용법: python tests/gui_smoke_v04.py <verify_v04 작업 폴더> <캡처 폴더>"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from rsq_compare.core import db  # noqa: E402
from rsq_compare.core.external import read_raw_table  # noqa: E402
from rsq_compare.core.plots import setup_korean_font  # noqa: E402
from rsq_compare.gui.db_tab import SeriesDialog  # noqa: E402
from rsq_compare.gui.main_window import MainWindow  # noqa: E402
from rsq_compare.gui.workers import JobRunner  # noqa: E402

work, shots = Path(sys.argv[1]), Path(sys.argv[2])
shots.mkdir(parents=True, exist_ok=True)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: print("경고창:", a[2] if len(a) > 2 else a))
app = QApplication([])
setup_korean_font()
w = MainWindow(JobRunner())
w.resize(1680, 960)
w.show()


def pump():
    for _ in range(40):
        app.processEvents()
        time.sleep(0.01)


def shot(name):
    pump()
    w.grab().save(str(shots / name))


dbp = work / "v04.db"
w.dbtab.db_path = dbp
w.dbtab.reload()
w.main_tabs.setCurrentIndex(1)
t = w.dbtab
rows = {t.tbl.item(i, 2).text(): i for i in range(t.tbl.rowCount())}
print("세션 행:", rows)
iA = rows["fieldA_20261029_105656"]
t.tbl.setCurrentCell(iA, 2)
t.tabs.setCurrentIndex(1)
shot("v04_1_지점수위_A.png")
print("A 지점 표시:", t.lbl_site.text()[:160].replace("<br>", " / "))
# 수위 표에서 T04 직접 입력
r4 = next(i for i in range(t.tbl_gh.rowCount()) if t.tbl_gh.item(i, 0).text() == "T04")
t.tbl_gh.item(r4, 3).setText("0.58")
pump()
gv = db.gauge_view(db.transects_df(dbp, [int(t.tbl.item(iA, 1).text())])).set_index("회차")
print("화면에서 T04 직접 입력 후:", gv.loc["T04", ["사용 수위", "출처"]].tolist())
# B: 코드 지우고 GPS 제안 확인
iB = rows["fieldB_20261029_105656"]
t.tbl.item(iB, 5).setText("")
pump()
rows = {t.tbl.item(i, 2).text(): i for i in range(t.tbl.rowCount())}
t.tbl.setCurrentCell(rows["fieldB_20261029_105656"], 2)
t.tabs.setCurrentIndex(1)
shot("v04_2_지점수위_B_GPS제안.png")
print("GPS 제안 버튼 활성:", t.b_use_gps.isEnabled())
t.b_use_gps.click()
pump()
print("적용 후 B 코드:", db.sessions_df(dbp).set_index("session_name").loc["fieldB_20261029_105656", ["site_code", "site_code_source"]].tolist())
# 잘못된 코드 입력 → 경고, 저장 안 됨
rows = {t.tbl.item(i, 2).text(): i for i in range(t.tbl.rowCount())}
t.tbl.item(rows["fieldA_20261029_105656"], 5).setText("12345")
pump()
print("잘못된 코드 후 A 코드:", db.sessions_df(dbp).set_index("session_name").loc["fieldA_20261029_105656", "site_code"])
# 외부 자료: 유량 시계열 선택
t.tabs.setCurrentIndex(3)
idx = next(i for i in range(t.cmb_series.count()) if "유량" in t.cmb_series.itemText(i))
t.cmb_series.setCurrentIndex(idx)
t.spin_margin.setValue(1.0)
shot("v04_3_외부자료_FEWP유량.png")
print("외부 연결 열:", [c for c in t.m_ext._df.columns][:12])
t.tabs.setCurrentIndex(0)
shot("v04_4_세션비교.png")
# 열 고르기 창
raw = read_raw_table(work / "FEWP_가상.csv")
dlg = SeriesDialog(t, work / "FEWP_가상.csv", raw, db.catalog_df(dbp))
dlg.resize(820, 600)
for i in range(dlg.tbl.rowCount()):
    if dlg.tbl.item(i, 1).text() in ("WAL", "TOT_DISCHA"):
        dlg.tbl.item(i, 0).setCheckState(Qt.Checked)
print("자동 인식:", dlg.code_note, "| 선택된 코드:", dlg.site_code())
dlg.show()
pump()
dlg.grab().save(str(shots / "v04_5_외부자료_열고르기창.png"))
print("창에서 고른 것:", dlg.chosen(), "| 시각 열:", dlg.tcol.currentText(), "| 코드:", dlg.site_code())
print("OK")
