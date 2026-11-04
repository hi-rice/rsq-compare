"""누적 저장소 (SQLite 파일 하나).

여러 번 측정한 결과를 한 파일에 쌓아 두고, 나중에 세션끼리 비교하거나
비교 유량·외부 시계열(수위, 강우 등)과 연결하기 위한 저장소다.

원칙
- 저장하는 값은 'DIS에 기록된 RSQ 결과'와 파일 출처 정보뿐이다(재계산 값 저장 안 함).
- 같은 세션 이름 + 같은 .dis 내용(SHA-256)은 한 번만 등록한다(중복 방지).
  같은 세션이라도 .dis가 다르면(예: T07 포함으로 다시 내보낸 .dis) 별도 등록으로 남긴다.
- 빈값은 NULL 로 저장한다(0으로 바꾸지 않음).
- 원본 측정 파일은 읽기만 한다.
"""
from __future__ import annotations

import hashlib
import math
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from rsq_compare.core.model import LEVEL_INFO, SessionData
from rsq_compare.core.parsers import to_number
from rsq_compare.core.sites import CODE_RE, gps_from_sum
from rsq_compare.core.tables import q_unit, time_basis

SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_name TEXT NOT NULL,
    site_name TEXT,
    date_measured TEXT,
    dis_file TEXT,
    dis_path TEXT,
    dis_sha256 TEXT NOT NULL,
    rsqmb_file TEXT,
    folder TEXT,
    n_transects_dis INTEGER,
    dis_total_q_raw TEXT,
    dis_total_q REAL,
    q_unit TEXT,
    time_basis TEXT,
    first_start_time TEXT,
    registered_at TEXT,
    memo TEXT
);
CREATE TABLE IF NOT EXISTS transects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    label TEXT, num INTEGER,
    has_summary INTEGER,
    file_name TEXT, start_edge TEXT,
    start_time_raw TEXT, duration_raw TEXT, duration_s REAL,
    width REAL, area REAL, mean_speed REAL, total_q REAL, pct_measured REAL,
    n_samples INTEGER, section_summary TEXT
);
CREATE TABLE IF NOT EXISTS reference_q (
    session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    ref_q REAL, unit TEXT, source TEXT, memo TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ext_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, unit TEXT, time_basis TEXT NOT NULL,
    source_file TEXT, source_sha256 TEXT, n_values INTEGER, n_dropped INTEGER,
    imported_at TEXT, memo TEXT
);
CREATE TABLE IF NOT EXISTS ext_values (
    series_id INTEGER NOT NULL REFERENCES ext_series(id) ON DELETE CASCADE,
    t TEXT NOT NULL, value REAL
);
CREATE INDEX IF NOT EXISTS ix_ext_values ON ext_values(series_id, t);
CREATE TABLE IF NOT EXISTS site_catalog (
    site_code TEXT PRIMARY KEY, river_name TEXT, sido TEXT, sigungu TEXT, emd TEXT, obs_address TEXT,
    obs_lat REAL, obs_lon REAL, sensor_type TEXT, install_date TEXT, interval_min TEXT, n_points TEXT,
    aws_id TEXT, aws_name TEXT, aws_lat REAL, aws_lon REAL, aws_dist_km REAL,
    slope REAL, length_km REAL, area_km2 REAL, source_file TEXT, imported_at TEXT
);
CREATE TABLE IF NOT EXISTS reg_checks (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    level TEXT, category TEXT, target TEXT, message TEXT
);
"""


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def connect(db_path: Path):
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# v0.4에서 추가된 열 (예전 DB는 열기만 하면 자동으로 추가됨, 기존 자료는 그대로)
MIGRATE_COLUMNS = {
    "sessions": [("local_site_id", "TEXT"), ("site_code", "TEXT"), ("site_code_source", "TEXT"), ("station_number_raw", "TEXT"),
                 ("operator", "TEXT"), ("gps_lat", "REAL"), ("gps_lon", "REAL"), ("gps_n", "INTEGER"), ("content_hash", "TEXT"), ("detail_hash", "TEXT"),
                 ("anchor_hash", "TEXT"), ("manifest_json", "TEXT"), ("measurement_id", "INTEGER"),
                 ("previous_id", "INTEGER"), ("review_status", "TEXT DEFAULT 'confirmed'"),
                 ("review_note", "TEXT"), ("compare_selected", "INTEGER DEFAULT 1")],
    "transects": [("gh_start", "REAL"), ("gh_start_time", "TEXT"), ("gh_end", "REAL"), ("gh_end_time", "TEXT"),
                  ("gh_unit", "TEXT"), ("gh_manual", "REAL"), ("gh_manual_time", "TEXT"), ("gh_manual_note", "TEXT"), ("gh_manual_unit", "TEXT DEFAULT 'm'"), ("gh_datum", "TEXT DEFAULT '미확인'"), ("gh_source", "TEXT"), ("compare_selected", "INTEGER DEFAULT 1"), ("selection_explicit", "INTEGER DEFAULT 0")],
    "ext_series": [("site_code", "TEXT"), ("kind", "TEXT"), ("target_session_id", "INTEGER"),
                   ("rain_type", "TEXT"), ("rain_interval_min", "REAL")],
    "ext_values": [("t_raw", "TEXT"), ("t_utc", "TEXT"), ("time_applied", "TEXT")],
}


def _migrate(con) -> None:
    for table, cols in MIGRATE_COLUMNS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))


def _prepare_v4(path):
    if not path.exists():
        return
    with sqlite3.connect(path) as con:
        row = con.execute("SELECT sql FROM sqlite_master WHERE name='sessions'").fetchone()
        if not row:
            return
        constraint = bool(re.search(r'UNIQUE\s*\(\s*session_name\s*,\s*dis_sha256\s*\)',row[0],re.I))
        if not constraint and 'content_hash' in row[0]:
            return
        # 고유 제약을 제거하기 전, 외래키와 사용자 입력을 포함한 DB 전체 백업.
        backup = path.with_name(path.name + '.before-v4.bak')
        n = 1
        while backup.exists():
            backup = path.with_name(path.name + f'.before-v4-{n}.bak')
            n += 1
        with sqlite3.connect(backup) as dest:
            con.backup(dest)
        if not constraint:
            return
        con.execute('PRAGMA foreign_keys=OFF')
        con.execute('BEGIN IMMEDIATE')
        objects = con.execute("SELECT sql FROM sqlite_master WHERE tbl_name='sessions' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        sequence = con.execute("SELECT seq FROM sqlite_sequence WHERE name='sessions'").fetchone()
        sql = re.sub(r'CREATE TABLE(?: IF NOT EXISTS)? ["`\[]?sessions["`\]]?', 'CREATE TABLE sessions_v4',row[0],count=1,flags=re.I)
        sql = re.sub(r',\s*UNIQUE\s*\(\s*session_name\s*,\s*dis_sha256\s*\)', '', sql)
        con.execute(sql)
        con.execute('INSERT INTO sessions_v4 SELECT * FROM sessions')
        con.execute('DROP TABLE sessions')
        con.execute('ALTER TABLE sessions_v4 RENAME TO sessions')
        for (sql,) in objects:
            con.execute(sql)
        if sequence:
            con.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='sessions'",sequence)
        if con.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('DB 이관 중 연결 오류. 백업을 확인하세요.')
        con.commit()


def init_db(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from rsq_compare.core.workflow import backup_upgrade
    backup_upgrade(db_path)
    _prepare_v4(db_path)
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        _migrate(con)
        from rsq_compare.core.catalog import initialize_catalog
        initialize_catalog(con)
        from rsq_compare.core.workflow import initialize
        initialize(con)
        con.execute("UPDATE sessions SET measurement_id=id WHERE measurement_id IS NULL")
        if not con.execute("SELECT 1 FROM meta WHERE key='legacy_identity_review'").fetchone():
            from rsq_compare.core.identity import digest
            for (sid,) in con.execute('SELECT id FROM sessions WHERE content_hash IS NULL').fetchall():
                anchors = con.execute('SELECT file_name,start_time_raw FROM transects WHERE session_id=? AND has_summary=1 AND file_name IS NOT NULL ORDER BY file_name,start_time_raw',(sid,)).fetchall()
                if anchors:
                    con.execute('UPDATE sessions SET anchor_hash=? WHERE id=?',(digest(anchors),sid))
            con.execute("""UPDATE sessions SET review_status='pending', review_note='이전 DB의 같은 DIS: 측정 관계 확인 필요'
                           WHERE content_hash IS NULL AND dis_sha256 IN
                           (SELECT dis_sha256 FROM sessions GROUP BY dis_sha256 HAVING count(*)>1)
                           OR (content_hash IS NULL AND anchor_hash IN
                           (SELECT anchor_hash FROM sessions WHERE anchor_hash IS NOT NULL GROUP BY anchor_hash HAVING count(*)>1))""")
            con.execute("INSERT INTO meta VALUES('legacy_identity_review','done')")
        con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('created_at', ?)", (_now(),))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 등록
def register_session(db_path: Path, sd: SessionData, memo: str = "", selected_nums: list[int] | None = None) -> tuple[str, int | None, str]:
    """세션 1개를 등록. 반환: (결과 'added'|'exists'|'no_dis', session_id, 안내 문구)"""
    init_db(db_path)
    if sd.dis_path is None or sd.dis is None:
        return "no_dis", None, f"{sd.files.name}: .dis가 없어 등록하지 않음(요약 결과가 없으면 비교할 값이 없음)"
    from rsq_compare.core.identity import fingerprint, copy_inputs
    fp = fingerprint(sd)
    sha = fp['manifest']['dis']['sha256']
    parent, pending, note = None, False, ''
    with connect(db_path) as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT id FROM sessions WHERE content_hash=?', (fp['content'],)).fetchone()
        if row:
            return 'exists', row[0], '입력 내용이 같은 자료입니다(이름·폴더가 달라도 중복 등록하지 않음).'
        known = con.execute('SELECT id,measurement_id,manifest_json,detail_hash,dis_sha256,review_status FROM sessions ORDER BY id DESC').fetchall()
        for rid, group, manifest, detail, old_dis, state in known:
            same_path = manifest and json.loads(manifest).get('dis',{}).get('path') == str(sd.dis_path.resolve())
            if state != 'pending' and manifest and ((fp['detail'] and fp['detail']==detail) or (same_path and sha==old_dis)):
                parent = rid
                break
        if parent:
            old_manifest = json.loads(next(r[2] for r in known if r[0]==parent))
            changed = [role for role in sorted(set(old_manifest)|set(fp['manifest']))
                       if old_manifest.get(role,{}).get('sha256') != fp['manifest'].get(role,{}).get('sha256')]
            note = f'재처리본: 이전 #{parent}. 바뀐 파일: ' + ', '.join(changed) + '. 비교할 버전 하나만 체크하세요.'
        else:
            candidates = con.execute("SELECT id FROM sessions WHERE anchor_hash=? OR dis_sha256=? OR (folder=? AND session_name=?)",
                         (fp['anchor'],sha,str(sd.files.folder),sd.files.name)).fetchall()
            if candidates:
                pending = True
                note = '동일 측정 여부 확인 필요: ' + ', '.join(f'#{r[0]}' for r in candidates)
        sec = sd.dis.sections
        station = (sec.get("Site Information", {}).get("Station Number") or "").strip() or None
        code, code_src = None, None
        if station and CODE_RE.match(station):
            code, code_src = station, "RSQ 기록(Station Number)"
        lat, lon, n_gps = gps_from_sum(sd.sum_dfs)
        total_raw = next((v for k, v in sec.get("Discharge Results", {}).items() if k.startswith("Total Q")), None)
        starts = [r.dis_row_raw.get("start") for r in sd.records if r.has_summary and r.dis_row_raw.get("start")]
        cur = con.execute(
            """INSERT INTO sessions(session_name, site_name, date_measured, dis_file, dis_path, dis_sha256,
               rsqmb_file, folder, n_transects_dis, dis_total_q_raw, dis_total_q, q_unit, time_basis,
               first_start_time, registered_at, memo, site_code, site_code_source, station_number_raw,
               gps_lat, gps_lon, gps_n) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sd.files.name,
             sec.get("Site Information", {}).get("Site Name") or None,
             sec.get("Discharge Measurement Summary", {}).get("Date Measured") or None,
             sd.dis_path.name, str(sd.dis_path), sha,
             sd.files.rsqmb.name if sd.files.rsqmb else None, str(sd.files.folder),
             sum(1 for r in sd.records if r.has_summary), total_raw, to_number(total_raw),
             q_unit(sd), time_basis(sd), min(starts) if starts else None, _now(), memo or None,
             code, code_src, station, lat, lon, n_gps))
        sid = cur.lastrowid
        group = con.execute('SELECT measurement_id FROM sessions WHERE id=?',(parent,)).fetchone()[0] if parent else sid
        con.execute("""UPDATE sessions SET content_hash=?,detail_hash=?,anchor_hash=?,manifest_json=?,
                       measurement_id=?,previous_id=?,review_status=?,review_note=?,compare_selected=? WHERE id=?""",
                    (fp['content'],fp['detail'],fp['anchor'],json.dumps(fp['manifest'],ensure_ascii=False),group,
                     parent,'pending' if pending else 'confirmed',note,0 if parent or pending else 1,sid))
        for r in sd.records:
            raw = r.dis_row_raw or {}
            v = r.dis_values
            con.execute(
                """INSERT INTO transects(session_id, label, num, has_summary, file_name, start_edge, start_time_raw,
                   duration_raw, duration_s, width, area, mean_speed, total_q, pct_measured, n_samples, section_summary,
                   gh_start, gh_start_time, gh_end, gh_end_time, gh_unit)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, r.label, r.num, int(r.has_summary), raw.get("file"), raw.get("edge"), raw.get("start"),
                 raw.get("duration"), v.get("duration_s"), v.get("width"), v.get("area"), v.get("speed"),
                 v.get("total_q"), v.get("pct"), r.n_rows.get("sum"), r.section_summary or None,
                 r.gauge.get("gh_start"), r.gauge.get("gh_start_time"), r.gauge.get("gh_end"),
                 r.gauge.get("gh_end_time"), r.gauge.get("unit")))
        if parent:
            copy_inputs(con,parent,sid)
        if selected_nums is not None:
            con.execute('UPDATE transects SET compare_selected=0,selection_explicit=1 WHERE session_id=?',(sid,))
            con.executemany('UPDATE transects SET compare_selected=1 WHERE session_id=? AND num=?',[(sid,int(n)) for n in selected_nums])
        keep = [c for c in sd.checks if c.level != LEVEL_INFO or c.category in ("회차 포함/제외", "사용한 .dis")]
        con.executemany("INSERT INTO reg_checks(session_id, level, category, target, message) VALUES(?,?,?,?,?)",
                        [(sid, c.level, c.category, c.target, c.message) for c in keep])
    if pending:
        return "review", sid, note
    if parent:
        return "version", sid, note
    return "added", sid, f"{sd.files.name} ({sd.dis_path.name}): 등록 완료 (회차 {len(sd.records)}개)"


def resolve_measurement(db_path, sid, previous_id=None):
    from rsq_compare.core.identity import copy_inputs
    with connect(db_path) as con:
        current = con.execute('SELECT review_status FROM sessions WHERE id=?',(sid,)).fetchone()
        if not current or current[0] != 'pending':
            raise ValueError('확인 대상 측정만 관계를 지정할 수 있습니다.')
        group = sid
        if previous_id is not None:
            p = con.execute('SELECT measurement_id,review_status FROM sessions WHERE id=?',(previous_id,)).fetchone()
            if not p or previous_id==sid or p[1]=='pending':
                raise ValueError('확인된 이전 측정을 선택하세요.')
            group = p[0] or previous_id
            copy_inputs(con,previous_id,sid)
        con.execute("""UPDATE sessions SET measurement_id=?,previous_id=?,review_status='confirmed',
                       review_note=?,compare_selected=0 WHERE id=?""",
                    (group,previous_id,'사용자 확인: 재처리본' if previous_id else '사용자 확인: 별도 측정',sid))


def transect_selection(db_path, sd, selected=None):
    from rsq_compare.core.identity import fingerprint
    if not Path(db_path).exists():
        return None
    content = fingerprint(sd)['content']
    with connect(db_path) as con:
        row = con.execute('SELECT id FROM sessions WHERE content_hash=?',(content,)).fetchone()
        if not row:
            return None
        if selected is not None:
            con.execute('UPDATE transects SET compare_selected=0,selection_explicit=1 WHERE session_id=?',(row[0],))
            con.executemany('UPDATE transects SET compare_selected=1 WHERE session_id=? AND num=?',[(row[0],int(n)) for n in selected])
        return [r[0] for r in con.execute('SELECT num FROM transects WHERE session_id=? AND compare_selected=1 ORDER BY num',(row[0],))]


def set_comparison_selected(db_path, sid, selected):
    with connect(db_path) as con:
        con.execute('UPDATE sessions SET compare_selected=? WHERE id=?',(int(bool(selected)),int(sid)))


def delete_sessions(db_path: Path, ids: list[int]) -> int:
    with connect(db_path) as con:
        for rid,group,previous in con.execute('SELECT id,measurement_id,previous_id FROM sessions'):
            if rid not in ids and (group in ids or previous in ids):
                raise ValueError('다른 버전이 연결된 이전 등록은 단독 삭제할 수 없습니다.')
        n = 0
        for i in ids:
            n += con.execute("DELETE FROM sessions WHERE id=?", (int(i),)).rowcount
    return n


def set_memo(db_path: Path, sid: int, memo: str) -> None:
    with connect(db_path) as con:
        con.execute("UPDATE sessions SET memo=? WHERE id=?", (memo or None, int(sid)))


# ---------------------------------------------------------------- 비교 유량
def set_reference(db_path: Path, sid: int, ref_q: float | None, unit: str = "", source: str = "",
                  memo: str = "") -> None:
    with connect(db_path) as con:
        if ref_q is None:
            con.execute("DELETE FROM reference_q WHERE session_id=?", (int(sid),))
        else:
            con.execute("""INSERT INTO reference_q(session_id, ref_q, unit, source, memo, updated_at)
                           VALUES(?,?,?,?,?,?)
                           ON CONFLICT(session_id) DO UPDATE SET ref_q=excluded.ref_q, unit=excluded.unit,
                           source=excluded.source, memo=excluded.memo, updated_at=excluded.updated_at""",
                        (int(sid), float(ref_q), unit or None, source or None, memo or None, _now()))


# ---------------------------------------------------------------- 외부 시계열
def add_series(db_path: Path, name: str, unit: str, time_basis_: str, times: list[str], values: list,
               source_file: Path | None, n_dropped: int, memo: str = "", site_code: str | None = None,
               kind: str | None = None, target_session_id: int | None = None,
               rain_type: str | None = None, rain_interval_min: float | None = None) -> int:
    from rsq_compare.core.external import normalize_time, RAIN_TYPES
    if len(times) != len(values):
        raise ValueError("시각과 값 개수가 다릅니다.")
    if rain_type is not None and rain_type not in RAIN_TYPES:
        raise ValueError("강우 종류를 확인하세요.")
    if rain_interval_min is not None and (not math.isfinite(float(rain_interval_min)) or float(rain_interval_min) <= 0):
        raise ValueError("기록 간격은 0보다 커야 합니다.")
    init_db(db_path)
    with connect(db_path) as con:
        if target_session_id is not None and not con.execute("SELECT 1 FROM sessions WHERE id=?", (int(target_session_id),)).fetchone():
            raise ValueError("연결할 측정이 없습니다.")
        if site_code and target_session_id is not None:
            raise ValueError("지점 또는 측정 중 하나만 지정하세요.")
        cur = con.execute(
            """INSERT INTO ext_series(name, unit, time_basis, source_file, source_sha256, n_values, n_dropped,
               imported_at, memo, site_code, kind, target_session_id, rain_type, rain_interval_min) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, unit or None, time_basis_, str(source_file) if source_file else None,
             sha256_file(source_file) if source_file else None, len(times), n_dropped, _now(), memo or None,
             site_code or None, kind or None, target_session_id, rain_type, rain_interval_min))
        sid = cur.lastrowid
        rows = []
        for t, v in zip(times, values):
            utc, applied = normalize_time(t, time_basis_)
            raw = str(t)
            rows.append((sid, raw, None if v is None or pd.isna(v) else float(v), raw,
                         None if pd.isna(utc) else utc.isoformat(), applied))
        con.executemany("INSERT INTO ext_values(series_id,t,value,t_raw,t_utc,time_applied) VALUES(?,?,?,?,?,?)", rows)
    return sid


