"""메인 창.

화면 구성
- 상단 : [데이터 폴더 선택] / 세션 선택 / [결과 저장]
- 왼쪽 : 회차 목록 (체크 = 비교통계 대상, 클릭 = 상세자료 보기)
- 오른쪽 탭 : 요약표 / 비교 그래프 / 상세자료 / 점검내역
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rsq_compare import APP_NAME, APP_VERSION
from rsq_compare.core.discovery import scan_folder
from rsq_compare.core.export import export_all
from rsq_compare.core.loader import load_session
from rsq_compare.core.model import SessionData, SessionFiles
from rsq_compare.core.plots import fig_depth_speed, fig_q_bar, fig_vel_profile
from rsq_compare.core.tables import (
    STATS_NOTE,
    STATS_TITLE,
    checks_table,
    dis_info_table,
    q_unit,
    selected_stats,
    stats_tables,
    summary_table,
    sum_with_sections,
)
from rsq_compare.core.loader import SECTION_ORDER
from rsq_compare.core.parsers import dis_overview
from rsq_compare.gui.df_model import DataFrameModel
from rsq_compare.gui.common import CopyTable, apply_theme


# ---------------------------------------------------------------- 작은 부품들
def make_table(model: DataFrameModel) -> QTableView:
    tv = CopyTable()
    tv.setModel(model)
    tv.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    tv.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    tv.setAlternatingRowColors(True)
    tv.setSelectionBehavior(QAbstractItemView.SelectRows)
    tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tv.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    tv.horizontalHeader().setDefaultSectionSize(110)
    tv.verticalHeader().setDefaultSectionSize(32)
    model.modelReset.connect(lambda: _fit_columns(tv))
    return tv


def _fit_columns(tv: QTableView, max_w: int = 340):
    """열 너비를 내용에 맞추되 너무 넓어지지 않게 제한."""
    tv.resizeColumnsToContents()
    for c in range(tv.model().columnCount()):
        if tv.columnWidth(c) > max_w:
            tv.setColumnWidth(c, max_w)


def note_label(text: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lb.setStyleSheet("color:#444; padding:4px 2px;")
    return lb


class Placeholder(QStackedWidget):
    """자료가 없을 때 빈 화면 대신 '이유'를 보여주는 틀."""

    def __init__(self, content: QWidget, empty_text: str):
        super().__init__()
        self._empty = QWidget()
        self._empty_layout = QVBoxLayout(self._empty)
        self._msg = QLabel(empty_text)
        self._empty_layout.addWidget(self._msg)
        self._actions = QHBoxLayout()
        self._empty_layout.addLayout(self._actions)
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet("color:#666; font-size:14px; padding:30px;")
        self.addWidget(self._empty)
        self.addWidget(content)

    def add_action(self,text,callback):
        button=QPushButton(text);button.clicked.connect(callback);self._actions.addWidget(button)
        return button

    def show_empty(self, text: str):
        self._msg.setText(text)
        self.setCurrentIndex(0)

    def show_content(self):
        self.setCurrentIndex(1)


class FigureBox(QWidget):
    """matplotlib 그림을 바꿔 끼우는 상자."""

    def __init__(self):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._canvas = None
        self.figure = None

    def set_figure(self, fig):
        if self._canvas is not None:
            self._lay.removeWidget(self._canvas)
            self._canvas.deleteLater()
        self.figure = fig
        self._canvas = FigureCanvasQTAgg(fig)
        self._lay.addWidget(self._canvas)
        self._canvas.draw_idle()


# ---------------------------------------------------------------- 메인 창
class MainWindow(QMainWindow):
    def __init__(self, runner):
        super().__init__()
        apply_theme(__import__("PySide6.QtWidgets",fromlist=["QApplication"]).QApplication.instance())
        self.runner = runner
        self.sessions: list[SessionFiles] = []
        self.scan_checks = []
        self.sd: SessionData | None = None
        self.settings = QSettings("NDMI", "RSQCompare")
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1400, 860)
        self._build_ui()
        self._refresh_all()

    # ------------------------------------------------------------ UI 구성
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        self.btn_folder = QPushButton("1  측정 가져오기")
        self.lbl_folder = QLabel("폴더를 선택하세요 (압축을 푼 RSQ 내보내기 폴더)")
        self.lbl_folder.setStyleSheet("color:#555;")
        self.cmb_session = QComboBox()
        self.cmb_session.setMinimumWidth(170)
        self.cmb_session.setMaximumWidth(320)
        self.cmb_session.setPlaceholderText("세션 없음")
        self.chk_vel = QCheckBox(".vel 셀 속도 분포 그림도 저장")
        self.chk_vel.setChecked(True)
        self.btn_save = QPushButton("4  결과 저장")
        self.btn_save.setProperty("primary",True)
        self.btn_reg = QPushButton("📥 누적 DB에 등록")
        self.btn_reg.setToolTip("지금 보고 있는 세션(선택한 .dis 기준)을 '② 누적·비교' 탭의 DB에 쌓습니다.")
        top.addWidget(self.btn_folder)
        self.lbl_folder.hide()
        top.addWidget(QLabel("세션:"))
        top.addWidget(self.cmb_session)
        self.chk_vel.hide()
        top.addWidget(self.btn_save)
        self.btn_point = QPushButton('2  지점 지정')
        self.btn_point.clicked.connect(self.assign_current_site)
        top.insertWidget(1,self.btn_point)
        self.btn_compare = QPushButton("3  회차·비교")
        self.btn_compare.clicked.connect(lambda:self.tabs.setCurrentIndex(1))
        top.insertWidget(2,self.btn_compare)
        self.btn_reg.setText('누적 등록')
        top.addWidget(self.btn_reg)
        root.addLayout(top)

        # 두 번째 줄: 사용할 .dis 선택
        top2 = QHBoxLayout()
        top2.addWidget(QLabel("DIS 파일:"))
        self.cmb_dis = QComboBox()
        self.cmb_dis.setMinimumWidth(180)
        self.cmb_dis.setMaximumWidth(360)
        self.cmb_dis.setToolTip("요약 결과(유량 등)를 읽을 .dis 파일. RSQ에서 다시 내보낸 .dis가 있으면 여기서 고릅니다.")
        self.btn_dis = QPushButton("다른 .dis 파일 선택…")
        self.lbl_dis = QLabel("")
        self.lbl_dis.setStyleSheet("color:#444;")
        self.lbl_dis.setWordWrap(True)
        top2.addWidget(self.cmb_dis)
        top2.addWidget(self.btn_dis)
        top2.addWidget(self.lbl_dis, 1)
        root.addLayout(top2)

        split = QSplitter(Qt.Horizontal)
        # 왼쪽: 회차 목록
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>회차 목록</b>"))
        lv.addWidget(note_label("☑ 체크 = 비교통계에 포함\n클릭 = 상세자료 탭에서 보기"))
        self.lst = QListWidget()
        lv.addWidget(self.lst, 1)
        hb = QHBoxLayout()
        self.btn_all = QPushButton("전체 선택")
        self.btn_none = QPushButton("전체 해제")
        hb.addWidget(self.btn_all)
        hb.addWidget(self.btn_none)
        lv.addLayout(hb)
        split.addWidget(left)

        # 오른쪽: 탭
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 1140])
        root.addWidget(split, 1)

        # 탭1 요약표
        self.m_summary = DataFrameModel()
        self.m_dis = DataFrameModel()
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(note_label(
            "폭·면적·평균 속력·총유량은 <b>DIS에 기록된 RSQ 결과</b>를 그대로 표시합니다(재계산 없음). "
            "시각은 파일 원문 그대로이며 시간대 변환을 하지 않습니다. 빈칸 = 원본에 값 없음. "
            "화면 숫자는 소수 4자리까지 표시(셀에 마우스를 올리면 원본 값)."))
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(make_table(self.m_summary))
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.addWidget(QLabel("<b>DIS 설정·전체 결과 (원문)</b>"))
        bv.addWidget(make_table(self.m_dis))
        sp.addWidget(box)
        sp.setSizes([480, 220])
        v.addWidget(sp, 1)
        self.ph_summary = Placeholder(w, "")
        self.tabs.addTab(self.ph_summary, "요약표")

        # 탭2 비교 그래프
        self.fig_bar = FigureBox()
        self.m_stat_sum = DataFrameModel()
        self.m_stat_det = DataFrameModel()
        w = QWidget()
        v = QVBoxLayout(w)
        self.lbl_stats_note = note_label(f"<b>{STATS_TITLE}</b> — {STATS_NOTE}")
        self.lbl_stats_note.setToolTip(STATS_NOTE)
        v.addWidget(self.lbl_stats_note)
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(self.fig_bar)
        bottom = QSplitter(Qt.Horizontal)
        t1 = make_table(self.m_stat_sum)
        t1.horizontalHeader().setStretchLastSection(True)
        bottom.addWidget(t1)
        t2 = make_table(self.m_stat_det)
        t2.horizontalHeader().setStretchLastSection(True)
        bottom.addWidget(t2)
        sp.addWidget(bottom)
        sp.setSizes([480, 240])
        v.addWidget(sp, 1)
        self.ph_compare = Placeholder(w, "")
        self.tabs.addTab(self.ph_compare, "비교 그래프")

        # 탭3 상세자료
        self.m_detail = DataFrameModel()
        self.fig_ds = FigureBox()
        self.fig_vel = FigureBox()
        w = QWidget()
        v = QVBoxLayout(w)
        hb = QHBoxLayout()
        hb.addWidget(QLabel("회차:"))
        self.cmb_detail = QComboBox()
        self.cmb_detail.setMinimumWidth(120)
        hb.addWidget(self.cmb_detail)
        hb.addWidget(QLabel("구간:"))
        self.cmb_section = QComboBox()
        self.cmb_section.setMinimumWidth(130)
        self.cmb_section.setToolTip("구간 정보는 .rsqmb에 RSQ가 기록한 샘플 타입입니다(추정 아님).")
        hb.addWidget(self.cmb_section)
        self.lbl_detail = note_label("")
        hb.addWidget(self.lbl_detail, 1)
        v.addLayout(hb)
        self.lbl_detail_note = note_label("")
        v.addWidget(self.lbl_detail_note)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.addTab(make_table(self.m_detail), "표 (.sum 원문)")
        self.detail_tabs.addTab(self.fig_ds, "수심 · 평균 속력 그래프")
        self.detail_tabs.addTab(self.fig_vel, ".vel 셀 속도 분포 (추가 기능)")
        v.addWidget(self.detail_tabs, 1)
        self.ph_detail = Placeholder(w, "")
        self.tabs.addTab(self.ph_detail, "상세자료")

        # 탭4 점검내역
        self.m_checks = DataFrameModel()
        self.m_src = DataFrameModel()
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(note_label("읽기 실패·파일 누락·출처 간 불일치·참고 관찰을 모았습니다. "
                               "‘주의’는 확인이 필요한 사항이며 측정 품질 판정이 아닙니다."))
        sp = QSplitter(Qt.Vertical)
        tchk = make_table(self.m_checks)
        tchk.horizontalHeader().setStretchLastSection(True)
        sp.addWidget(tchk)
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.addWidget(QLabel("<b>출처 비교 (참고)</b> — .dis vs .rsqmb 내부 Summary.json. "
                            "어느 값이 최종값인지 정하지 않으며, 화면·통계는 DIS 값만 사용합니다."))
        bv.addWidget(make_table(self.m_src))
        sp.addWidget(box)
        sp.setSizes([420, 260])
        v.addWidget(sp, 1)
        self.ph_checks = Placeholder(w, "")
        self.tabs.addTab(self.ph_checks, "점검내역")

        # 맨 위 탭: ① 세션 보기 / ② 누적·비교
        from rsq_compare.gui.db_tab import DbTab
        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(central, "① 측정 확인")
        self.dbtab = DbTab(self)
        self.main_tabs.addTab(self.dbtab, "② 지점·누적 비교")
        self.setCentralWidget(self.main_tabs)
        self.ph_summary.add_action("측정 가져오기",self.choose_folder)
        self._db_buttons = [self.dbtab.b_import, self.dbtab.b_export]
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        # 신호 연결
        self.btn_folder.clicked.connect(self.choose_folder)
        self.cmb_session.currentIndexChanged.connect(self.on_session_changed)
        self.cmb_dis.currentIndexChanged.connect(lambda _i: self._load_current())
        self.btn_dis.clicked.connect(self.choose_dis)
        self.cmb_section.currentIndexChanged.connect(lambda _i: self._refresh_detail(keep_section=True))
        self.btn_save.clicked.connect(self.save_results)
        self.btn_reg.clicked.connect(lambda: self.sd is not None and self.dbtab.register(self.sd))
        self.lst.itemChanged.connect(self._selection_changed)
        self.lst.currentRowChanged.connect(self._on_list_row)
        self.cmb_detail.currentIndexChanged.connect(lambda _i: self._refresh_detail(keep_section=False))
        self.btn_all.clicked.connect(lambda: self._check_all(True))
        self.btn_none.clicked.connect(lambda: self._check_all(False))

    # ------------------------------------------------------------ 상태
    def _set_busy(self, busy: bool, msg: str = ""):
        for w in (self.btn_folder, self.btn_save, self.cmb_session, self.cmb_dis, self.btn_dis, self.btn_reg,
                  *getattr(self, "_db_buttons", [])):
            w.setEnabled(not busy)
        self.progress.setVisible(busy)
        if msg:
            self.statusBar().showMessage(msg)

    def _error(self, title: str, msg: str, detail: str = ""):
        self._set_busy(False, f"{title}: {msg}")
        box = QMessageBox(QMessageBox.Warning, title, msg, parent=self)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    # ------------------------------------------------------------ 폴더/세션
    def choose_folder(self):
        start = self.settings.value("last_folder", str(Path.home()))
        d = QFileDialog.getExistingDirectory(self, "압축을 푼 데이터 폴더 선택", start)
        if d:
            self.settings.setValue("last_folder", d)
            self.open_folder(Path(d))

    def open_folder(self, folder: Path):
        self.lbl_folder.setText(str(folder))
        self._set_busy(True, "폴더를 살펴보는 중...")
        self.runner.start(_scan_job, folder, on_done=self._on_scanned,
                          on_fail=lambda m, d: self._error("폴더 읽기 실패", f"폴더를 읽지 못했습니다.\n{m}", d),
                          on_progress=self.statusBar().showMessage)

    def _on_scanned(self, res):
        self.sessions, self.scan_checks = res
        self.cmb_session.blockSignals(True)
        self.cmb_session.clear()
        for s in self.sessions:
            self.cmb_session.addItem(s.key)
        self.cmb_session.blockSignals(False)
        self._set_busy(False, f"세션 {len(self.sessions)}개를 찾았습니다.")
        if not self.sessions:
            self.sd = None
            self._refresh_all("선택한 폴더(하위 폴더 포함)에서 RSQ 내보내기 파일(.dis / _T번호.sum 등)을 찾지 못했습니다.\n"
                              "압축을 푼 폴더를 선택했는지 확인해 주세요.")
            return
        self.cmb_session.setCurrentIndex(0)
        self.on_session_changed(0)

    def on_session_changed(self, idx: int):
        if idx < 0 or idx >= len(self.sessions):
            return
        sf = self.sessions[idx]
        self.cmb_dis.blockSignals(True)
        self.cmb_dis.clear()
        for p in sf.dis_candidates:
            self.cmb_dis.addItem(p.name, p)
        if not sf.dis_candidates:
            self.cmb_dis.addItem("(.dis 없음)", None)
        self.cmb_dis.blockSignals(False)
        self._load_current()

    def _load_current(self):
        idx = self.cmb_session.currentIndex()
        if idx < 0 or idx >= len(self.sessions):
            return
        sf = self.sessions[idx]
        dis = self.cmb_dis.currentData()
        self._set_busy(True, f"세션 읽는 중: {sf.name}" + (f" (DIS: {dis.name})" if dis else ""))
        self.runner.start(load_session, sf, dis_path=dis, on_done=self._on_loaded,
                          on_fail=lambda m, d: self._error("세션 읽기 실패", f"세션을 읽는 중 문제가 생겼습니다.\n{m}", d),
                          on_progress=self.statusBar().showMessage)

    def choose_dis(self):
        idx = self.cmb_session.currentIndex()
        if idx < 0 or idx >= len(self.sessions):
            QMessageBox.information(self, "DIS 파일 선택", "먼저 데이터 폴더를 열어 세션을 선택하세요.")
            return
        sf = self.sessions[idx]
        p, _ = QFileDialog.getOpenFileName(self, "사용할 .dis 파일 선택", str(sf.folder), "RSQ 유량 요약 (*.dis)")
        if not p:
            return
        p = Path(p)
        try:
            ov = dis_overview(p)
        except Exception as e:  # noqa: BLE001
            self._error("DIS 파일 읽기 실패", f"이 파일을 .dis로 읽지 못했습니다.\n{e}")
            return
        if not ov["files"]:
            ans = QMessageBox.question(self, "확인", "이 .dis에서 회차표를 찾지 못했습니다. 그래도 사용할까요?")
            if ans != QMessageBox.Yes:
                return
        if p not in sf.dis_candidates:
            sf.dis_candidates.append(p)
            self.cmb_dis.addItem(p.name, p)
        self.cmb_dis.setCurrentIndex(self.cmb_dis.findData(p))  # → 다시 읽기

    def _on_loaded(self, sd: SessionData):
        self.sd = sd
        self._detail_num = None
        if sd.dis_path is not None:
            try:
                ov = dis_overview(sd.dis_path)
                self.lbl_dis.setText(f"이 .dis: 회차 {len(ov['files'])}개 · 전체 Total Q {ov['total_q_raw']} "
                                     "(RSQ 요약 패널에서 체크된 회차만 들어감)")
            except Exception:  # noqa: BLE001
                self.lbl_dis.setText("")
        else:
            self.lbl_dis.setText(".dis 없음 → 요약 결과 표시 불가")
        self._fill_list()
        self._set_busy(False, f"불러오기 완료: {sd.files.name} (회차 {len(sd.records)}개)")
        self._refresh_all()

    # ------------------------------------------------------------ 목록
    def assign_current_site(self):
        if self.sd is None:
            QMessageBox.information(self,'지점 지정','먼저 측정 폴더를 가져오세요.');return
        from rsq_compare.core import db
        status,sid,msg=db.register_session(self.dbtab.db_path,self.sd,selected_nums=self.selected_nums())
        if sid is None:
            QMessageBox.warning(self,'지점 지정',msg);return
        from rsq_compare.gui.input_dialogs import SiteDialog
        if SiteDialog(self,self.dbtab.db_path,sid).exec():
            self.dbtab.reload();self.statusBar().showMessage('지점 저장 완료',5000)

    def _selection_key(self):
        import hashlib
        return 'transects/' + hashlib.sha256(str(self.sd.dis_path.resolve() if self.sd.dis_path else self.sd.files.folder).encode()).hexdigest()

    def _selection_changed(self, *_):
        if self.sd is not None:
            self.settings.setValue(self._selection_key(), self.selected_nums())
            if hasattr(self,'dbtab'):
                from rsq_compare.core import db
                db.transect_selection(self.dbtab.db_path,self.sd,self.selected_nums())
        self._refresh_compare()

    def _fill_list(self):
        self.lst.blockSignals(True)
        self.lst.clear()
        self.cmb_detail.blockSignals(True)
        self.cmb_detail.clear()
        u = q_unit(self.sd) if self.sd else ""
        saved = self.settings.value(self._selection_key(), None)
        if saved is None and hasattr(self,'dbtab'):
            from rsq_compare.core import db
            saved = db.transect_selection(self.dbtab.db_path,self.sd)
        saved = {int(n) for n in saved} if isinstance(saved,(list,tuple)) else None
        for r in self.sd.records:
            if r.total_q is not None:
                txt = f"{r.label}   Q = {r.total_q:.4f} {u}"
            elif r.has_summary:
                txt = f"{r.label}   (DIS 유량 빈값)"
            else:
                txt = f"{r.label}   상세자료 있음 / 요약 결과 없음"
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, r.num)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (r.num in saved if saved is not None else r.total_q is not None) else Qt.Unchecked)
            it.setToolTip(r.status)
            if not r.has_summary:
                it.setForeground(Qt.darkRed)
            self.lst.addItem(it)
            self.cmb_detail.addItem(r.label, r.num)
        self.lst.blockSignals(False)
        self.cmb_detail.blockSignals(False)

    def _check_all(self, on: bool):
        self.lst.blockSignals(True)
        for i in range(self.lst.count()):
            self.lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.lst.blockSignals(False)
        self._selection_changed()

    def selected_nums(self) -> list[int]:
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                if self.lst.item(i).checkState() == Qt.Checked]

    def _on_list_row(self, row: int):
        if row >= 0:
            self.cmb_detail.setCurrentIndex(row)

    # ------------------------------------------------------------ 새로고침
    def _refresh_all(self, empty_reason: str | None = None):
        if self.sd is None:
            msg = empty_reason or "왼쪽 위 ‘데이터 폴더 선택’ 버튼으로 압축을 푼 RSQ 자료 폴더를 선택하세요."
            for ph in (self.ph_summary, self.ph_compare, self.ph_detail, self.ph_checks):
                ph.show_empty(msg)
            self.btn_save.setEnabled(False)
            self.btn_reg.setEnabled(False)
            return
        self.btn_save.setEnabled(True)
        self.btn_reg.setEnabled(True)
        sd = self.sd
        if sd.records:
            self.m_summary.set_df(summary_table(sd), highlight_col="상태")
            self.m_dis.set_df(dis_info_table(sd))
            self.ph_summary.show_content()
        else:
            self.ph_summary.show_empty("이 세션에는 회차 정보가 없습니다. 점검내역 탭을 확인하세요.")
        self.m_checks.set_df(checks_table(sd, self.scan_checks), highlight_col="수준")
        self.m_src.set_df(sd.source_compare)
        self.ph_checks.show_content()
        self._refresh_compare()
        self._refresh_detail()

    def _refresh_compare(self):
        sd = self.sd
        if sd is None:
            return
        if not any(r.total_q is not None for r in sd.records):
            self.ph_compare.show_empty("DIS 요약 결과(총유량)가 있는 회차가 없어 비교 그래프를 그릴 수 없습니다.\n"
                                       ".dis 파일이 있는지 점검내역 탭을 확인하세요.")
            return
        sel = self.selected_nums()
        st = selected_stats(sd, sel)
        fmt=lambda x:'계산 불가' if x is None else f'{x:.4f}'
        self.lbl_stats_note.setText(f'선택 {st.n}회 · 평균 {fmt(st.mean)} {q_unit(sd)}\n표본표준편차(n−1) {fmt(st.std)} · 모표준편차(n) {fmt(st.pstd)} · COV {fmt(st.cov)} (무차원)')
        s1, s2 = stats_tables(sd, st)
        self.m_stat_sum.set_df(s1)
        self.m_stat_det.set_df(s2)
        self.fig_bar.set_figure(fig_q_bar(sd, sel, st))
        self.ph_compare.show_content()

    def _refresh_detail(self, keep_section: bool = True):
        sd = self.sd
        if sd is None:
            return
        num = self.cmb_detail.currentData()
        if num is None:
            self.ph_detail.show_empty("회차가 없습니다.")
            return
        r = sd.record(num)
        df = sd.sum_dfs.get(num)
        if df is None:
            why = r.load_errors.get("sum") if r else None
            self.ph_detail.show_empty(
                f"{r.label if r else num}: .sum 파일을 {'읽지 못했습니다: ' + why if why else '찾지 못했습니다.'}")
            return
        sec = sd.sections.get(num)
        # 구간 선택 상자 채우기 (회차가 바뀌었을 때만)
        if not keep_section or getattr(self, "_detail_num", None) != num:
            self._detail_num = num
            self.cmb_section.blockSignals(True)
            self.cmb_section.clear()
            self.cmb_section.addItem("전체", None)
            if sec is not None:
                present = list(dict.fromkeys(sec.values))
                for name in [n for n in SECTION_ORDER if n in present] + [n for n in present if n not in SECTION_ORDER]:
                    self.cmb_section.addItem(name, name)
            self.cmb_section.setEnabled(sec is not None)
            self.cmb_section.blockSignals(False)
        chosen = self.cmb_section.currentData()
        view = sum_with_sections(sd, num, chosen)
        self.m_detail.set_df(view)
        self.fig_ds.set_figure(fig_depth_speed(view, r.label, sec, subset_name=chosen))
        fig, _mode = fig_vel_profile(sd.vel_dfs.get(num), r.label, sec)
        self.fig_vel.set_figure(fig)
        self.lbl_detail.setText(f"원본: {r.files['sum'].name}  ·  {len(df)}행  ·  {r.status}  ·  샘플 번호 점검: {r.sample_check}")
        if sec is not None:
            self.lbl_detail_note.setText(
                f"<b>구간:</b> {r.section_summary}<br>"
                "구간은 .rsqmb에 RSQ가 기록한 샘플 타입을 <b>샘플 번호로 연결</b>한 값입니다(추정 아님). "
                "표의 '구간' 열은 이 프로그램이 붙인 열이고, 그래프 음영으로도 표시합니다. 가로축은 샘플 번호입니다.")
        else:
            self.lbl_detail_note.setText(
                f"이 회차는 구간 정보를 연결하지 못했습니다({r.section_summary or '.rsqmb 없음'}). "
                "구간을 추정하지 않고 <b>파일 전체 기록</b>을 표시합니다. 가로축은 샘플 번호입니다.")
        self.ph_detail.show_content()

    # ------------------------------------------------------------ 저장
    def save_results(self):
        if self.sd is None:
            return
        start = self.settings.value("last_out", str(Path.home() / "Documents"))
        d = QFileDialog.getExistingDirectory(self, "결과를 저장할 위치 선택 (이 안에 새 폴더가 만들어집니다)", start)
        if not d:
            return
        self.settings.setValue("last_out", d)
        self._set_busy(True, "결과 저장 중...")
        self.runner.start(export_all, self.sd, self.selected_nums(), Path(d),
                          include_vel_plot=self.chk_vel.isChecked(),
                          on_done=self._on_saved,
                          on_fail=lambda m, dt: self._error(
                              "저장 실패",
                              f"결과를 저장하지 못했습니다.\n{m}\n\n엑셀에서 같은 파일을 열어두었거나 "
                              "저장 위치에 쓰기 권한이 없는지 확인하세요.", dt),
                          on_progress=self.statusBar().showMessage)

    def _on_saved(self, res):
        self._set_busy(False, f"저장 완료: {res['folder']}")
        box = QMessageBox(self)
        box.setWindowTitle("저장 완료")
        box.setText(f"결과를 저장했습니다.\n\n{res['folder']}\n\n엑셀 1개, 그래프 {len(res['files']) - 1}개")
        open_btn = box.addButton("폴더 열기", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_folder(res["folder"])

    def closeEvent(self, ev):
        self.runner.wait_all()
        super().closeEvent(ev)


def _scan_job(folder: Path, progress=None):
    if progress:
        progress("파일 목록 확인 중...")
    return scan_folder(folder)


def open_folder(p: Path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception:  # noqa: BLE001
        pass
