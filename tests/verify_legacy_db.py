"""이전 DB의 임시 복사본만 이관하고 기존 열/행·외래키 보존을 검증한다.
python tests/verify_legacy_db.py <private old database>
"""
import hashlib
from contextlib import closing
import sqlite3
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rsq_compare.core import db


def main():
    source=Path(sys.argv[1]);before=hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        copy=Path(tmp)/'old.db'
        # WAL 포함 일관된 스냅샷을 읽기 전용 원본 연결에서 만든다.
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src, src,closing(sqlite3.connect(copy)) as dst, dst:
            src.backup(dst)
        with closing(sqlite3.connect(copy)) as con, con:
            tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            snapshots={}
            for t in tables:
                cols=[r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
                # meta의 버전 표시만 바뀌며 나머지 원래 값은 유지되어야 한다.
                rows=con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                snapshots[t]=(cols,[r for r in rows if not(t=='meta' and r[0]=='schema_version')])
        db.init_db(copy);db.init_db(copy)
        with closing(sqlite3.connect(copy)) as con, con:
            for t,(cols,old) in snapshots.items():
                fields=','.join('"'+c+'"' for c in cols)
                new=con.execute(f'SELECT {fields} FROM "{t}" ORDER BY rowid').fetchall()
                if t=='meta':
                    oldkeys={r[0] for r in old};new=[r for r in new if r[0] in oldkeys]
                assert new==old, f'기존 자료 변경: {t}'
            assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert list(copy.parent.glob('*.bak')),'이관 전 전체 백업이 없습니다.'
        print(f'PASS 이전 DB {len(tables)}개 테이블의 기존 열/행 보존, 반복 이관, 전체 백업, 외래키/무결성')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    print('PASS 원본 DB SHA-256 불변(임시 복사본만 이관)')


if __name__=='__main__':main()