def set_series_target(db_path: Path, series_id: int, site_code=None, target_session_id=None):
    init_db(db_path)
    if not site_code and target_session_id is None:
        raise ValueError("연결할 지점이나 측정을 지정하세요.")
    if site_code and target_session_id is not None:
        raise ValueError("지점 또는 측정 중 하나만 지정하세요.")
    with connect(db_path) as con:
        if target_session_id is not None and not con.execute("SELECT 1 FROM sessions WHERE id=?", (int(target_session_id),)).fetchone():
            raise ValueError("연결할 측정이 없습니다.")
        con.execute("UPDATE ext_series SET site_code=?, target_session_id=? WHERE id=?",
                    (site_code or None, target_session_id, int(series_id)))


def delete_series(db_path: Path, series_id: int) -> None:
    with connect(db_path) as con:
        con.execute("DELETE FROM ext_series WHERE id=?", (int(series_id),))


# ---------------------------------------------------------------- 읽기
def read_table(db_path: Path, sql: str, params=()) -> pd.DataFrame:
    with connect(db_path) as con:
        return pd.read_sql_query(sql, con, params=params)


def sessions_df(db_path: Path) -> pd.DataFrame:
    return read_table(db_path, """
        SELECT s.*, EXISTS(SELECT 1 FROM catalog_entries ce WHERE ce.site_code=s.site_code
          AND NOT EXISTS(SELECT 1 FROM site_catalog sc WHERE sc.site_code=ce.site_code)) AS catalog_conflict, r.ref_q, r.unit AS ref_unit, r.source AS ref_source, r.memo AS ref_memo,
               COALESCE(c.river_name,l.name) AS river_name, c.sido, COALESCE(c.sigungu,l.region) AS sigungu, c.sensor_type, c.interval_min,
               c.aws_id, c.aws_name, c.aws_dist_km, c.obs_lat, c.obs_lon
        FROM sessions s LEFT JOIN reference_q r ON r.session_id = s.id
        LEFT JOIN site_catalog c ON c.site_code = s.site_code LEFT JOIN local_sites l ON l.id=s.local_site_id
        ORDER BY COALESCE(s.first_start_time, s.date_measured, s.registered_at), s.id""")


