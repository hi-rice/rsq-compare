"""실제 측정 읽기 + 가상 외부자료 통합 검증. 원본 파일 해시를 대조한다.
사용: python tests/verify_external_real.py <private test folder>
외부 수위값 1,2,3은 검증용 가상값이며 실제 외부 관측자료가 아니다.
"""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from openpyxl import load_workbook
from rsq_compare import cli_db
from rsq_compare.core import db
from rsq_compare.core.batch import import_folder
from rsq_compare.core.db_export import export_db, external_tables
from rsq_compare.core.external import normalize_time


def hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def main():
    source = Path(sys.argv[1])
    before = hashes(source)
    assert before, '검증할 실제 자료가 없습니다.'
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database = root / 'check.db'
        import_folder(source, database)
        sess = db.sessions_df(database)
        tr = db.transects_df(database)
        valid = tr[tr.has_summary == 1].iloc[0]
        sid = int(valid.session_id)
        basis = sess.set_index('id').loc[sid, 'time_basis']
        start, _ = normalize_time(valid.start_time_raw, basis)
        assert start is not None and not pd.isna(start)
        # 같은 실제 시각을 Z, +09:00, 시간대 없는 한국시간으로 표현한다.
        raw = [start.isoformat().replace('+00:00', 'Z'),
               start.tz_convert('Asia/Seoul').isoformat(),
               start.tz_convert('Asia/Seoul').strftime('%Y-%m-%d %H:%M:%S')]
        csv = root / 'fake_external.csv'
        csv.write_text('시각,값\n' + '\n'.join(f'{t},{v}' for t,v in zip(raw,[1,2,3])), encoding='utf-8')
        assert cli_db.main(['ext',str(csv),'--db',str(database),'--name','가상 외부자료',
                            '--basis','UTC+9','--kind','수위','--unit','m','--session-id',str(sid)]) == 0
        info, matched, values = external_tables(database,sess,tr,0)[0]
        row = matched[matched['회차'] == valid.label].iloc[0]
        assert row['시간창 안 자료 수'] == 3 and row['평균'] == 2
        assert values.t_utc.nunique() == 1 and list(values.t_raw) == raw
        if '--gui' in sys.argv:
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QInputDialog
            from rsq_compare.gui.main_window import MainWindow
            from rsq_compare.gui.workers import JobRunner
            app = QApplication.instance() or QApplication([])
            w = MainWindow(JobRunner())
            w.dbtab.db_path = database
            legacy = db.add_series(database,'가상 미지정','m','UTC+9',raw,[1,2,3],None,0)
            w.dbtab.reload()
            w.dbtab.cmb_series.setCurrentIndex(w.dbtab.cmb_series.findData(legacy))
            w.dbtab.refresh_ext()
            assert set(w.dbtab.m_ext._df['연결']) == {'연결 대상 지정 필요'}
            def pick(parent, title, label, items, *args):
                return next(x for x in items if x.startswith(f'측정 #{sid}:')), True
            with patch.object(QInputDialog, 'getItem', side_effect=pick):
                w.dbtab.assign_series_target()
            row = w.dbtab.m_ext._df[w.dbtab.m_ext._df['회차'] == valid.label].iloc[0]
            assert row['시간창 안 자료 수'] == 3
            assert set(w.dbtab.m_ext_values._df['시각 원문']) == set(raw)
            w.close()
            app.processEvents()
            print('PASS GUI 기존 미지정 자료 차단 → 대상 지정 → 연결/시각 원문 표 표시')
        result = export_db(database, list(sess.id), root / 'output')
        wb = load_workbook(result['files'][0])
        audit = wb[f"시각원문_{int(info.id)}"]
        exported = [str(cell.value) for row in audit for cell in row]
        assert all(t in exported for t in raw)
        assert any('원문 시간대' in t for t in exported)
        assert all(p.exists() and p.stat().st_size > 0 for p in result['files'])
        assert db.transects_df(database).total_q.equals(tr.total_q)
        print('PASS 실제 측정 읽기 + 가상 외부자료 CLI/연결/UTC 그래프/엑셀 원문 추적/유량 불변')
    assert hashes(source) == before, '원본 측정자료가 변경됐습니다.'
    print('PASS 원본 측정자료 전체 파일 해시 불변')


if __name__ == '__main__':
    main()
