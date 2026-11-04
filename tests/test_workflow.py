"""모든 지점/비교값은 가상. 원본 자료에 추정값을 추가하지 않는다."""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from rsq_compare.core import db,workflow
from rsq_compare.core.sites import read_catalog_file

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'private.db';db.init_db(self.path)
        with db.connect(self.path) as c:
            c.execute("INSERT INTO sessions(id,session_name,dis_sha256,q_unit,time_basis) VALUES(1,'가상','hash','m3/s','UTC+9')")
            c.execute("INSERT INTO transects(id,session_id,num,label,has_summary,total_q,start_time_raw,duration_s) VALUES(1,1,1,'T01',1,3,'2026-01-01 09:00:00',120)")
    def tearDown(self):self.tmp.cleanup()
    def test_local_site_does_not_invent_official_code_and_persists(self):
        key=workflow.assign_site(self.path,1,local_name='안동 실험수로',region='시험')
        db.init_db(self.path);r=db.sessions_df(self.path).iloc[0]
        self.assertTrue(key.startswith('local:'));self.assertIsNone(r.site_code);self.assertEqual(r.river_name,'안동 실험수로')
    def test_gauge_zero_missing_original_and_datum_are_distinct(self):
        workflow.save_gauge(self.path,1,0,'cm','2026-01-01 09:00','수위표','미확인')
        r=db.transects_df(self.path).iloc[0];self.assertEqual(r.gh_manual,0);self.assertIsNone(r.gh_start)
        self.assertEqual(r.gh_datum,'미확인');self.assertEqual(r.gh_manual_unit,'cm')
        workflow.save_gauge(self.path,1,None);self.assertIsNone(db.transects_df(self.path).iloc[0].gh_manual)
    def test_session_reference_is_one_baseline_not_replicated_observations(self):
        workflow.assign_site(self.path,1,local_name='시험')
        workflow.save_reference(self.path,1,0,'m3/s','가상 기준')
        result=workflow.reference_results(self.path,db.sessions_df(self.path),db.transects_df(self.path))
        self.assertEqual(len(result),1);self.assertIsNone(result.iloc[0]['상대 차이(%)']);self.assertEqual(result.iloc[0]['차이(RS5−비교)'],3)
        self.assertIn('동시 관측 아님',result.iloc[0]['적용 범위'])
    def test_mismatched_site_unit_and_time_block_calculation(self):
        workflow.assign_site(self.path,1,local_name='시험A')
        workflow.save_reference(self.path,1,2,'L/s','가상')
        workflow.save_reference(self.path,1,2,'m3/s','가상',scope='window',start='2026-01-02 00:00',end='2026-01-02 01:00')
        result=workflow.reference_results(self.path,db.sessions_df(self.path),db.transects_df(self.path))
        self.assertEqual(set(result['상태']),{'단위가 다름','대상 회차·시간이 맞지 않음'})
        workflow.assign_site(self.path,1,local_name='시험B')
        result=workflow.reference_results(self.path,db.sessions_df(self.path),db.transects_df(self.path))
        self.assertEqual(set(result['상태']),{'입력 당시 지점과 다름'})
    def test_search_last_of_220_synthetic_sites_assigns_code_without_stale_row(self):
        import os;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from rsq_compare.gui.input_dialogs import SiteDialog
        app=QApplication.instance() or QApplication([])
        p=Path(self.tmp.name)/'catalog.csv'
        p.write_text('소하천코드,소하천명,시군구\n'+'\n'.join(f'{i:011d},가상하천{i},지역{i%3}' for i in range(1,221)),encoding='utf-8')
        cat,_=read_catalog_file(p);db.save_catalog(self.path,cat,p)
        d=SiteDialog(None,self.path,1);self.assertEqual(len(d.visible),220)
        d.search.setText('00000000220');self.assertEqual(len(d.visible),1)
        self.assertEqual(d.table.currentRow(),-1)
        d.table.setCurrentCell(0,0);d.accept()
        self.assertEqual(db.sessions_df(self.path).iloc[0].site_code,'00000000220')


class AccumulatedUiTests(unittest.TestCase):
    setUp=WorkflowTests.setUp
    tearDown=WorkflowTests.tearDown
    def test_distinct_synthetic_measurements_filters_and_checkbox_persistence(self):
        import os;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QSettings,Qt,QDate
        from rsq_compare.gui.main_window import MainWindow
        from rsq_compare.gui.workers import JobRunner
        app=QApplication.instance() or QApplication([])
        settings=QSettings('NDMI','RSQCompare');previous=settings.value('db_path');settings.setValue('db_path',str(self.path))
        with db.connect(self.path) as c:
            c.execute("UPDATE sessions SET date_measured='2026-01-01',first_start_time='2026-01-01 09:00:00' WHERE id=1")
            c.execute("INSERT INTO sessions(id,session_name,dis_sha256,q_unit,time_basis,date_measured,first_start_time) VALUES(2,'별개 가상 측정','other-hash','m3/s','UTC+9','2026-01-02','2026-01-02 09:00:00')")
            c.execute("INSERT INTO transects(session_id,num,label,has_summary,total_q,start_time_raw,duration_s) VALUES(2,1,'T01',1,7,'2026-01-02 09:00:00',120)")
        workflow.assign_site(self.path,1,local_name='합성 시험지점A')
        w=MainWindow(JobRunner())
        try:
            self.assertEqual(len(w.dbtab._selected()[0]),2)
            w.dbtab.measure_search.setText('합성 시험지점A');self.assertEqual(len(w.dbtab.checked_ids()),1)
            w.dbtab.measure_search.clear();w.dbtab.unassigned.setChecked(True)
            self.assertEqual(w.dbtab.checked_ids(),[2]);w.dbtab.unassigned.setChecked(False)
            w.dbtab.date_from.setDate(QDate(2026,1,1));w.dbtab.date_to.setDate(QDate(2026,1,1));w.dbtab.use_dates.setChecked(True)
            self.assertEqual(w.dbtab.checked_ids(),[1])
            model=w.dbtab.m_tr;model.setData(model.index(0,0),Qt.Unchecked,Qt.CheckStateRole)
            self.assertEqual(db.transects_df(self.path,[1]).iloc[0].compare_selected,0)
            w.dbtab.reload();self.assertEqual(w.dbtab.m_tr._df.iloc[0]['상태'],'사용자 미선택')
        finally:
            w.close();settings.setValue('db_path',previous)

if __name__=='__main__':unittest.main()