def transects_df(db_path: Path, ids: list[int] | None = None) -> pd.DataFrame:
    sql = """SELECT t.*, s.session_name, s.dis_file FROM transects t JOIN sessions s ON s.id = t.session_id"""
    params: tuple = ()
    if ids is not None:
        if not ids:
            return read_table(db_path, sql + " WHERE 0")
        sql += f" WHERE t.session_id IN ({','.join('?' * len(ids))})"
        params = tuple(int(i) for i in ids)
    return read_table(db_path, sql + " ORDER BY t.session_id, t.num", params)


def series_df(db_path: Path) -> pd.DataFrame:
    return read_table(db_path, """SELECT e.*, c.river_name FROM ext_series e
        LEFT JOIN site_catalog c ON c.site_code = e.site_code ORDER BY e.id""")


def series_values(db_path: Path, series_id: int) -> pd.DataFrame:
    from rsq_compare.core.external import normalized_values
    init_db(db_path)
    values = read_table(db_path, "SELECT t, value, t_raw, t_utc, time_applied FROM ext_values WHERE series_id=? ORDER BY rowid", (int(series_id),))
    # 기존 DB의 t 원문을 유지한다. 예전에 버린 시간대는 복원할 수 없다.
    values["시각 보존 안내"] = values["t_raw"].isna().map({True: "이전 저장값: 원문 시간대 유실 가능, 원본 재가져오기 권장", False: "원문 보존"})
    values["t_raw"] = values["t_raw"].fillna(values["t"])
    info = series_df(db_path)
    row = info[info.id == series_id]
    return normalized_values(values, row.iloc[0]["time_basis"]) if not row.empty else values


