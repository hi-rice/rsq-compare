"""'② 누적·비교' 탭 화면 자동 점검(오프스크린).

사용법: python tests/gui_smoke_db.py <측정 폴더(원본+T07포함 .dis)> <임시 DB 경로> <캡처 폴더>
기준유량·외부 시계열은 templates 의 '예시(가상) 값'을 쓴다.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from rsq_compare.core import db  # noqa: E402
from rsq_compare.core.batch import import_folder  # noqa: E402
from rsq_compare.core.external import read_timeseries  # noqa: E402
from rsq_compare.core.plots import setup_korean_font  # noqa: E402
from rsq_compare.gui.main_window import MainWindow  # noqa: E402
from rsq_compare.gui.workers import JobRunner  # noqa: E402

data, dbp, shots = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
shots.mkdir(parents=True, exist_ok=True)
if dbp.exists():
    dbp.unlink()
QMessageBox.information = staticmethod(lambda *a, **k: None)  # 테스트 중 알림창 막기

app = QApplication([])
setup_korean_font()
runner = JobRunner()
w = MainWindow(runner)
w.resize(1600, 940)
w.show()


def pump(cond=lambda: True, timeout=60):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.time() - t0 > timeout:
            raise TimeoutError
    for _ in range(30):
        app.processEvents()


def shot(name):
    pump()
    w.grab().save(str(shots / name))


w.dbtab.db_path = dbp
w.dbtab.reload()
w.main_tabs.setCurrentIndex(1)
shot("db_0_빈DB.png")

# 1) 폴더 일괄 가져오기 (GUI와 같은 경로: 작업 스레드 → _on_imported)
runner.start(import_folder, data, dbp, on_done=w.dbtab._on_imported, on_progress=lambda m: None)
pump(lambda: not runner.busy() and w.dbtab.tbl.rowCount() == 1)
print("가져오기 보고:", w.dbtab.m_rep._df[["세션", "사용한 .dis", "결과"]].values.tolist())
shot("db_1_가져오기보고.png")

# 2) 세션 보기 탭에서 T07 포함 .dis 선택 → '누적 DB에 등록'
w.main_tabs.setCurrentIndex(0)
w.open_folder(data)
pump(lambda: w.sd is not None and not runner.busy())
old = w.sd
w.cmb_dis.setCurrentIndex(1)
pump(lambda: w.sd is not old and not runner.busy())
w.btn_reg.click()
pump()
print("등록 수:", w.dbtab.tbl.rowCount())

# 3) 기준유량(예시 양식) + 외부 시계열(예시 양식)
db.import_reference_file(dbp, ROOT / "templates" / "비교유량_양식.csv")
vals, dropped, _ = read_timeseries(ROOT / "templates" / "외부시계열_양식.csv")
db.add_series(dbp, "수위(예시·가상)", "m", "UTC+9 (한국시간)", [t.strftime("%Y-%m-%d %H:%M:%S") for t in vals["t"]],
              list(vals["value"]), ROOT / "templates" / "외부시계열_양식.csv", dropped, kind="수위")
w.dbtab.reload()
w.main_tabs.setCurrentIndex(1)
w.dbtab.tabs.setCurrentIndex(0)
shot("db_2_세션비교.png")
w.dbtab.tabs.setCurrentIndex(2)
shot("db_3_비교유량.png")
w.dbtab.tabs.setCurrentIndex(3)
shot("db_4_외부시계열.png")
print("외부 연결:", w.dbtab.m_ext._df[["등록ID", "회차", "연결", "시간창 안 자료 수"]].head(3).values.tolist())

# 4) 표에서 기준유량 직접 수정 → 반영 확인
w.dbtab.tbl.item(0, 10).setText("3.2")
pump()
print("직접 입력 후 기준유량:", db.sessions_df(dbp)[["id", "ref_q", "ref_source"]].values.tolist())
# 5) 체크 해제 → 비교 대상 변경
w.dbtab.tbl.item(1, 0).setCheckState(w.dbtab.tbl.item(1, 0).checkState().__class__.Unchecked)
pump()
print("체크 후 비교 대상:", w.dbtab.checked_ids(), "| 요약 행 수:", len(w.dbtab.m_summ._df))
print("OK")
