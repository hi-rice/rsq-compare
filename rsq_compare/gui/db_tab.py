"""'② 누적·비교' 탭: 현장 측정 세션을 쌓아 두고 비교한다.

할 수 있는 일
1) 폴더에서 새 측정 가져오기 (일괄 등록, 같은 .dis는 건너뜀)
2) 소하천 목록(220개소 등) 불러오기 → 소하천코드만 넣으면 소하천명·가까운 AWS 자동 표시
   (RSQ Station Number에 소하천코드를 적어 두면 자동 연결, GPS가 있으면 가까운 소하천 제안)
3) 수위: RSQ에 입력된 값이 있으면 그 값, 없으면 직접 입력
4) 비교 유량(예: 같은 시간 스마트 계측 유량) 입력 → 차이만 표시(판정 없음)
5) 외부 시계열(FEWP 수위·유량, AWS 강우 등): 열을 골라 불러오고 같은 소하천 세션에만 연결
6) 비교 결과를 엑셀·그래프로 저장
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rsq_compare.core import db
from rsq_compare.core.identity import validate_comparison
from rsq_compare.core.catalog import catalog_review, resolve_catalog
from rsq_compare.core.batch import import_folder
from rsq_compare.core.db_export import _tr_view, export_db
from rsq_compare.core.external import (
    KIND_CHOICES,
    RAIN_TYPES,
    TIME_BASIS_CHOICES,
    extract_series,
    guess_time_column,
    match_to_transects,
    read_raw_table,
)
from rsq_compare.core.multi import NOTE_MULTI, fig_external, fig_reference, fig_sessions, reference_by_transect, session_summary
from rsq_compare.core.parsers import to_number
from rsq_compare.core.sites import CODE_RE, nearest_sites, read_catalog_file, site_text, KOR_LABEL
from rsq_compare.gui.df_model import DataFrameModel

EDIT_BG = QColor("#fffbe6")
COLS = ["비교", "등록ID", "세션", "사용한 .dis", "측정일", "소하천코드 (입력)", "소하천명[목록]", "측정자 (입력)",
        "DIS 회차 수", "회차 평균 Q", "비교 유량 (입력)", "메모·날씨 (입력)"]
C_CHECK, C_ID, C_CODE, C_RIVER, C_OP, C_REF, C_MEMO = 0, 1, 5, 6, 7, 10, 11
EDITABLE = {C_CODE, C_OP, C_REF, C_MEMO}


def _nn(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


class SeriesDialog(QDialog):
    """외부 파일의 열을 골라 시계열로 불러오는 창. 형식을 미리 알 수 없으므로 사용자가 고른다."""

    def __init__(self, parent, path: Path, raw: pd.DataFrame, catalog: pd.DataFrame, sessions: pd.DataFrame | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"외부 자료 불러오기 — {path.name}")
        self.resize(760, 560)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.tcol = QComboBox()
        self.tcol.addItems(list(raw.columns))
        self.tcol.setCurrentText(guess_time_column(raw))
        self.basis = QComboBox()
        self.basis.addItems(TIME_BASIS_CHOICES)
        self.site = QComboBox()
        self.site.setEditable(True)
        self.site.addItem("(지점을 고르거나 측정 지정)", None)
        for _, r in catalog.iterrows():
            self.site.addItem(f"{r['site_code']} {r['river_name']} ({r['sigungu'] or ''})", r["site_code"])
        self.target = QComboBox()
        self.target.addItem("(측정 지정 안 함)", None)
        if sessions is not None:
            for _, r in sessions.iterrows():
                self.target.addItem(f"#{int(r['id'])} {r['session_name']}", int(r['id']))
        self.prefix = QLineEdit(path.stem)
        # 파일 안에 소하천코드(숫자 11자리)만 들어 있는 열이 있으면 자동 인식
        self.code_note = ""
        for c in raw.columns:
            vals = {str(x).strip() for x in raw[c] if str(x).strip()}
            if vals and all(CODE_RE.match(x) for x in vals):
                if len(vals) == 1:
                    code = next(iter(vals))
                    i = self.site.findData(code)
                    if i >= 0:
                        self.site.setCurrentIndex(i)
                    else:
                        self.site.setEditText(code)
                    self.code_note = f"소하천코드 자동 인식: '{c}' 열"
                else:
                    self.code_note = f"⚠ '{c}' 열에 소하천코드 {len(vals)}개가 섞여 있음"
                break
        f.addRow("시각 열", self.tcol)
        f.addRow("시간대 없는 값의 기준", self.basis)
        f.addRow("소하천코드", self.site)
        f.addRow("측정 직접 지정", self.target)
        f.addRow("이름", self.prefix)
        v.addLayout(f)
        if self.code_note:
            cn = QLabel(self.code_note)
            cn.setStyleSheet("color:#1d4ed8;" if not self.code_note.startswith("⚠") else "color:#b91c1c; font-weight:bold;")
            v.addWidget(cn)
        v.addWidget(QLabel("<b>값 열</b>"))
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["사용", "열 이름", "자료 종류", "단위", "강우 종류", "기록 간격(분)"])
        for c in raw.columns:
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            self.tbl.setItem(i, 0, chk)
            it = QTableWidgetItem(c)
            it.setFlags(Qt.ItemIsEnabled)
            self.tbl.setItem(i, 1, it)
            kind = QComboBox()
            kind.addItems(KIND_CHOICES)
            guess = next((k for k, keys in [("수위", ("수위", "WAL", "level")), ("유량", ("유량", "DISCHA", "flow", "Q")),
                                              ("강우", ("강우", "강수", "rain", "RN"))] if any(x in c for x in keys)), "기타")
            kind.setCurrentText(guess)
            self.tbl.setCellWidget(i, 2, kind)
            self.tbl.setItem(i, 3, QTableWidgetItem({"수위": "m", "유량": "m³/s"}.get(guess, "")))
            rain = QComboBox()
            rain.addItems(RAIN_TYPES)
            self.tbl.setCellWidget(i, 4, rain)
            self.tbl.setItem(i, 5, QTableWidgetItem(""))
        self.tbl.resizeColumnsToContents()
        v.addWidget(self.tbl, 1)
        v.addWidget(QLabel("강우 구간값은 구간 끝 시각을 사용합니다. 종류·단위·간격을 확인하세요."))
        v.addWidget(QLabel("<b>미리보기</b> (앞 5행)"))
        prev = QTableWidget(min(5, len(raw)), len(raw.columns))
        prev.setHorizontalHeaderLabels(list(raw.columns))
        for i in range(min(5, len(raw))):
            for j, c in enumerate(raw.columns):
                prev.setItem(i, j, QTableWidgetItem(str(raw.iloc[i, j])))
        prev.setMaximumHeight(170)
        v.addWidget(prev)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def chosen(self):
        out = []
        for i in range(self.tbl.rowCount()):
            if self.tbl.item(i, 0).checkState() == Qt.Checked:
                out.append((self.tbl.item(i, 1).text(), self.tbl.cellWidget(i, 2).currentText(),
                            (self.tbl.item(i, 3).text() if self.tbl.item(i, 3) else "").strip(),
                            self.tbl.cellWidget(i, 4).currentText(), self.tbl.item(i, 5).text().strip()))
        return out

    def accept(self):
        if not self.site_code() and self.target.currentData() is None:
            QMessageBox.warning(self, "연결 대상", "지점이나 측정을 지정하세요.")
            return
        for _, kind, unit, rain, interval in self.chosen():
            if kind == "강우" and rain in ("구간 강우량", "누적 강우량"):
                try:
                    if float(interval) <= 0 or not math.isfinite(float(interval)):
                        raise ValueError
                except ValueError:
                    QMessageBox.warning(self, "강우 간격", "기록 간격을 분 단위로 입력하세요.")
                    return
        super().accept()

    def site_code(self):
        if self.target.currentData() is not None:
            return None
        d = self.site.currentData()
        if d and self.site.currentText() == self.site.itemText(self.site.currentIndex()):
            return d
        t = self.site.currentText().strip().split(" ")[0]
        return t if CODE_RE.match(t) else None


class DbTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.runner = main.runner
        default = str(Path.home() / "Documents" / "RSQ_측정기록.db")
        self.db_path = Path(main.settings.value("db_path", default))
        self.sess = pd.DataFrame()
        self._build()
        self.reload()

    # ------------------------------------------------------------ UI
    def _build(self):
        from rsq_compare.gui.main_window import FigureBox, Placeholder, make_table  # 순환 import 방지
        v = QVBoxLayout(self)
        r1 = QHBoxLayout()
        self.lbl_db = QLabel()
        self.lbl_db.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b_db = QPushButton("DB 파일 열기/새로 만들기…")
        r1.addWidget(QLabel("<b>누적 DB:</b>"))
        r1.addWidget(self.lbl_db, 1)
        r1.addWidget(b_db)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        self.b_import = QPushButton("📥 폴더에서 새 측정 가져오기")
        self.b_cat = QPushButton("소하천 목록 불러오기(220개소 등)")
        self.b_ref = QPushButton("비교 유량 양식 불러오기")
        self.b_ext = QPushButton("외부 자료(수위·유량·강우) 불러오기")
        self.b_export = QPushButton("💾 비교 결과 저장")
        self.b_review = QPushButton("측정 관계 확인")
        self.b_review.clicked.connect(self.review_measurement)
        self.b_code_review = QPushButton("코드 행 선택")
        self.b_code_review.clicked.connect(self.review_code)
        self.b_del = QPushButton("체크한 등록 삭제")
        for b in (self.b_import, self.b_cat, self.b_ref, self.b_ext, self.b_export, self.b_del, self.b_review, self.b_code_review):
            r2.addWidget(b)
        r2.addStretch(1)
        v.addLayout(r2)
        note = QLabel(NOTE_MULTI + " 노란 칸은 더블클릭해서 입력합니다. 비교 유량은 차이만 보여주고 판정하지 않습니다.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#444; padding:2px;")
        v.addWidget(note)

        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>등록된 세션</b> — ☑ 비교에 포함 · 행을 클릭하면 '지점·수위' 탭에 자세히 표시"))
        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.verticalHeader().setVisible(False)
        lv.addWidget(self.tbl, 1)
        hb = QHBoxLayout()
        b_all = QPushButton("전체 선택")
        b_none = QPushButton("전체 해제")
        hb.addWidget(b_all)
        hb.addWidget(b_none)
        lv.addLayout(hb)
        sp.addWidget(left)

        self.tabs = QTabWidget()
        self.fig_s = FigureBox()
        self.m_summ = DataFrameModel()
        w = QSplitter(Qt.Vertical)
        w.addWidget(self.fig_s)
        w.addWidget(make_table(self.m_summ))
        w.setSizes([430, 250])
        self.ph_s = Placeholder(w, "")
        self.tabs.addTab(self.ph_s, "세션 비교")

        # 지점·수위
        w = QWidget()
        gv = QVBoxLayout(w)
        self.lbl_site = QLabel("")
        self.lbl_site.setWordWrap(True)
        self.lbl_site.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_site.setStyleSheet("background:#f6f8fa; padding:6px; border:1px solid #ddd;")
        gv.addWidget(self.lbl_site)
        sh = QHBoxLayout()
        self.b_use_gps = QPushButton("GPS 제안 소하천코드 적용")
        self.b_use_gps.setEnabled(False)
        sh.addWidget(self.b_use_gps)
        sh.addStretch(1)
        gv.addLayout(sh)
        gv.addWidget(QLabel("<b>회차별 수위</b> — RSQ에 입력된 수위가 있으면 그 값을 쓰고, 없으면 '직접 입력 수위' 칸에 넣으세요."))
        self.tbl_gh = QTableWidget(0, 0)
        gv.addWidget(self.tbl_gh, 1)
        self.ph_g = Placeholder(w, "")
        self.tabs.addTab(self.ph_g, "지점·수위")

        self.fig_r = FigureBox()
        self.m_ref = DataFrameModel()
        w = QSplitter(Qt.Horizontal)
        w.addWidget(self.fig_r)
        w.addWidget(make_table(self.m_ref))
        self.tabs.addTab(w, "비교 유량")

        w = QWidget()
        ev = QVBoxLayout(w)
        eh = QHBoxLayout()
        eh.addWidget(QLabel("외부 자료:"))
        self.cmb_series = QComboBox()
        self.cmb_series.setMinimumWidth(380)
        eh.addWidget(self.cmb_series)
        eh.addWidget(QLabel("시간창 앞뒤 여유(분):"))
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0, 1440)
        self.spin_margin.setDecimals(1)
        self.spin_margin.setToolTip("회차 시간창이 짧아 자료가 없을 때 앞뒤로 넓혀 봅니다(보간은 하지 않음). "
                                    "예: FEWP 2분 간격이면 1~2분")
        eh.addWidget(self.spin_margin)
        self.b_target = QPushButton("연결 대상 지정")
        self.b_target.clicked.connect(self.assign_series_target)
        eh.addWidget(self.b_target)
        self.b_del_series = QPushButton("이 자료 삭제")
        eh.addWidget(self.b_del_series)
        eh.addStretch(1)
        ev.addLayout(eh)
        self.fig_e = FigureBox()
        self.m_ext = DataFrameModel()
        es = QSplitter(Qt.Vertical)
        es.addWidget(self.fig_e)
        es.addWidget(make_table(self.m_ext))
        self.m_ext_values = DataFrameModel()
        es.addWidget(make_table(self.m_ext_values))
        es.setSizes([380, 260])
        ev.addWidget(es, 1)
        self.ph_e = Placeholder(w, "")
        self.tabs.addTab(self.ph_e, "외부 자료 연결")
        self.m_tr = DataFrameModel()
        self.tabs.addTab(make_table(self.m_tr), "회차 전체")
        self.m_versions = DataFrameModel()
        self.tabs.addTab(make_table(self.m_versions), "측정 이력")
        self.m_codes = DataFrameModel()
        self.tabs.addTab(make_table(self.m_codes), "코드 확인")
        self.m_rep = DataFrameModel()
        self.tabs.addTab(make_table(self.m_rep), "가져오기 보고")
        sp.addWidget(self.tabs)
        sp.setSizes([640, 860])
        v.addWidget(sp, 1)

        b_db.clicked.connect(self.choose_db)
        self.b_import.clicked.connect(self.import_dir)
        self.b_cat.clicked.connect(self.import_catalog)
        self.b_ref.clicked.connect(self.import_ref)
        self.b_ext.clicked.connect(self.import_ext)
        self.b_export.clicked.connect(self.export)
        self.b_del.clicked.connect(self.delete_checked)
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none.clicked.connect(lambda: self._check_all(False))
        self.tbl.itemChanged.connect(self._on_item)
        self.tbl.currentCellChanged.connect(lambda r, *_: self.refresh_site(r))
        self.tbl_gh.itemChanged.connect(self._on_gh_item)
        self.b_use_gps.clicked.connect(self._apply_gps)
        self.cmb_series.currentIndexChanged.connect(lambda _i: self.refresh_ext())
        self.spin_margin.valueChanged.connect(lambda _v: self.refresh_ext())
        self.b_del_series.clicked.connect(self.delete_series)

    # ------------------------------------------------------------ DB 읽기/표
    def choose_db(self):
        p, _ = QFileDialog.getSaveFileName(self, "누적 DB 파일 (있으면 열고, 없으면 새로 만듦)", str(self.db_path),
                                           "SQLite DB (*.db)", options=QFileDialog.DontConfirmOverwrite)
        if p:
            self.db_path = Path(p)
            self.main.settings.setValue("db_path", str(self.db_path))
            self.reload()

    def reload(self):
        keep_row = max(self.tbl.currentRow(), 0)
        try:
            db.init_db(self.db_path)
            self.sess = db.sessions_df(self.db_path)
            self.cat = db.catalog_df(self.db_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "DB 열기 실패", f"누적 DB를 열지 못했습니다.\n{self.db_path}\n{e}")
            self.sess, self.cat = pd.DataFrame(), pd.DataFrame()
        self.lbl_db.setText(f"{self.db_path}   (등록 {len(self.sess)}건 · 소하천 목록 {len(self.cat)}곳)")
        tr_all = db.transects_df(self.db_path) if not self.sess.empty else pd.DataFrame()
        summ = session_summary(self.sess, tr_all) if not self.sess.empty else pd.DataFrame()
        mcol = next((c for c in summ.columns if c.startswith("회차 Total Q 산술평균")), None)
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(self.sess))
        for i, (_, s) in enumerate(self.sess.iterrows()):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if s.get("compare_selected",1) else Qt.Unchecked)
            chk.setToolTip(s.get("review_note") or "")
            self.tbl.setItem(i, 0, chk)
            mean = summ.loc[i, mcol] if mcol else None
            river = _nn(s.get("river_name"))
            code = _nn(s.get("site_code"))
            name = s["session_name"] + (" [확인 필요]" if s.get("review_status")=="pending" else f" [재처리 · 이전 #{int(s.previous_id)}]" if pd.notna(s.get("previous_id")) else "")
            vals = [str(s["id"]), name, s["dis_file"], s["date_measured"] or "",
                    code or "", river or ("목록에 없음" if code and not self.cat.empty else ""),
                    _nn(s.get("operator")) or "", str(s["n_transects_dis"]),
                    "" if mean is None or pd.isna(mean) else f"{mean:.4f}",
                    "" if _nn(s.get("ref_q")) is None else f"{s['ref_q']:g}", _nn(s.get("memo")) or ""]
            for j, val in enumerate(vals, start=1):
                it = QTableWidgetItem(str(val))
                if j in EDITABLE:
                    it.setBackground(EDIT_BG)
                    it.setToolTip("더블클릭해서 입력")
                else:
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if j == C_CODE and code:
                    it.setToolTip(f"출처: {_nn(s.get('site_code_source')) or ''}")
                self.tbl.setItem(i, j, it)
        self.tbl.resizeColumnsToContents()
        self.tbl.blockSignals(False)
        self.m_codes.set_df(catalog_review(self.db_path).rename(columns=KOR_LABEL))
        version_cols = {'id':'등록ID','measurement_id':'측정 묶음','previous_id':'이전 등록ID','session_name':'세션',
                        'dis_file':'사용 DIS','review_status':'확인 상태','review_note':'안내','folder':'원본 폴더'}
        versions = self.sess.reindex(columns=version_cols).rename(columns=version_cols)
        versions['확인 상태'] = versions['확인 상태'].replace({'confirmed':'확인됨','pending':'확인 필요'})
        self.m_versions.set_df(versions)
        self.cmb_series.blockSignals(True)
        self.cmb_series.clear()
        for _, r in db.series_df(self.db_path).iterrows():
            where = f"{r['site_code']} {_nn(r.get('river_name')) or ''}".strip() if _nn(r.get("site_code")) else "소하천 미지정"
            self.cmb_series.addItem(f"#{r['id']} [{_nn(r.get('kind')) or '기타'}] {r['name']} ({r['unit'] or '-'}) · {where} · "
                                    f"기준 {r['time_basis']} · {r['n_values']}개", int(r["id"]))
        self.cmb_series.blockSignals(False)
        if len(self.sess):
            self.tbl.setCurrentCell(min(keep_row, len(self.sess) - 1), 2)
        self.refresh_views()

    def checked_ids(self) -> list[int]:
        return [int(self.tbl.item(i, C_ID).text()) for i in range(self.tbl.rowCount())
                if self.tbl.item(i, C_CHECK).checkState() == Qt.Checked]

    def _check_all(self, on):
        self.tbl.blockSignals(True)
        for i in range(self.tbl.rowCount()):
            self.tbl.item(i, C_CHECK).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.tbl.blockSignals(False)
        for i in range(self.tbl.rowCount()):
            db.set_comparison_selected(self.db_path,int(self.tbl.item(i,C_ID).text()),on)
        self.refresh_views()

    def _on_item(self, it: QTableWidgetItem):
        row, col = it.row(), it.column()
        if col == C_CHECK:
            db.set_comparison_selected(self.db_path,int(self.tbl.item(row,C_ID).text()),it.checkState()==Qt.Checked)
            self.refresh_views()
            return
        sid = int(self.tbl.item(row, C_ID).text())
        txt = it.text().strip()
        if col == C_REF:
            q = to_number(txt) if txt else None
            if txt and q is None:
                QMessageBox.warning(self, "입력 확인", f"비교 유량은 숫자로 입력하세요: '{txt}'")
            else:
                unit = self.sess.loc[self.sess["id"] == sid, "q_unit"].iloc[0] or ""
                db.set_reference(self.db_path, sid, q, unit, "화면에서 직접 입력")
        elif col == C_MEMO:
            db.set_memo(self.db_path, sid, txt)
        elif col == C_OP:
            db.set_operator(self.db_path, sid, txt)
        elif col == C_CODE:
            if txt and not CODE_RE.match(txt):
                QMessageBox.warning(self, "입력 확인", f"소하천코드는 숫자 11자리입니다: '{txt}'")
            else:
                if txt and not self.cat.empty and txt not in set(self.cat["site_code"]):
                    QMessageBox.information(self, "소하천코드", "불러온 소하천 목록에 없는 코드입니다. 그대로 저장합니다.")
                db.set_site_code(self.db_path, sid, txt or None, "직접 입력")
        self.reload()

    # ------------------------------------------------------------ 보기
    def _selected(self):
        ids = self.checked_ids()
        sess = self.sess[self.sess["id"].isin(ids)].reset_index(drop=True) if not self.sess.empty else self.sess
        validate_comparison(sess)
        tr = db.transects_df(self.db_path, list(sess["id"]))
        tr = tr[tr.compare_selected.fillna(1) == 1] if not sess.empty else pd.DataFrame()
        return sess, tr

    def refresh_views(self):
        if self.sess.empty:
            msg = ("아직 등록된 세션이 없습니다.\n'📥 폴더에서 새 측정 가져오기'로 RSQ 내보내기 폴더를 고르거나,\n"
                   "'① 세션 보기' 탭에서 세션을 연 뒤 '📥 누적 DB에 등록'을 누르세요.")
            for ph in (self.ph_s, self.ph_e, self.ph_g):
                ph.show_empty(msg)
            self.m_ref.set_df(None)
            self.m_tr.set_df(None)
            self.fig_r.set_figure(fig_reference(pd.DataFrame()))
            return
        try:
            sess, tr = self._selected()
        except ValueError as e:
            self.ph_s.show_empty(str(e))
            self.ph_e.show_empty(str(e))
            self.m_summ.set_df(None)
            self.m_ref.set_df(None)
            self.m_tr.set_df(None)
            return
        self.refresh_site(self.tbl.currentRow())
        if sess.empty:
            self.ph_s.show_empty("왼쪽 표에서 비교할 세션을 체크하세요.")
            self.ph_e.show_empty("왼쪽 표에서 비교할 세션을 체크하세요.")
            return
        summ = session_summary(sess, tr)
        self.fig_s.set_figure(fig_sessions(sess, tr))
        self.m_summ.set_df(summ)
        self.ph_s.show_content()
        self.fig_r.set_figure(fig_reference(summ))
        self.m_ref.set_df(reference_by_transect(sess, tr))
        self.m_tr.set_df(_tr_view(tr))
        self.refresh_ext()

    def _current_sid(self, row=None):
        row = self.tbl.currentRow() if row is None else row
        if row is None or row < 0 or row >= self.tbl.rowCount() or self.tbl.item(row, C_ID) is None:
            return None
        return int(self.tbl.item(row, C_ID).text())

    def refresh_site(self, row):
        sid = self._current_sid(row)
        self._gps_code = None
        self.b_use_gps.setEnabled(False)
        if sid is None or self.sess.empty:
            self.ph_g.show_empty("왼쪽 표에서 세션(행)을 클릭하세요.")
            return
        s = self.sess[self.sess["id"] == sid].iloc[0]
        lines = [f"<b>#{sid} {s['session_name']}</b> ({s['dis_file']})"]
        code = _nn(s.get("site_code"))
        if code:
            if s.get("catalog_conflict"):
                lines.append("<b>소하천코드 충돌: 코드 확인 탭에서 행을 확인하세요.</b>")
            lines.append(f"소하천코드: {code}  <span style='color:#666'>(출처: {_nn(s.get('site_code_source')) or ''})</span>")
            c = self.cat[self.cat["site_code"] == code] if not self.cat.empty else pd.DataFrame()
            if not c.empty:
                lines.append(site_text(c.iloc[0].to_dict()).replace("\n", "<br>"))
                if _nn(c.iloc[0].get("aws_name")) is None:
                    lines.append("<span style='color:#9a3412'>목록에 이 소하천의 AWS 정보가 비어 있음</span>")
            elif self.cat.empty:
                lines.append("<span style='color:#9a3412'>소하천 목록을 아직 불러오지 않아 소하천명·AWS를 표시할 수 없음 "
                             "('소하천 목록 불러오기')</span>")
            else:
                lines.append("<span style='color:#9a3412'>불러온 소하천 목록에 이 코드가 없음</span>")
        else:
            lines.append("<span style='color:#9a3412'>소하천코드 없음 — 왼쪽 표 '소하천코드' 칸에 입력하세요. "
                         "(측정할 때 RSQ의 Station Number에 소하천코드를 적어 두면 자동으로 들어옵니다)</span>")
        lat, lon, n = _nn(s.get("gps_lat")), _nn(s.get("gps_lon")), _nn(s.get("gps_n"))
        if lat is not None and lon is not None:
            txt = f"RS5 GPS(.sum 위도·경도 {int(n or 0)}개 샘플 중앙값): {lat:.6f}, {lon:.6f}"
            if not self.cat.empty:
                near = nearest_sites(self.cat, lat, lon, 3)
                if not near.empty:
                    top = near.iloc[0]
                    txt += (f"<br>→ 가장 가까운 목록 소하천(관측소 위치 기준): <b>{top['river_name']} ({top['site_code']}), "
                            f"{top['거리_km']:.2f} km</b> · 다음: " + ", ".join(
                                f"{r['river_name']} {r['거리_km']:.1f} km" for _, r in near.iloc[1:].iterrows()))
                    txt += "<br><span style='color:#666'>※ 제안일 뿐입니다. 맞으면 아래 버튼으로 적용하세요.</span>"
                    if code != top["site_code"]:
                        self._gps_code = top["site_code"]
                        self.b_use_gps.setEnabled(True)
            lines.append(txt)
        else:
            lines.append("<span style='color:#666'>RS5 GPS 위치 없음(.sum 위도·경도가 비어 있음) → 소하천 자동 제안 불가</span>")
        self.lbl_site.setText("<br>".join(lines))
        # 수위 표
        gv = db.gauge_view(db.transects_df(self.db_path, [sid]))
        self._gh_df = gv
        cols = ["회차", "RSQ 시작 수위", "RSQ 끝 수위", "직접 입력 수위", "직접 입력 시각", "직접 입력 메모", "사용 수위", "출처", "비고"]
        self.tbl_gh.blockSignals(True)
        self.tbl_gh.clear()
        self.tbl_gh.setColumnCount(len(cols))
        self.tbl_gh.setHorizontalHeaderLabels(cols)
        self.tbl_gh.setRowCount(len(gv))
        for i, (_, r) in enumerate(gv.iterrows()):
            for j, c in enumerate(cols):
                v = _nn(r[c])
                it = QTableWidgetItem("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)))
                if c.startswith("직접 입력"):
                    it.setBackground(EDIT_BG)
                else:
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tbl_gh.setItem(i, j, it)
        self.tbl_gh.resizeColumnsToContents()
        self.tbl_gh.blockSignals(False)
        self.ph_g.show_content()

    def _on_gh_item(self, it: QTableWidgetItem):
        row = it.row()
        r = self._gh_df.iloc[row]
        get = lambda c: (self.tbl_gh.item(row, c).text().strip() if self.tbl_gh.item(row, c) else "")  # noqa: E731
        val_txt, t_txt, note = get(3), get(4), get(5)
        val = to_number(val_txt) if val_txt else None
        if val_txt and val is None:
            QMessageBox.warning(self, "입력 확인", f"수위는 숫자로 입력하세요: '{val_txt}'")
        else:
            db.set_gauge_manual(self.db_path, int(r["회차ID"]), val, t_txt, note)
        self.refresh_site(self.tbl.currentRow())

    def _apply_gps(self):
        sid = self._current_sid()
        if sid is not None and self._gps_code:
            db.set_site_code(self.db_path, sid, self._gps_code, "GPS 제안 적용(사용자 확인)")
            self.reload()

    def refresh_ext(self):
        sid = self.cmb_series.currentData()
        if sid is None:
            self.ph_e.show_empty("외부 자료가 없습니다.\n'외부 자료(수위·유량·강우) 불러오기'로 CSV/엑셀 파일을 추가하세요.\n"
                                 "파일 형식은 자유롭게 — 불러올 때 시각 열과 값 열을 고릅니다.")
            return
        try:
            sess, tr = self._selected()
        except ValueError as e:
            self.ph_s.show_empty(str(e))
            self.ph_e.show_empty(str(e))
            self.m_summ.set_df(None)
            self.m_ref.set_df(None)
            self.m_tr.set_df(None)
            return
        if sess.empty:
            return
        info = db.series_df(self.db_path)
        s = info[info["id"] == sid].iloc[0]
        vals = db.series_values(self.db_path, sid)
        m = match_to_transects(tr, sess, vals, s["time_basis"], self.spin_margin.value(),
                               site_code=_nn(s.get("site_code")), kind=_nn(s.get("kind")), unit=_nn(s.get("unit")),
                               target_session_id=_nn(s.get("target_session_id")),
                               rain_type=_nn(s.get("rain_type")), rain_interval_min=_nn(s.get("rain_interval_min")),
                               n_dropped=int(_nn(s.get("n_dropped")) or 0))
        shift = 0
        note = "UTC 기준 · 원문 시간대 우선"
        self.fig_e.set_figure(fig_external(vals, m, s["name"], s["unit"] or "", note, shift))
        self.m_ext.set_df(m)
        audit = vals[["t_raw", "time_applied", "t_utc", "value", "시각 보존 안내"]].copy()
        audit["t_utc"] = audit["t_utc"].map(lambda t: "" if pd.isna(t) else t.isoformat())
        self.m_ext_values.set_df(audit.rename(columns={"t_raw": "시각 원문", "time_applied": "적용 기준",
                                                      "t_utc": "시각 UTC", "value": "값"}))
        self.ph_e.show_content()

    def assign_series_target(self):
        sid = self.cmb_series.currentData()
        if sid is None:
            return
        options = {}
        for _, r in db.sessions_df(self.db_path).iterrows():
            options[f"측정 #{int(r['id'])}: {r['session_name']}"] = (None, int(r['id']))
        for _, r in self.cat.iterrows():
            options[f"지점 {r['site_code']}: {r['river_name']}"] = (r['site_code'], None)
        if not options:
            QMessageBox.information(self, "연결 대상", "먼저 측정이나 지점 목록을 불러오세요.")
            return
        label, ok = QInputDialog.getItem(self, "연결 대상", "연결할 지점 또는 측정", list(options), 0, False)
        if ok:
            code, target = options[label]
            db.set_series_target(self.db_path, sid, code, target)
            self.refresh_ext()

    # ------------------------------------------------------------ 작업
    def review_measurement(self):
        sid = self._current_sid()
        if sid is None:
            return
        options = {'별도 측정으로 확인':None}
        for _,r in self.sess.iterrows():
            if r.id != sid and r.review_status != 'pending':
                options[f"이전 #{int(r.id)} {r.session_name}의 재처리본"] = int(r.id)
        label,ok = QInputDialog.getItem(self,'측정 관계 확인','파일 내용과 이전 등록을 확인한 뒤 선택하세요.',list(options),0,False)
        if ok:
            try:
                db.resolve_measurement(self.db_path,sid,options[label])
            except ValueError as e:
                QMessageBox.warning(self,'측정 관계',str(e))
            self.reload()

    def review_code(self):
        rows = catalog_review(self.db_path)
        if rows.empty:
            return
        chosen,ok = QInputDialog.getInt(self,'코드 행 선택','코드 확인 표의 사용할 목록행ID',int(rows.iloc[0]['목록행ID']),1)
        row = rows[rows['목록행ID']==chosen]
        if ok and not row.empty:
            info = row.iloc[0]
            if QMessageBox.question(self,'코드 확인',f"{info['site_code']} / {info['river_name']} / 원본 행 {info['원본 행']}\n이 행을 사용하겠습니까?") == QMessageBox.Yes:
                resolve_catalog(self.db_path,chosen)
                self.reload()

    def register(self, sd):
        try:
            status, _sid, msg = db.register_session(self.db_path, sd, selected_nums=self.main.selected_nums())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "등록 실패", f"누적 DB에 등록하지 못했습니다.\n{e}")
            return
        QMessageBox.information(self, "누적 DB 등록", msg)
        self.reload()

    def import_dir(self):
        d = QFileDialog.getExistingDirectory(self, "새 측정 자료 폴더 선택 (하위 폴더까지 찾음)",
                                             self.main.settings.value("last_folder", str(Path.home())))
        if not d:
            return
        self.main._set_busy(True, "새 측정 가져오는 중...")
        self.runner.start(import_folder, Path(d), self.db_path, on_done=self._on_imported,
                          on_fail=lambda m, dt: self.main._error("가져오기 실패", m, dt),
                          on_progress=self.main.statusBar().showMessage)

    def _on_imported(self, rep: pd.DataFrame):
        self.main._set_busy(False, "가져오기 완료")
        self.m_rep.set_df(rep)
        self.reload()
        self.tabs.setCurrentIndex(self.tabs.count()-1)
        n_new = int((rep["결과"] == "새로 등록").sum()) if "결과" in rep else 0
        n_skip = int((rep["결과"] == "이미 등록됨(건너뜀)").sum()) if "결과" in rep else 0
        QMessageBox.information(self, "가져오기 완료",
                                f"새로 등록 {n_new}건, 이미 있어서 건너뜀 {n_skip}건, 기타 {len(rep) - n_new - n_skip}건\n"
                                "자세한 내용은 '가져오기 보고' 탭을 보세요.")

    def import_catalog(self):
        p, _ = QFileDialog.getOpenFileName(self, "소하천 목록 파일 (예: 220개소_…_AWS_특성정보포함.xlsx)", "",
                                           "엑셀/CSV (*.xlsx *.csv)")
        if not p:
            return
        try:
            cat, msgs = read_catalog_file(Path(p))
            n = db.save_catalog(self.db_path, cat, Path(p))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "소하천 목록 불러오기 실패", str(e))
            return
        self.reload()
        QMessageBox.information(self, "소하천 목록", f"소하천 {n}곳을 저장했습니다.\n\n" + "\n".join(msgs))

    def import_ref(self):
        p, _ = QFileDialog.getOpenFileName(self, "비교 유량 양식 파일", "", "CSV/엑셀 (*.csv *.xlsx)")
        if not p:
            return
        try:
            rep = db.import_reference_file(self.db_path, Path(p))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "비교 유량 불러오기 실패", str(e))
            return
        self.m_rep.set_df(rep)
        self.reload()
        QMessageBox.information(self, "비교 유량", "불러오기 결과는 '가져오기 보고' 탭에 있습니다.")

    def import_ext(self):
        p, _ = QFileDialog.getOpenFileName(self, "외부 자료 파일 (FEWP CSV, AWS 강우 등)", "", "CSV/엑셀 (*.csv *.xlsx)")
        if not p:
            return
        try:
            raw = read_raw_table(Path(p))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "파일 읽기 실패", str(e))
            return
        dlg = SeriesDialog(self, Path(p), raw, self.cat if not self.cat.empty else pd.DataFrame(
            columns=["site_code", "river_name", "sigungu"]), db.sessions_df(self.db_path))
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.chosen()
        if not chosen:
            QMessageBox.information(self, "외부 자료", "체크한 값 열이 없습니다.")
            return
        msgs = []
        for col, kind, unit, rain, interval in chosen:
            try:
                vals, dropped = extract_series(raw, dlg.tcol.currentText(), col)
                if vals.empty:
                    msgs.append(f"'{col}': 시각을 하나도 읽지 못해 건너뜀")
                    continue
                db.add_series(self.db_path, f"{dlg.prefix.text().strip()} {col}".strip(), unit, dlg.basis.currentText(),
                              list(vals["t_raw"]), list(vals["value"]), Path(p),
                              dropped, site_code=dlg.site_code(), kind=kind, target_session_id=dlg.target.currentData(),
                              rain_type=rain if kind == "강우" else None,
                              rain_interval_min=float(interval) if kind == "강우" and interval else None)
                msgs.append(f"'{col}' [{kind}]: {len(vals)}개 값, 시각 못 읽어 뺀 행 {dropped}개, "
                            f"빈값 {int(vals['value'].isna().sum())}개(0으로 바꾸지 않음)")
            except Exception as e:  # noqa: BLE001
                msgs.append(f"'{col}': 실패 — {e}")
        QMessageBox.information(self, "외부 자료", "\n".join(msgs))
        self.reload()
        self.cmb_series.setCurrentIndex(self.cmb_series.count() - 1)
        self.tabs.setCurrentIndex(3)

    def delete_series(self):
        sid = self.cmb_series.currentData()
        if sid is None:
            return
        if QMessageBox.question(self, "삭제 확인", "이 외부 자료를 DB에서 삭제할까요? (원본 파일은 그대로)") == QMessageBox.Yes:
            db.delete_series(self.db_path, sid)
            self.reload()

    def delete_checked(self):
        ids = self.checked_ids()
        if not ids:
            return
        if QMessageBox.question(self, "삭제 확인", f"체크한 등록 {len(ids)}건을 DB에서 삭제할까요?\n"
                                                   "(측정 원본 파일은 지워지지 않고, 다시 가져올 수 있습니다)") == QMessageBox.Yes:
            try:
                db.delete_sessions(self.db_path, ids)
            except ValueError as e:
                QMessageBox.warning(self,'등록 삭제',str(e))
            self.reload()

    def export(self):
        ids = self.checked_ids()
        if not ids:
            QMessageBox.information(self, "저장", "비교할 세션을 체크하세요.")
            return
        d = QFileDialog.getExistingDirectory(self, "결과를 저장할 위치 (안에 새 폴더가 생김)",
                                             self.main.settings.value("last_out", str(Path.home() / "Documents")))
        if not d:
            return
        self.main._set_busy(True, "누적 비교 결과 저장 중...")
        self.runner.start(export_db, self.db_path, ids, Path(d), self.spin_margin.value(),
                          on_done=self.main._on_saved,
                          on_fail=lambda m, dt: self.main._error("저장 실패", m, dt),
                          on_progress=self.main.statusBar().showMessage)
