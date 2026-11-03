"""민감 열을 제외한 목록의 모든 행과 코드 충돌 확인 이력."""
import json
from pathlib import Path

import pandas as pd
from rsq_compare.core.identity import digest
from rsq_compare.core.sites import CATALOG_COLUMNS, KOR_LABEL, CODE_RE

KEYS = [k for k,_ in CATALOG_COLUMNS]


def _payload(row):
    return {k: None if row.get(k) is None or pd.isna(row.get(k)) else str(row.get(k)).strip() for k in KEYS}


def initialize_catalog(con):
    con.executescript('''CREATE TABLE IF NOT EXISTS catalog_entries(
        id INTEGER PRIMARY KEY, site_code TEXT NOT NULL, payload TEXT NOT NULL,
        source_file TEXT, source_row INTEGER, import_hash TEXT);
        CREATE TABLE IF NOT EXISTS catalog_choices(site_code TEXT PRIMARY KEY, entry_id INTEGER, group_hash TEXT);''')
    if not con.execute('SELECT 1 FROM catalog_entries LIMIT 1').fetchone():
        names = [r[1] for r in con.execute('PRAGMA table_info(site_catalog)')]
        for n,row in enumerate(con.execute('SELECT * FROM site_catalog').fetchall(),2):
            r = dict(zip(names,row));v=_payload(r)
            con.execute('INSERT INTO catalog_entries(site_code,payload,source_file,source_row,import_hash) VALUES(?,?,?,?,?)',
                        (v['site_code'],json.dumps(v,ensure_ascii=False),r.get('source_file'),n,'legacy'))


def store_catalog(con,cat,path):
    # 원본의 필요한 20개 열만 저장. 파일 자체나 민감 열을 복사하지 않는다.
    raw = cat.attrs.get('raw_rows') or [_payload(r) for r in cat.to_dict('records')]
    batch = digest([str(Path(path).resolve()),raw])
    if not con.execute('SELECT 1 FROM catalog_entries WHERE import_hash=?',(batch,)).fetchone():
        for n,r in zip(cat.attrs.get("source_rows",range(2,len(raw)+2)), raw):
            v = _payload(r)
            if not v['site_code']:
                continue
            con.execute('INSERT INTO catalog_entries(site_code,payload,source_file,source_row,import_hash) VALUES(?,?,?,?,?)',
                        (v['site_code'],json.dumps(v,ensure_ascii=False),str(path),n,batch))
    rebuild_catalog(con)
    return len(cat)


def _groups(con):
    groups = {}
    for rid,code,payload,path,row in con.execute('SELECT id,site_code,payload,source_file,source_row FROM catalog_entries ORDER BY id'):
        groups.setdefault(code,[]).append((rid,json.loads(payload),path,row))
    return groups


def rebuild_catalog(con):
    con.execute('DELETE FROM site_catalog')
    for code,rows in _groups(con).items():
        if not CODE_RE.fullmatch(code):
            continue
        unique = {digest(r[1]) for r in rows}
        state = digest(sorted(unique))
        choice = con.execute('SELECT entry_id,group_hash FROM catalog_choices WHERE site_code=?',(code,)).fetchone()
        selected = next((r for r in rows if choice and choice[1]==state and r[0]==choice[0]),None)
        if len(unique)>1 and selected is None:
            continue
        r = selected or rows[0]  # 모든 필드가 같은 중복만 대표 행을 사용할 수 있다.
        vals = [r[1].get(k) for k in KEYS]
        con.execute(f"INSERT INTO site_catalog({','.join(KEYS)},source_file,imported_at) VALUES({','.join('?' for _ in range(len(KEYS)+2))})",
                    vals+[r[2],'사용자 확인' if selected else '충돌 없음'])
    con.execute("""UPDATE sessions SET site_code=station_number_raw,site_code_source='RSQ 기록(Station Number)'
                   WHERE site_code IS NULL AND station_number_raw IN (SELECT site_code FROM site_catalog)""")


def catalog_review(db_path):
    from rsq_compare.core.db import connect
    result=[]
    with connect(db_path) as con:
        for code,rows in _groups(con).items():
            unique={digest(r[1]) for r in rows}
            changed=[k for k in KEYS if len({r[1][k] for r in rows})>1]
            state=digest(sorted(unique))
            choice=con.execute('SELECT entry_id,group_hash FROM catalog_choices WHERE site_code=?',(code,)).fetchone()
            confirmed=choice and choice[1]==state
            status='코드 형식 확인' if not CODE_RE.fullmatch(code) else '확인됨' if confirmed else '정보 충돌' if len(unique)>1 else '완전 중복' if len(rows)>1 else '정상'
            for rid,data,path,row in rows:
                result.append({'목록행ID':rid,'상태':status,'다른 항목':', '.join(KOR_LABEL.get(k,k) for k in changed),'선택한 행':bool(confirmed and choice[0]==rid),
                               **data,'원본 파일':path,'원본 행':row})
    return pd.DataFrame(result)


def resolve_catalog(db_path,entry_id):
    from rsq_compare.core.db import connect
    with connect(db_path) as con:
        row=con.execute('SELECT site_code FROM catalog_entries WHERE id=?',(entry_id,)).fetchone()
        if not row:
            raise ValueError('목록 행을 찾을 수 없습니다.')
        code=row[0];rows=_groups(con)[code]
        state=digest(sorted({digest(r[1]) for r in rows}))
        con.execute('INSERT OR REPLACE INTO catalog_choices VALUES(?,?,?)',(code,int(entry_id),state))
        rebuild_catalog(con)