def reg_checks_df(db_path: Path) -> pd.DataFrame:
    return read_table(db_path, """SELECT c.session_id AS 등록ID, s.session_name AS 세션, s.dis_file AS 사용한_dis,
        c.level AS 수준, c.category AS 분류, c.target AS 대상, c.message AS 내용
        FROM reg_checks c JOIN sessions s ON s.id = c.session_id ORDER BY c.session_id""")



# ---------------------------------------------------------------- 비교 유량 양식 불러오기
REF_TEMPLATE_COLS = ["세션", "사용한_dis", "비교 유량", "단위", "출처", "메모"]


def import_reference_file(db_path: Path, path: Path) -> pd.DataFrame:
    """비교 유량 양식(CSV/엑셀)을 읽어 '세션'(+선택: '사용한_dis') 이름이 같은 등록 세션에 비교 유량을 넣는다.
    반환: 줄마다 처리 결과 표. 비교 유량이 숫자가 아니면 넣지 않는다(0으로 바꾸지 않음)."""
    from rsq_compare.core.parsers import ENCODINGS
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path, dtype=str)
    else:
        df = None
        for enc in ENCODINGS:
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise ValueError("글자 인코딩을 알 수 없습니다.")
    df.columns = [str(c).strip() for c in df.columns]
    qcol = "비교유량" if "비교유량" in df.columns else ("기준유량" if "기준유량" in df.columns else None)  # 예전 양식 호환
    if "세션" not in df.columns or qcol is None:
        raise ValueError("양식에 '세션', '비교유량' 열이 있어야 합니다. (templates 폴더의 비교유량_양식.csv 참고)")
    sess = sessions_df(db_path)
    out = []
    for i, r in df.iterrows():
        name = str(r.get("세션") or "").strip()
        dis = str(r.get("사용한_dis") or "").strip()
        q = to_number(r.get(qcol))
        if not name:
            continue
        cand = sess[sess["session_name"] == name]
        if dis:
            cand = cand[cand["dis_file"] == dis]
        if q is None:
            out.append({"양식 행": i + 2, "세션": name, "결과": "건너뜀(비교유량이 숫자가 아님)", "적용 등록ID": None})
            continue
        if cand.empty:
            out.append({"양식 행": i + 2, "세션": name, "결과": "건너뜀(DB에 같은 세션 없음)", "적용 등록ID": None})
            continue
        for sid in cand["id"]:
            set_reference(db_path, int(sid), q, str(r.get("단위") or ""),
                          str(r.get("출처") or "") or f"양식 파일: {path.name}", str(r.get("메모") or ""))
        out.append({"양식 행": i + 2, "세션": name, "결과": f"적용({len(cand)}건)",
                    "적용 등록ID": ", ".join(str(int(x)) for x in cand["id"])})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- v0.4: 지점 정보 / 수위 / 소하천 목록
