"""현재 측정에 적용 대상을 명시하는 입력창."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QLabel,QDialogButtonBox,QTableWidget,QTableWidgetItem,QMessageBox)
import pandas as pd
from rsq_compare.core import db
from rsq_compare.core import workflow


class SiteDialog(QDialog):
    def __init__(self,parent,path,sid):
        super().__init__(parent);self.path=path;self.sid=sid;self.setWindowTitle('현재 측정의 지점 지정');self.resize(780,550)
        v=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText('하천명 또는 관리코드 검색');v.addWidget(self.search)
        self.region=QComboBox();self.region.addItem('모든 지역');self.cat=db.catalog_df(path)
        self.region.addItems(sorted({str(r) for r in self.cat.sigungu.dropna()}));v.addWidget(self.region)
        self.count=QLabel();v.addWidget(self.count);self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['하천명','관리코드','지역']);self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setEditTriggers(QTableWidget.NoEditTriggers);v.addWidget(self.table,1)
        f=QFormLayout();self.local=QComboBox();self.local.addItem('새 시험 지점',None)
        for _,r in db.read_table(path,'SELECT * FROM local_sites').iterrows():self.local.addItem(f'{r["name"]} · {r["region"] or ""}',r.id)
        self.name=QLineEdit();self.area=QLineEdit();f.addRow('시험 지점',self.local);f.addRow('새 시험 지점 이름',self.name);f.addRow('시험 지점 지역',self.area);v.addLayout(f)
        v.addWidget(QLabel('목록 행을 선택하거나 시험 지점을 지정하세요. 공식 관리코드를 만들지 않습니다.'))
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);v.addWidget(buttons)
        self.search.textChanged.connect(self.filter);self.region.currentTextChanged.connect(self.filter);self.filter()
    def filter(self):
        q=self.search.text().strip();c=self.cat
        if q:c=c[c.site_code.str.contains(q,regex=False,na=False)|c.river_name.str.contains(q,regex=False,na=False)]
        if self.region.currentIndex():c=c[c.sigungu==self.region.currentText()]
        self.visible=c.reset_index(drop=True);self.table.setRowCount(len(c))
        for i,(_,r) in enumerate(c.iterrows()):
            for j,value in enumerate([r.river_name,r.site_code,f'{r.sido or ""} {r.sigungu or ""}']):self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.table.setCurrentCell(-1,-1);self.table.clearSelection()
        self.table.resizeColumnsToContents();self.count.setText(f'선택 가능한 지점 {len(self.cat)}곳 · 검색 결과 {len(c)}곳 (충돌 지점은 소하천 목록에서 확인)')
    def accept(self):
        try:
            if self.name.text().strip() or self.local.currentData():workflow.assign_site(self.path,self.sid,local_name=self.name.text(),region=self.area.text(),local_id=self.local.currentData())
            elif self.table.currentRow()>=0:workflow.assign_site(self.path,self.sid,code=self.visible.iloc[self.table.currentRow()].site_code)
            else:raise ValueError('지점 행을 선택하거나 시험 지점을 입력하세요.')
        except ValueError as e:QMessageBox.warning(self,'지점 지정',str(e));return
        super().accept()


class ObservationDialog(QDialog):
    def __init__(self,parent,path,sid,kind):
        super().__init__(parent);self.path=path;self.sid=sid;self.kind=kind;self.setWindowTitle('수위 입력' if kind=='gauge' else '비교 유량 입력');self.resize(530,460)
        v=QVBoxLayout(self);f=QFormLayout();self.tr=db.transects_df(path,[sid]);self.target=QComboBox()
        if kind!='gauge':self.target.addItem('측정 전체 기준값 (동시 관측 아님)',None);self.target.addItem('시간 범위','window')
        for _,r in self.tr.iterrows():self.target.addItem(r.label,int(r.id) if kind=='gauge' else int(r.num))
        self.value=QLineEdit();self.unit=QComboBox();self.unit.addItems(['m','cm'] if kind=='gauge' else ['m³/s','L/s'])
        self.time=QLineEdit();self.time.setPlaceholderText('관측 시각 원문 (예: 2026-10-29T10:40:00+09:00)');self.end=QLineEdit();self.basis=QComboBox();self.basis.addItems(['UTC+9','UTC'])
        self.source=QLineEdit();self.datum=QLineEdit('미확인');self.note=QLineEdit()
        for name,w in [('적용 대상',self.target),('값 (빈칸은 미입력)',self.value),('단위',self.unit),('관측/시작 시각',self.time),('끝 시각 (시간 범위)',self.end),('시간대 없는 값의 기준',self.basis),('출처',self.source)]:f.addRow(name,w)
        if kind=='gauge':f.addRow('기준면',self.datum);f.addRow('메모',self.note)
        v.addLayout(f);v.addWidget(QLabel('현재 선택한 측정에 저장합니다. 수심을 수위로 사용하지 않습니다.' if kind=='gauge' else '차이 = RS5−비교 · 상대 차이 = 차이/비교×100. 조건이 다르면 계산하지 않습니다.'))
        bb=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);bb.accepted.connect(self.accept);bb.rejected.connect(self.reject);v.addWidget(bb)
        if kind=='gauge':self.target.currentIndexChanged.connect(self.load_gauge);self.load_gauge()
    def load_gauge(self,*_):
        row=self.tr[self.tr.id==self.target.currentData()]
        if row.empty:return
        r=row.iloc[0]
        self.value.setText('' if pd.isna(r.gh_manual) else str(r.gh_manual))
        self.unit.setCurrentText(r.get('gh_manual_unit') or 'm')
        self.time.setText(r.get('gh_manual_time') or '')
        self.source.setText(r.get('gh_source') or '')
        self.datum.setText(r.get('gh_datum') or '미확인')
        self.note.setText(r.get('gh_manual_note') or '')
        basis=r.get('gh_manual_basis')
        if basis in ('UTC+9','UTC'):self.basis.setCurrentText(basis)

    def accept(self):
        try:
            value=float(self.value.text()) if self.value.text().strip() else None
            if self.kind=='gauge':workflow.save_gauge(self.path,self.target.currentData(),value,self.unit.currentText(),self.time.text(),self.source.text(),self.datum.text(),self.note.text(),basis=self.basis.currentText())
            else:
                if value is None:raise ValueError('비교 유량을 입력하세요.')
                target=self.target.currentData();scope='session' if target is None else 'window' if target=='window' else 'transect'
                workflow.save_reference(self.path,self.sid,value,self.unit.currentText(),self.source.text(),scope,target if scope=='transect' else None,self.time.text(),self.end.text(),self.basis.currentText())
        except (ValueError,TypeError) as e:QMessageBox.warning(self,'입력 확인',str(e));return
        super().accept()
