"""GC 시점과 무관하게 SQLite 연결이 범위 종료 전에 닫히는지 검증한다."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from rsq_compare.core import db

RAW_CONNECT = sqlite3.connect


class TrackedConnection(sqlite3.Connection):
    closed = False
    fail_pragma = False

    def close(self):
        super().close()
        self.closed = True

    def execute(self, sql, *args, **kwargs):
        if self.fail_pragma and sql == 'PRAGMA foreign_keys = ON':
            raise sqlite3.OperationalError('injected pragma failure')
        return super().execute(sql, *args, **kwargs)


class SqliteLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'private.db'
        # 강한 참조를 유지해 GC가 누수를 우연히 감추지 못하게 한다.
        self.connections = []
        self.fail_pragma = False

    def tearDown(self):
        # 실패한 회귀 검증 자체가 Windows에서 추가 삭제 오류를 만들지 않게 한다.
        # 누수 여부는 아래 assert_all_closed에서 먼저 엄격히 검사한다.
        for con in self.connections:
            if not con.closed:
                con.close()
        self.temp.cleanup()

    def track_connect(self, *args, **kwargs):
        kwargs['factory'] = TrackedConnection
        con = RAW_CONNECT(*args, **kwargs)
        con.fail_pragma = self.fail_pragma
        self.connections.append(con)
        return con

    def assert_all_closed(self):
        self.assertTrue(self.connections)
        self.assertEqual(sum(not c.closed for c in self.connections), 0,
                         '범위를 벗어난 SQLite 연결이 남아 있습니다.')
        for con in self.connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                con.execute('SELECT 1')
        # Windows에서도 테스트 본문에서 실제 삭제가 가능해야 한다.
        for p in self.root.iterdir():
            p.unlink()

    def test_current_database_repeated_initialization_closes_early_return_connections(self):
        db.init_db(self.path)
        with patch('sqlite3.connect', self.track_connect):
            db.init_db(self.path)
            db.init_db(self.path)
        self.assert_all_closed()

    def test_upgrade_closes_source_and_backup_and_preserves_database(self):
        schema = db.SCHEMA.replace('    memo TEXT\n);',
                                  '    memo TEXT, UNIQUE(session_name, dis_sha256)\n);', 1)
        with closing(RAW_CONNECT(self.path)) as con, con:
            con.executescript(schema)
            con.execute("INSERT INTO sessions(id,session_name,dis_sha256,memo) VALUES(42,'가상','hash','보존')")
            con.execute("INSERT INTO reference_q(session_id,ref_q) VALUES(42,3.25)")
        with patch('sqlite3.connect', self.track_connect):
            db.init_db(self.path)
        with closing(RAW_CONNECT(self.path)) as con:
            self.assertEqual(con.execute('SELECT id,memo FROM sessions').fetchall(), [(42, '보존')])
            self.assertEqual(con.execute('SELECT ref_q FROM reference_q').fetchall(), [(3.25,)])
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        backups = list(self.root.glob('*.bak'))
        self.assertTrue(backups)
        for backup in backups:
            with closing(RAW_CONNECT(backup)) as con:
                self.assertEqual(con.execute('SELECT memo FROM sessions').fetchone()[0], '보존')
        self.assert_all_closed()

    def test_application_transaction_commit_rollback_and_close(self):
        with patch('sqlite3.connect', self.track_connect):
            with db.connect(self.path) as con:
                con.execute('CREATE TABLE sample(value INTEGER)')
                con.execute('INSERT INTO sample VALUES(0)')
            with self.assertRaisesRegex(ValueError, 'rollback'):
                with db.connect(self.path) as con:
                    con.execute('INSERT INTO sample VALUES(99)')
                    raise ValueError('rollback')
        with closing(RAW_CONNECT(self.path)) as con:
            self.assertEqual(con.execute('SELECT value FROM sample').fetchall(), [(0,)])
        self.assert_all_closed()

    def test_connection_closes_when_initialization_pragma_fails(self):
        self.fail_pragma = True
        with patch('sqlite3.connect', self.track_connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'injected'):
                with db.connect(self.path):
                    self.fail('연결 초기화 오류가 무시됐습니다.')
        self.assert_all_closed()


if __name__ == '__main__':
    unittest.main()