def save_catalog(db_path: Path, cat: pd.DataFrame, source_file: Path) -> int:
    from rsq_compare.core.catalog import store_catalog
    init_db(db_path)
    with connect(db_path) as con:
        return store_catalog(con,cat,source_file)


def catalog_df(db_path: Path) -> pd.DataFrame:
    return read_table(db_path, "SELECT * FROM site_catalog ORDER BY sido, sigungu, river_name")


def set_site_code(db_path: Path, sid: int, code: str | None, source: str = "직접 입력") -> None:
    with connect(db_path) as con:
        con.execute("UPDATE sessions SET local_site_id=NULL, site_code=?, site_code_source=? WHERE id=?",
                    (code or None, source if code else None, int(sid)))


def set_operator(db_path: Path, sid: int, name: str) -> None:
    with connect(db_path) as con:
        con.execute("UPDATE sessions SET operator=? WHERE id=?", (name or None, int(sid)))


def set_gauge_manual(db_path: Path, transect_id: int, value: float | None, obs_time: str = "", note: str = "") -> None:
    with connect(db_path) as con:
        con.execute("UPDATE transects SET gh_manual=?, gh_manual_time=?, gh_manual_note=? WHERE id=?",
                    (value, obs_time or None, note or None, int(transect_id)))


def gauge_view(tr: pd.DataFrame) -> pd.DataFrame:
    """회차별 수위: RSQ 기록이 있으면 그것을, 없으면 직접 입력을 '사용값'으로. 둘 다 있고 다르면 불일치 표시."""
    rows = []
    for _, t in tr.iterrows():
        rs = [v for v in (t.get("gh_start"), t.get("gh_end")) if v is not None and not pd.isna(v)]
        rsq = sum(rs) / len(rs) if rs else None
        man = t.get("gh_manual")
        man = None if man is None or pd.isna(man) else float(man)
        if rsq is not None:
            use, src = rsq, "RSQ 기록" + ("(시작·끝 평균)" if len(rs) == 2 else "")
        elif man is not None:
            use, src = man, "직접 입력"
        else:
            use, src = None, "없음"
        note = ""
        if rsq is not None and man is not None:
            note = "기준면 확인 전 직접 비교하지 않음"
        rows.append({"회차ID": t["id"], "등록ID": t["session_id"], "세션": t.get("session_name"), "회차": t["label"],
                     "RSQ 시작 수위": t.get("gh_start"), "RSQ 시작 관측시각": t.get("gh_start_time"),
                     "RSQ 끝 수위": t.get("gh_end"), "RSQ 끝 관측시각": t.get("gh_end_time"),
                     "직접 입력 수위": man, "직접 입력 시각": t.get("gh_manual_time"), "직접 입력 메모": t.get("gh_manual_note"),
                     "사용 수위": use, "출처": src, "수위 단위": t.get("gh_unit") or "m" if rsq is not None else t.get("gh_manual_unit") or "m",
                     "직접 입력 기준면": t.get("gh_datum") or "미확인", "직접 입력 출처": t.get("gh_source"), "비고": note})
    return pd.DataFrame(rows)
