"""가상 측정/목록만 사용하는 중복·버전·충돌 회귀 검증."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from rsq_compare.core import db
from rsq_compare.core.catalog import catalog_review,resolve_catalog
from rsq_compare.core.identity import validate_comparison
from rsq_compare.core.model import DisResult,SessionData,SessionFiles,TransectRecord
from rsq_compare.core.sites import read_catalog_file,nearest_sites
from rsq_compare.core.db_export import export_db


class IdentityRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'test.db'
    def tearDown(self):
        self.tmp.cleanup()
    def sample(self,name='one',details=b'raw samples',dis=b'summary',rsqmb=b'raw container'):
        folder=self.root/name;folder.mkdir(exist_ok=True)
        dispath=folder/(name+'.dis');dispath.write_bytes(dis)
        mb=folder/(name+'.rsqmb');mb.write_bytes(rsqmb)
        (folder/(name+'_T01.sum')).write_bytes(details)
        sf=SessionFiles(name,folder,dis=dispath,rsqmb=mb)
        r=TransectRecord(1,'T01',dis_row_raw={'file':'01-Transect_20260101090000','start':'2026-01-01 09:00:00'},
                         dis_values={'total_q':3,'duration_s':120},n_rows={'sum':3})
        return SessionData(sf,DisResult(dispath,{},[],[],[]),{},[r],{1:pd.DataFrame({'샘플':[1],'값':[1]})},{},{},[],dis_path=dispath)
    def register(self,**kw):
        return db.register_session(self.db,self.sample(**kw))

    def test_renamed_copy_not_registered_twice(self):
        status,sid,_=self.register()
        status2,sid2,_=self.register(name='renamed')
        self.assertEqual((status,status2),('added','exists'))
        self.assertEqual(sid,sid2)
        self.assertEqual(len(db.sessions_df(self.db)),1)

    def test_details_and_rsqmb_changes_are_linked_versions(self):
        _,a,_=self.register()
        status,b,_=self.register(details=b'changed sample')
        self.assertEqual(status,'version')
        status,c,_=self.register(details=b'changed sample',rsqmb=b'changed container')
        self.assertEqual(status,'version')
        s=db.sessions_df(self.db).set_index('id')
        self.assertEqual(s.loc[b,'previous_id'],a)
        self.assertEqual(s.loc[c,'measurement_id'],a)
        self.assertEqual(list(s.compare_selected),[1,0,0])
        self.assertEqual(len({x for x in s.content_hash}),3)

    def test_unused_coordinate_file_included_in_fingerprint(self):
        sd=self.sample();other=sd.files.folder/'one_T01.XYZ.vel';other.write_bytes(b'xyz')
        db.register_session(self.db,sd)
        other.write_bytes(b'xyz changed')
        self.assertEqual(db.register_session(self.db,sd)[0],'version')

    def test_multiple_detail_aliases_are_all_fingerprinted(self):
        sd=self.sample();alias=sd.files.folder/'one_T1.sum';alias.write_bytes(b'other alias')
        db.register_session(self.db,sd)
        (sd.files.folder/'one_T01.sum').write_bytes(b'changed original alias')
        self.assertEqual(db.register_session(self.db,sd)[0],'version')
        self.assertEqual(len(json.loads(db.sessions_df(self.db).iloc[0].manifest_json)),4)

    def test_changed_dis_with_same_raw_data_is_related(self):
        _,a,_=self.register()
        status,b,_=self.register(dis=b'reprocessed summary')
        self.assertEqual(status,'version')
        self.assertEqual(db.sessions_df(self.db).set_index('id').loc[b,'previous_id'],a)

    def test_uncertain_relation_is_not_merged_and_requires_review(self):
        _,a,_=self.register()
        status,b,_=self.register(name='different',details=b'changed raw',dis=b'changed summary')
        self.assertEqual(status,'review')
        s=db.sessions_df(self.db).set_index('id')
        self.assertNotEqual(s.loc[a,'measurement_id'],s.loc[b,'measurement_id'])
        with self.assertRaises(ValueError): validate_comparison(s.reset_index())
        db.resolve_measurement(self.db,b)
        db.init_db(self.db)
        validate_comparison(db.sessions_df(self.db))
        self.assertEqual(len(db.sessions_df(self.db)),2)

    def test_confirmed_reprocessing_preserves_old_and_new_annotations(self):
        _,a,_=self.register()
        db.set_memo(self.db,a,'현장 메모');db.set_reference(self.db,a,4,'m3/s','사용자','비교 메모')
        with db.connect(self.db) as con:
            con.execute("UPDATE sessions SET operator='측정자',compare_selected=0 WHERE id=?",(a,))
            con.execute("UPDATE transects SET gh_manual=0.5,gh_manual_note='수위 메모',compare_selected=0 WHERE session_id=?",(a,))
        _,b,_=self.register(details=b'changed raw')
        self.assertEqual(db.sessions_df(self.db).set_index('id').loc[b,'memo'],'현장 메모')
        self.assertEqual(db.sessions_df(self.db).set_index('id').loc[b,'ref_q'],4)
        self.assertEqual(db.transects_df(self.db,[b]).iloc[0].gh_manual_note,'수위 메모')
        self.assertEqual(db.transects_df(self.db,[b]).iloc[0].compare_selected,0)
        self.assertEqual(db.sessions_df(self.db).set_index('id').loc[a,'compare_selected'],0)
        with self.assertRaises(ValueError):
            export_db(self.db,[a,b],self.root/'out')
        self.assertFalse((self.root/'out').exists())
        with self.assertRaises(ValueError):db.delete_sessions(self.db,[a])
        self.assertEqual(len(db.sessions_df(self.db)),2)
        # 재등록/다시 열기가 사용자 입력·선택을 되돌리지 않는다.
        self.register(details=b'changed raw');db.init_db(self.db)
        self.assertEqual(db.transects_df(self.db,[a]).iloc[0].gh_manual,0.5)

    def test_confirmation_does_not_overwrite_inputs_already_on_pending_version(self):
        _,a,_=self.register()
        with db.connect(self.db) as con:
            con.execute('UPDATE transects SET gh_manual=0.5 WHERE session_id=?',(a,))
        _,b,_=self.register(name='pending',details=b'new raw',dis=b'new summary')
        with db.connect(self.db) as con:
            con.execute('UPDATE transects SET gh_manual=0.9,compare_selected=0,selection_explicit=1 WHERE session_id=?',(b,))
        db.resolve_measurement(self.db,b,a)
        self.assertEqual(db.transects_df(self.db,[b]).iloc[0].gh_manual,0.9)
        self.assertEqual(db.transects_df(self.db,[b]).iloc[0].compare_selected,0)
        self.assertEqual(db.transects_df(self.db,[a]).iloc[0].gh_manual,0.5)

    def test_selection_survives_renamed_copy_and_reimport(self):
        sd=self.sample();_,a,_=db.register_session(self.db,sd,selected_nums=[])
        alias=self.sample(name='alias')
        self.assertEqual(db.transect_selection(self.db,alias),[])
        db.register_session(self.db,alias)
        self.assertEqual(db.transect_selection(self.db,sd),[])
        db.transect_selection(self.db,alias,[1])
        self.assertEqual(db.transect_selection(self.db,sd),[1])

    def test_legacy_copies_need_review_without_guessing_detail_history(self):
        db.init_db(self.db)
        with db.connect(self.db) as con:
            con.execute("DELETE FROM meta WHERE key='legacy_identity_review'")
            con.execute("INSERT INTO sessions(id,session_name,dis_sha256,memo) VALUES(1,'old','same','보존')")
            con.execute("INSERT INTO sessions(id,session_name,dis_sha256,memo) VALUES(2,'renamed','same','다른 메모')")
        db.init_db(self.db)
        self.assertEqual(set(db.sessions_df(self.db).review_status),{'pending'})
        db.resolve_measurement(self.db,1)
        db.resolve_measurement(self.db,2,1)
        db.init_db(self.db)
        with self.assertRaises(ValueError):validate_comparison(db.sessions_df(self.db))
        self.assertEqual(list(db.sessions_df(self.db).memo),['보존','다른 메모'])
        self.assertEqual(set(db.sessions_df(self.db).review_status),{'confirmed'})

    def test_legacy_unique_constraint_migration_keeps_ids_foreign_keys_and_backup(self):
        old=db.SCHEMA.replace('    memo TEXT\n);','    memo TEXT, UNIQUE(session_name, dis_sha256)\n);',1)
        with sqlite3.connect(self.db) as con:
            con.executescript(old)
            con.execute("INSERT INTO sessions(id,session_name,dis_sha256,memo) VALUES(42,'old','hash','보존')")
            con.execute("INSERT INTO reference_q(session_id,ref_q,memo) VALUES(42,4,'비교 메모')")
            con.execute("INSERT INTO transects(id,session_id,label,num) VALUES(55,42,'T01',1)")
            con.execute("CREATE INDEX user_memo_index ON sessions(memo)")
            con.execute("CREATE TABLE user_audit(sid INTEGER)")
            con.execute("CREATE TRIGGER user_audit_trigger AFTER INSERT ON sessions BEGIN INSERT INTO user_audit VALUES(new.id); END")
            con.execute("INSERT INTO sessions(id,session_name,dis_sha256) VALUES(90,'deleted','old')")
            con.execute('DELETE FROM sessions WHERE id=90')
        db.init_db(self.db);db.init_db(self.db)
        self.assertTrue(self.db.with_name('test.db.before-v4.bak').exists())
        self.assertEqual(db.sessions_df(self.db).iloc[0].id,42)
        self.assertEqual(db.sessions_df(self.db).iloc[0].ref_q,4)
        self.assertEqual(db.transects_df(self.db).iloc[0].id,55)
        with db.connect(self.db) as con:
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
            con.execute("INSERT INTO sessions(session_name,dis_sha256) VALUES('old','hash')")
            self.assertGreater(con.execute('SELECT MAX(id) FROM sessions').fetchone()[0],90)
            self.assertEqual(con.execute("SELECT count(*) FROM sqlite_master WHERE name='user_memo_index'").fetchone()[0],1)
            self.assertEqual(con.execute('SELECT count(*) FROM user_audit').fetchone()[0],2)


class CatalogRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'test.db'
    def tearDown(self):self.tmp.cleanup()
    def load(self,text,name='catalog.csv'):
        p=self.root/name;p.write_text(text,encoding='utf-8-sig')
        cat,msg=read_catalog_file(p);db.save_catalog(self.db,cat,p)
        return cat

    def test_identical_duplicates_all_retained_but_only_one_safe_site(self):
        c=self.load('소하천코드,소하천명\n00123456789,가상천\n00123456789,가상천\n')
        self.assertEqual(len(c),2)
        r=catalog_review(self.db)
        self.assertEqual(len(r),2)
        self.assertEqual(set(r['상태']),{'완전 중복'})
        self.assertEqual(list(db.catalog_df(self.db).site_code),['00123456789'])
        # 같은 파일 재가져오기는 목록행을 무한히 추가하지 않는다.
        db.save_catalog(self.db,c,self.root/'catalog.csv')
        self.assertEqual(len(catalog_review(self.db)),2)

    def test_conflict_blocks_auto_join_until_user_selects(self):
        self.load('소하천코드,소하천명,관측소 위도\n00123456789,가상A,37\n00123456789,가상B,38\n')
        self.assertTrue(db.catalog_df(self.db).empty)
        r=catalog_review(self.db)
        self.assertEqual(set(r['상태']),{'정보 충돌'})
        self.assertIn('소하천명',r.iloc[0]['다른 항목'])
        chosen=int(r.iloc[1]['목록행ID']);resolve_catalog(self.db,chosen)
        self.assertEqual(db.catalog_df(self.db).iloc[0].river_name,'가상B')
        self.assertEqual(len(catalog_review(self.db)),2)
        self.load('소하천코드,소하천명\n00123456789,가상C\n',name='new.csv')
        self.assertTrue(db.catalog_df(self.db).empty)
        self.assertEqual(len(catalog_review(self.db)),3)

    def test_conflict_does_not_attach_an_arbitrary_site_or_external_series(self):
        from rsq_compare.core.external import match_to_transects
        self.load('소하천코드,소하천명\n00123456789,가상A\n00123456789,가상B\n')
        with db.connect(self.db) as con:
            con.execute("INSERT INTO sessions(id,session_name,dis_sha256,site_code,time_basis) VALUES(1,'가상','x','00123456789','UTC')")
        sess=db.sessions_df(self.db)
        self.assertEqual(len(sess),1)
        self.assertIsNone(sess.iloc[0].river_name)
        self.assertEqual(sess.iloc[0].catalog_conflict,1)
        tr=pd.DataFrame([dict(session_id=1,session_name='가상',label='T01',start_time_raw='2026-01-01T00:00Z',duration_s=60)])
        values=pd.DataFrame({'t':['2026-01-01T00:00Z'],'value':[1]})
        matched=match_to_transects(tr,sess,values,'UTC',site_code='00123456789')
        self.assertEqual(matched.iloc[0]['연결'],'소하천코드 충돌 확인 필요')
        self.assertNotIn('평균',matched)

    def test_sensitive_columns_not_stored_and_csv_leading_zero_survives(self):
        self.load('소하천코드,소하천명,서비스 Key\n00123456789,가상천,DO_NOT_STORE_SECRET\n')
        self.assertEqual(db.catalog_df(self.db).iloc[0].site_code,'00123456789')
        self.assertNotIn(b'DO_NOT_STORE_SECRET',self.db.read_bytes())

    def test_formatted_excel_zero_prefix_survives(self):
        p=self.root/'formatted.xlsx';w=Workbook();s=w.active
        s.append(['소하천코드','소하천명']);s.append([123456789,'가상천']);s['A2'].number_format='00000000000';w.save(p)
        cat,_=read_catalog_file(p)
        self.assertEqual(cat.iloc[0].site_code,'00123456789')
        db.save_catalog(self.db,cat,p)
        self.assertEqual(db.catalog_df(self.db).iloc[0].site_code,'00123456789')

    def test_same_code_in_another_file_does_not_overwrite_old_info(self):
        self.load('소하천코드,소하천명\n00123456789,이전\n')
        self.load('소하천코드,소하천명\n00123456789,변경\n',name='second.csv')
        self.assertEqual(len(catalog_review(self.db)),2)
        self.assertTrue(db.catalog_df(self.db).empty)


if __name__=='__main__':unittest.main()
