"""실제 test 한 건 + 명시적인 가상 사용자 입력. 실제 외부자료 호환 시험이 아니다."""
import hashlib
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings,Qt
from PySide6.QtWidgets import QApplication
from rsq_compare.core import db,workflow
from rsq_compare.core.discovery import scan_folder
from rsq_compare.core.loader import load_session
from rsq_compare.core.tables import selected_stats
from rsq_compare.gui.main_window import MainWindow
from rsq_compare.gui.workers import JobRunner
from rsq_compare.gui.input_dialogs import SiteDialog


def hashes(p):return {str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file()}

def main():
    source=Path(sys.argv[1]);output=Path(sys.argv[2]);output.mkdir(parents=True,exist_ok=True);before=hashes(source)
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'개인 DB.db';QSettings('NDMI','RSQCompare').setValue('db_path',str(path))
        w=MainWindow(JobRunner());w.show();w.open_folder(source)
        deadline=time.time()+60
        while w.sd is None or w.runner.busy():
            app.processEvents();time.sleep(.02)
            if time.time()>deadline:raise TimeoutError('측정 가져오기 실패')
        sd=w.sd
        selected=[r.num for r in sd.records if r.total_q is not None]
        for i in range(w.lst.count()):w.lst.item(i).setCheckState(Qt.Checked if w.lst.item(i).data(Qt.UserRole) in selected else Qt.Unchecked)
        st=selected_stats(sd,w.selected_nums())
        for actual,expected in [(st.mean,3.332042857142857),(st.std,0.4554451077687367),(st.pstd,0.4216602351153723),(st.cov,0.1265470623258836)]:assert abs(actual-expected)<1e-12
        assert sd.record(7).total_q is None
        status,sid,_=db.register_session(path,sd,selected_nums=w.selected_nums())
        d=SiteDialog(w,path,sid);d.name.setText('검증용 가상 시험지점');d.area.setText('실제 지점 아님');d.accept()
        workflow.save_gauge(path,int(db.transects_df(path).iloc[0].id),0,source='가상 검증',datum='미확인')
        workflow.save_reference(path,sid,0,'m3/s','가상 검증 기준값')
        w.dbtab.reload();assert db.sessions_df(path).iloc[0].site_code is None
        for width,height in [(1366,768),(1920,1080)]:
            w.resize(width,height)
            for main_tab in range(2):
                w.main_tabs.setCurrentIndex(main_tab)
                tabs=w.tabs if main_tab==0 else w.dbtab.tabs
                for tab in range(tabs.count()):
                    tabs.setCurrentIndex(tab)
                    for _ in range(8):app.processEvents();time.sleep(.015)
                    assert w.grab().save(str(output/f'{width}_{main_tab}_{tab}.png'))
                    if main_tab==0 and tab==2:
                        for inner in (1,2):
                            w.detail_tabs.setCurrentIndex(inner)
                            for _ in range(8):app.processEvents();time.sleep(.015)
                            assert w.grab().save(str(output/f'{width}_detail_{inner}.png'))
                        w.detail_tabs.setCurrentIndex(0)
        from rsq_compare.core.export import export_all
        from rsq_compare.core.db_export import export_db
        from openpyxl import load_workbook
        context=db.sessions_df(path).iloc[0].to_dict()
        exported=export_all(sd,selected,output/'exports',include_vel_plot=False,context=context)
        book=load_workbook(exported['files'][0]);summary=book.active
        assert book.sheetnames[0]=='결과 요약' and len(summary._charts)==1
        assert abs(summary['B11'].value-st.mean)<1e-12 and summary['A11'].value==7
        assert summary['C21'].value is None and '요약 없음' in summary['D21'].value
        assert str(source) not in str(list(summary.values))
        accumulated=export_db(path,[sid],output/'exports')
        assert load_workbook(accumulated['files'][0]).sheetnames[0]=='결과 요약'
        print('PASS 실제 측정 Excel 요약/내장 차트/선택 7회 통계/T07 빈값/지점/공유 요약 경로 비노출')
        w.close();app.processEvents()
        w2=MainWindow(JobRunner());w2._on_loaded(sd)
        assert w2.selected_nums()==selected
        assert db.sessions_df(path).iloc[0].river_name=='검증용 가상 시험지점'
        assert db.transects_df(path).iloc[0].gh_manual==0
        w2.close()
        print('PASS 실제 한 측정: 가져오기/가상 시험지점 지정/회차 선택/재실행 보존, 7회 통계 원정밀도 일치/T07 빈값')
        print('PASS 실행 화면 PNG 1366×768 및 1920×1080, 모든 주요 탭 캡처')
    assert hashes(source)==before;print('PASS 원본 전체 SHA-256 불변')

if __name__=='__main__':main()
