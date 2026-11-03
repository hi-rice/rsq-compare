"""실제 첨부 측정 읽기 + 임시 복사본의 가상 변경. 원본은 수정하지 않는다.
python tests/verify_identity_real.py <private test folder>
"""
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rsq_compare.core import db
from rsq_compare.core.discovery import scan_folder
from rsq_compare.core.loader import load_session
from rsq_compare.core.db_export import export_db


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def main():
    source=Path(sys.argv[1]);before=hashes(source);assert before
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);folder=root/'working';shutil.copytree(source,folder)
        database=root/'test.db'
        load=lambda p:load_session(scan_folder(p)[0][0])
        sd=load(folder);status,a,_=db.register_session(database,sd,selected_nums=[1,2])
        assert status=='added'
        db.set_memo(database,a,'가상 입력 보존')
        # 파일/폴더 이름만 바꾼 복사본은 같은 내용으로 감지.
        renamed=root/'renamed';shutil.copytree(folder,renamed)
        for p in list(renamed.iterdir()):
            if not p.name.startswith('~$'):
                p.rename(p.with_name(p.name.replace(sd.files.name,'renamed_20261029_105656')))
        assert db.register_session(database,load(renamed))[0]=='exists'
        # 임시 복사본에 빈 줄만 추가해 상세 파일 변경 감지를 검증.
        detail=next(folder.glob('*.sum'));detail.write_bytes(detail.read_bytes()+b'\n')
        status,b,_=db.register_session(database,load(folder));assert status=='version'
        mb=next(folder.glob('*.rsqmb'));mb.write_bytes(mb.read_bytes()+b'\n')
        status,c,_=db.register_session(database,load(folder));assert status=='version'
        rows=db.sessions_df(database).set_index('id')
        assert rows.loc[c,'measurement_id']==a and rows.loc[b,'previous_id']==a
        assert rows.loc[c,'memo']=='가상 입력 보존'
        assert db.transects_df(database,[c]).query('compare_selected == 1').num.tolist()==[1,2]
        try:
            export_db(database,[a,c],root/'blocked')
        except ValueError:
            pass
        else:
            raise AssertionError('같은 측정 버전의 중복 비교를 막지 못함')
        result=export_db(database,[c],root/'output')
        assert all(p.exists() and p.stat().st_size for p in result['files'])
        print('PASS 실제 측정 읽기 + 이름 변경 복사본 중복 방지')
        print('PASS 임시 복사본의 상세파일/rsqmb 가상 변경 감지, 버전 연결, 선택/메모 보존')
        print('PASS 다중 버전 비교 차단 및 한 버전 엑셀/그래프 저장')
        if '--gui' in sys.argv:
            from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
            from PySide6.QtCore import Qt
            from unittest.mock import patch
            from rsq_compare.gui.main_window import MainWindow
            from rsq_compare.gui.workers import JobRunner
            from rsq_compare.core.sites import read_catalog_file
            from rsq_compare.core.catalog import catalog_review
            app=QApplication.instance() or QApplication([])
            w=MainWindow(JobRunner());w.dbtab.db_path=database;w.dbtab.reload()
            w._on_loaded(load(folder))
            assert w.selected_nums()==[1,2]
            w.lst.item(0).setCheckState(Qt.Unchecked)
            assert db.transect_selection(database,load(folder))==[2]
            w._on_loaded(load(folder));assert w.selected_nums()==[2]
            w.dbtab._check_all(True)
            try:w.dbtab._selected()
            except ValueError:pass
            else:raise AssertionError('GUI 중복 버전 비교를 막지 못함')
            db.set_comparison_selected(database,a,False);db.set_comparison_selected(database,b,False)
            db.set_comparison_selected(database,c,True);w.dbtab.reload()
            csv=root/'codes.csv';csv.write_text('소하천코드,소하천명\n00123456789,가상A\n00123456789,가상B\n',encoding='utf-8')
            cat,_=read_catalog_file(csv);db.save_catalog(database,cat,csv);w.dbtab.reload()
            assert len(w.dbtab.m_codes._df)==2 and db.catalog_df(database).empty
            chosen=int(catalog_review(database).iloc[1]['목록행ID'])
            with patch.object(QInputDialog,'getInt',return_value=(chosen,True)),patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
                w.dbtab.review_code()
            assert db.catalog_df(database).iloc[0].river_name=='가상B'
            w.close();app.processEvents()
            print('PASS GUI 회차 선택 재열기/DB 보존, 다중버전 차단, 코드 모든 행 표시/사용자 선택')

    assert hashes(source)==before
    print('PASS 원본 측정자료 전체 SHA-256 불변')


if __name__=='__main__':main()
