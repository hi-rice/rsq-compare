"""시간대·연결 범위·강우 안전성 회귀 검증. 모든 값은 가상 자료다.
실행: .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from rsq_compare.core import db
from rsq_compare.core.external import (extract_series, match_to_transects, normalize_time,
                                       normalized_values, parse_offset_hours)
from rsq_compare.core.multi import fig_external
from rsq_compare.core.parsers import parse_rsq_time


def measurements(start='2026-01-01 09:00:00', basis='UTC+9', duration=120):
    sess = pd.DataFrame([dict(id=i, time_basis=basis, site_code=c, q_unit='m3/s')
                         for i, c in [(1, '11111111111'), (2, '22222222222')]])
    tr = pd.DataFrame([dict(session_id=i, session_name=f'가상{i}', label='T01',
                            start_time_raw=start, duration_s=duration, total_q=3.) for i in [1, 2]])
    return tr, sess


def match(times, vals, **kwargs):
    tr, sess = measurements()
    kwargs.setdefault('target_session_id', 1)
    return match_to_transects(tr, sess, pd.DataFrame(dict(t=times, value=vals)), 'UTC+9', **kwargs)


class ExternalRegression(unittest.TestCase):
    def test_mixed_offsets_represent_same_instant(self):
        raw = pd.DataFrame({'시각': ['2026-01-01T00:00:00Z', '2026-01-01T09:00:00+09:00',
                                     '2026-01-01 09:00:00'], '값': ['1', '2', '3']})
        vals, dropped = extract_series(raw, '시각', '값')
        self.assertEqual(dropped, 0)
        norm = normalized_values(vals, 'UTC+9')
        self.assertEqual(norm.t_utc.nunique(), 1)
        self.assertEqual(list(norm.t_raw), list(raw['시각']))
        self.assertEqual(norm.time_applied.iloc[0], '원문 시간대')
        self.assertIn('사용자 기준', norm.time_applied.iloc[2])
        tr, sess = measurements()
        result = match_to_transects(tr, sess, vals, 'UTC+9', target_session_id=1).iloc[0]
        self.assertEqual(result['시간창 안 자료 수'], 3)
        self.assertEqual(result['평균'], 2)
        self.assertEqual(result['참고: 시간 차(분)'], 1)

    def test_explicit_dis_offset_overrides_selected_basis(self):
        tr, sess = measurements('2026-01-01T00:00:00Z', 'UTC+9')
        r = match_to_transects(tr, sess, pd.DataFrame({'t':['2026-01-01T09:01:00+09:00'], 'value':[4]}),
                               'unknown', target_session_id=1).iloc[0]
        self.assertEqual(r['시간창 안 자료 수'], 1)
        self.assertEqual(r['시작 시각 UTC'], '2026-01-01T00:00:00+00:00')
        self.assertEqual(parse_rsq_time('2026-01-01T09:00:00+09:00').utcoffset().total_seconds(), 32400)

    def test_unknown_naive_basis_does_not_guess(self):
        self.assertTrue(pd.isna(normalize_time('2026-01-01 09:00', None)[0]))
        self.assertFalse(pd.isna(normalize_time('2026-01-01T00:00Z', None)[0]))
        self.assertEqual(parse_offset_hours('UTC+05:30'), 5.5)
        self.assertIsNone(parse_offset_hours('UTC+09:99'))

    def test_unassigned_never_links_all_sessions(self):
        r = match(['2026-01-01 09:01:00'], [2], target_session_id=None)
        self.assertEqual(set(r['연결']), {'연결 대상 지정 필요'})
        self.assertNotIn('평균', r)

    def test_explicit_site_and_measurement_scope(self):
        r = match(['2026-01-01 09:01:00'], [2], target_session_id=None, site_code='22222222222')
        self.assertEqual(list(r['등록ID']), [2])
        r = match(['2026-01-01 09:01:00'], [2])
        self.assertEqual(list(r['등록ID']), [1])
        self.assertEqual(r.iloc[0]['시간창 시작 UTC'], '2026-01-01T00:00:00+00:00')

    def test_window_margin_counts_missing_and_nearest(self):
        r = match(['2026-01-01 08:59:30', '2026-01-01 09:01', '2026-01-01 09:05'],
                  [1, None, 9], margin_min=1).iloc[0]
        self.assertEqual(r['시간창 안 자료 수'], 2)
        self.assertEqual(r['시간창 안 빈값 수'], 1)
        self.assertEqual(r['앞뒤 여유(분)'], 1)
        self.assertEqual(r['참고: 시간 차(분)'], 0)
        with self.assertRaises(ValueError):
            match([], [], margin_min=-1)

    def rain(self, vals, typ='미확인', unit='mm', times=None):
        return match(times or ['2026-01-01 09:00', '2026-01-01 09:01', '2026-01-01 09:02'], vals,
                     kind='강우', unit=unit, rain_type=typ, rain_interval_min=1).iloc[0]

    def test_unknown_rain_and_units_never_sum(self):
        for typ, unit in [('미확인', 'mm'), ('구간 강우량',''), ('구간 강우량','mm/h')]:
            r = self.rain([10, 11, 12], typ, unit)
            self.assertNotIn('시간창 강우량(mm)', r)
            self.assertNotIn('합계(강우일 때 참고)', r)

    def test_interval_amounts_use_end_stamped_complete_intervals(self):
        self.assertEqual(self.rain([99, 1, 2], '구간 강우량')['시간창 강우량(mm)'], 3)

    def test_cumulative_uses_difference_not_sum(self):
        self.assertEqual(self.rain([10, 11, 13], '누적 강우량')['시간창 강우량(mm)'], 3)

    def test_reset_missing_negative_duplicate_gap_and_boundaries_block_total(self):
        cases = [([10, 0, 2], '누적 강우량', None),
                 ([10, None, 12], '누적 강우량', None),
                 ([0, -1, 2], '구간 강우량', None),
                 ([0, None, 2], '구간 강우량', None),
                 ([0, 1], '구간 강우량', ['2026-01-01 09:00','2026-01-01 09:02']),
                 ([0, 1], '구간 강우량', ['2026-01-01 09:01','2026-01-01 09:02']),
                 ([0, 1, 2, 3], '구간 강우량', ['2026-01-01 09:00','2026-01-01 09:01',
                                                          '2026-01-01 09:01','2026-01-01 09:02'])]
        for vals, typ, times in cases:
            with self.subTest(vals=vals, typ=typ):
                self.assertNotIn('시간창 강우량(mm)', self.rain(vals, typ, times=times))

    def test_unreadable_time_blocks_rain_total(self):
        times = ['2026-01-01 09:00','2026-01-01 09:01','2026-01-01 09:02']
        for dropped, timestamps, numbers in [(1, times, [0,1,2]), (0, times + ['bad'], [0,1,2,5])]:
            r = match(timestamps, numbers, kind='강우', unit='mm', rain_type='구간 강우량',
                      rain_interval_min=1, n_dropped=dropped).iloc[0]
            self.assertNotIn('시간창 강우량(mm)', r)
            self.assertEqual(r['강우 집계'], '읽지 못한 시각 확인 필요')

    def test_intensity_is_not_added_as_amount(self):
        r = self.rain([1, 3, 5], '강우강도', 'mm/h')
        self.assertEqual(r['평균'], 3)
        self.assertNotIn('시간창 강우량(mm)', r)
        self.assertIn('합산 안 함', r['강우 집계'])

    def test_db_preserves_offset_raw_and_normalization(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'test.db'
            raw = ['2026-01-01T09:00:00+09:00','2026-01-01T00:00:00Z']
            sid = db.add_series(p, '가상', 'm', 'UTC', raw, [1, 2], None, 0, site_code='11111111111')
            v = db.series_values(p, sid)
            self.assertEqual(list(v.t_raw), raw)
            self.assertEqual(v.t_utc.nunique(), 1)
            with db.connect(p) as con:
                self.assertEqual(con.execute('SELECT t_utc FROM ext_values').fetchone()[0],
                                 '2026-01-01T00:00:00+00:00')
            with self.assertRaises(ValueError):
                db.add_series(p, '길이 오류', '', 'UTC', raw, [1], None, 0)

    def test_legacy_schema_migration_preserves_rows_and_disables_unassigned(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'old.db'
            with sqlite3.connect(p) as con:
                con.executescript(db.SCHEMA)
                con.execute("INSERT INTO sessions(id,session_name,dis_sha256,memo) VALUES(1,'가상','hash','보존')")
                con.execute("INSERT INTO ext_series(id,name,time_basis) VALUES(7,'기존','UTC+9')")
                con.execute("INSERT INTO ext_values VALUES(7,'2026-01-01 09:01:00',2)")
            db.init_db(p)
            db.init_db(p)
            v = db.series_values(p, 7)
            self.assertEqual(v.iloc[0].value, 2)
            self.assertIn('유실 가능', v.iloc[0]['시각 보존 안내'])
            self.assertIsNone(db.series_df(p).iloc[0].target_session_id)
            self.assertEqual(db.sessions_df(p).iloc[0]['memo'], '보존')
            db.set_series_target(p, 7, target_session_id=1)
            self.assertEqual(db.series_df(p).iloc[0].target_session_id, 1)

    def test_utc_plot_uses_normalized_values(self):
        v = normalized_values(pd.DataFrame({'t':['2026-01-01T09:01+09:00'], 'value':[2]}), 'UTC')
        tr, sess = measurements()
        matched = match_to_transects(tr, sess, v, 'UTC', target_session_id=1)
        f = fig_external(v, matched, '가상', 'm', 'UTC', 0)
        self.assertEqual(len(f.axes[0].lines[0].get_xdata()), 1)
        self.assertEqual(f.axes[0].get_xlabel(), '시각 (UTC)')




class ImportDialogRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        from rsq_compare.gui.db_tab import SeriesDialog
        raw = pd.DataFrame({'시각':['2026-01-01T00:00Z'], 'rain':['1']})
        return SeriesDialog(None, Path('fake.csv'), raw,
                            pd.DataFrame(columns=['site_code','river_name','sigungu']),
                            pd.DataFrame([dict(id=3,session_name='가상 측정')]))

    def test_missing_target_prevents_accept(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog, QMessageBox
        d = self.dialog()
        with patch.object(QMessageBox, 'warning') as warning:
            d.accept()
            warning.assert_called_once()
        self.assertNotEqual(d.result(), QDialog.Accepted)
        d.target.setCurrentIndex(1)
        d.accept()
        self.assertEqual(d.result(), QDialog.Accepted)
        self.assertIsNone(d.site_code())

    def test_rain_is_not_inferred_as_mm_or_confirmed_type(self):
        d = self.dialog()
        self.assertEqual(d.tbl.item(1,3).text(), '')
        self.assertEqual(d.tbl.cellWidget(1,4).currentText(), '미확인')


if __name__ == '__main__':
    unittest.main()
