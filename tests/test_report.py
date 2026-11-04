import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook,load_workbook
from rsq_compare.core.report import add_summary
from rsq_compare.core import db
from rsq_compare.core.db_export import export_db

class ReportTests(unittest.TestCase):
    def test_native_chart_static_statistics_missing_and_safe_strings(self):
        wb=Workbook();wb.active.title='처리정보'
        records=[dict(label='T01',q=0.,selected=True,time='원문'),dict(label='T02',q=6.,selected=True,time='원문'),dict(label='T07',q=None,selected=False,time=None)]
        ws=add_summary(wb,[dict(point='=2+2',dis='source.dis',unit='m3/s',records=records)])
        self.assertEqual(wb.sheetnames[0],'결과 요약');self.assertTrue(ws.protection.sheet)
        self.assertEqual(ws['A11'].value,2);self.assertEqual(ws['B11'].value,3)
        self.assertEqual(ws['C11'].value,18**.5);self.assertEqual(ws['D11'].value,3);self.assertEqual(ws['E11'].value,1)
        self.assertEqual(ws['C15'].value,0);self.assertIsNone(ws['C17'].value);self.assertIsNone(ws['F17'].value);self.assertIsNone(ws['G17'].value)
        self.assertIn('요약 없음',ws['D17'].value);self.assertEqual(ws['B5'].data_type,'s')
        self.assertEqual(len(ws._charts),1);self.assertEqual(ws._charts[0].dispBlanksAs,'gap')
        self.assertFalse(any(c.data_type=='f' for row in ws for c in row))
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'result.xlsx';wb.save(p);out=load_workbook(p)
            self.assertEqual(out.active['B11'].value,3);self.assertEqual(len(out.active._charts),1)
    def test_no_comparison_sheet_without_comparison_data(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'private.db';db.init_db(p)
            with db.connect(p) as c:
                c.execute("INSERT INTO sessions(id,session_name,dis_sha256,q_unit) VALUES(1,'합성','hash','m3/s')")
                c.execute("INSERT INTO transects(session_id,num,label,has_summary,total_q) VALUES(1,1,'T01',1,0)")
                c.execute("INSERT INTO transects(session_id,num,label,has_summary,total_q,compare_selected) VALUES(1,7,'T07',0,NULL,0)")
            out=export_db(p,[1],Path(folder)/'output');w=load_workbook(out['files'][0])
            self.assertEqual(w.sheetnames[0],'결과 요약');self.assertNotIn('비교 유량',w.sheetnames)
            self.assertEqual(len(w.active._charts),1)
            self.assertNotIn(str(p),str(list(w.active.values)))
            self.assertNotIn('False',str(list(w.active.values)))

if __name__=='__main__':unittest.main()
