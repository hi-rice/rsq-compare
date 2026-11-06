"""지점·관측 입력. 원본 DIS와 독립적인 사용자 정보만 저장한다."""
import math
from contextlib import closing
import sqlite3
import uuid
from pathlib import Path
import pandas as pd
from rsq_compare.core.external import normalize_time, norm_unit


def backup_upgrade(path):
    if not Path(path).exists(): return
    with closing(sqlite3.connect(path)) as con, con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='sessions'").fetchone(): return
        version=con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if version and int(version[0])>=5:return
        dest=Path(str(path)+'.before-v5.bak');n=2
        while dest.exists():dest=Path(str(path)+f'.before-v5-{n}.bak');n+=1
        with closing(sqlite3.connect(dest)) as target, target:con.backup(target)


def initialize(con):
    con.executescript('''CREATE TABLE IF NOT EXISTS local_sites(id TEXT PRIMARY KEY,name TEXT NOT NULL,region TEXT,note TEXT);
    CREATE TABLE IF NOT EXISTS comparison_values(id INTEGER PRIMARY KEY,session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    value REAL NOT NULL,unit TEXT,source TEXT,site_key TEXT,scope TEXT,transect_num INTEGER,start_raw TEXT,end_raw TEXT,time_basis TEXT,start_utc TEXT,end_utc TEXT);
    ''')


def site_key(row):
    if row.get('local_site_id') is not None and pd.notna(row.get('local_site_id')):return row['local_site_id']
    if row.get('site_code') and pd.notna(row.get('site_code')):return 'official:'+str(row['site_code'])
    return None


def assign_site(path,sid,code=None,local_name=None,region='',local_id=None):
    from rsq_compare.core import db
    db.init_db(path)
    with db.connect(path) as con:
        if code:
            if not con.execute('SELECT 1 FROM site_catalog WHERE site_code=?',(str(code),)).fetchone():
                raise ValueError('충돌 없는 목록 지점을 선택하세요.')
            con.execute("UPDATE sessions SET site_code=?,local_site_id=NULL,site_code_source='목록에서 직접 선택' WHERE id=?",(str(code),sid))
        else:
            if not local_id:
                if not local_name or not local_name.strip():raise ValueError('시험 지점 이름을 입력하세요.')
                local_id='local:'+str(uuid.uuid4())
                con.execute('INSERT INTO local_sites VALUES(?,?,?,?)',(local_id,local_name.strip(),region.strip(),None))
            if not con.execute('SELECT 1 FROM local_sites WHERE id=?',(local_id,)).fetchone():raise ValueError('시험 지점을 찾지 못했습니다.')
            con.execute("UPDATE sessions SET site_code=NULL,local_site_id=?,site_code_source='시험 지점 직접 지정' WHERE id=?",(local_id,sid))
    return local_id if not code else str(code)


def save_gauge(path,tid,value,unit='m',observed='',source='',datum='미확인',note='',basis='미확인'):
    from rsq_compare.core import db
    if value is not None and not math.isfinite(float(value)):raise ValueError('수위는 유한한 숫자로 입력하세요.')
    if unit not in ('m','cm'):raise ValueError('수위 단위를 확인하세요.')
    utc,_=normalize_time(observed,basis)
    with db.connect(path) as con:
        con.execute('''UPDATE transects SET gh_manual=?,gh_manual_unit=?,gh_manual_time=?,gh_source=?,gh_datum=?,gh_manual_note=?,gh_manual_basis=?,gh_manual_utc=?,gh_manual_explicit=1 WHERE id=?''',
                    (value,unit,observed or None,source or None,datum or '미확인',note or None,basis,None if pd.isna(utc) else utc.isoformat(),tid))


def save_reference(path,sid,value,unit,source,scope='session',num=None,start='',end='',basis='UTC+9'):
    from rsq_compare.core import db
    if not math.isfinite(float(value)):raise ValueError('비교 유량을 확인하세요.')
    if not source.strip():raise ValueError('비교값의 출처를 입력하세요.')
    if scope not in ('session','transect','window'):raise ValueError('적용 범위를 확인하세요.')
    if scope=='transect' and num is None:raise ValueError('대상 회차를 선택하세요.')
    a,b=None,None
    if scope=='window':
        a,_=normalize_time(start,basis);b,_=normalize_time(end,basis)
        if pd.isna(a) or pd.isna(b) or a>b:raise ValueError('시작·끝 시각과 시간 기준을 확인하세요.')
    row=db.sessions_df(path).set_index('id').loc[sid]
    with db.connect(path) as con:
        con.execute('''INSERT INTO comparison_values(session_id,value,unit,source,site_key,scope,transect_num,start_raw,end_raw,time_basis,start_utc,end_utc)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(sid,float(value),unit,source.strip(),site_key(row),scope,num,start,end,basis,
                        a.isoformat() if a is not None else None,b.isoformat() if b is not None else None))


def reference_results(path,sess,tr):
    from rsq_compare.core import db
    records=db.read_table(path,'SELECT * FROM comparison_values ORDER BY id')
    out=[]
    for _,s in sess.iterrows():
        obs=records[records.session_id==s.id]
        # 기존 기준값도 측정 전체 기준값으로만 해석한다. 회차 관측값으로 복제하지 않는다.
        if pd.notna(s.get('ref_q')):
            obs=pd.concat([obs,pd.DataFrame([dict(value=s.ref_q,unit=s.get('ref_unit'),source=s.get('ref_source'),site_key=s.get('ref_site_key'),scope='session')])],ignore_index=True)
        for _,o in obs.iterrows():
            ts=tr[(tr.session_id==s.id)&(tr.has_summary==1)]
            reason='';label='측정 전체 기준값 (동시 관측 아님)'
            if o.scope=='transect':ts=ts[ts.num==o.transect_num];label=f'T{int(o.transect_num):02d}'
            elif o.scope=='window':
                label='지정 시간 범위'
                keep=[]
                for _,t in ts.iterrows():
                    start,_=normalize_time(t.start_time_raw,s.time_basis)
                    stop=start+pd.Timedelta(seconds=float(t.duration_s)) if pd.notna(start) and pd.notna(t.duration_s) else pd.NaT
                    keep.append(pd.notna(stop) and start>=pd.Timestamp(o.start_utc) and stop<=pd.Timestamp(o.end_utc))
                ts=ts.loc[keep]
            if not site_key(s):reason='지점 미지정'
            elif pd.isna(o.get('site_key')) or o.get('site_key')!=site_key(s):reason='입력 당시 지점과 다름'
            elif norm_unit(o.unit)!=norm_unit(s.q_unit):reason='단위가 다름'
            elif ts.empty:reason='대상 회차·시간이 맞지 않음'
            q=ts.total_q.dropna().mean() if not ts.empty else None
            diff=float(q)-float(o.value) if not reason and q is not None and pd.notna(q) else None
            out.append({'지점':s.get('river_name') or '미지정','측정일시':s.first_start_time,'적용 범위':label,'RS5 유량 [DIS]':q,
                        '비교 유량':o.value,'단위':o.unit,'차이(RS5−비교)':diff,'상대 차이(%)':diff/o.value*100 if diff is not None and o.value!=0 else None,
                        '출처':o.source,'상태':reason or ('비교값 0: 상대 차이 없음' if o.value==0 else '비교 가능'),
                        '계산': '(RS5−비교) / 비교 × 100','시작 원문':o.get('start_raw'),'끝 원문':o.get('end_raw')})
    return pd.DataFrame(out)
