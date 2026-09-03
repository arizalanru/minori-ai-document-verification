from contextlib import contextmanager
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS applications(
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
 profile_json TEXT NOT NULL, active_evaluation_id TEXT, confirmed_evaluation_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 document_type TEXT NOT NULL, active_version_id TEXT, UNIQUE(application_id,document_type));
CREATE TABLE IF NOT EXISTS versions(
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 number INTEGER NOT NULL, file_key TEXT NOT NULL, content_hash TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'uploaded', active_run_id TEXT,
 corrections_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, UNIQUE(document_id,number));
CREATE TABLE IF NOT EXISTS process_runs(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 status TEXT NOT NULL, input_revision INTEGER NOT NULL, metadata_json TEXT NOT NULL,
 blocks_json TEXT, fields_json TEXT, error_code TEXT, started_at TEXT NOT NULL, finished_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_running ON process_runs(version_id) WHERE status='RUNNING';
CREATE TABLE IF NOT EXISTS evaluations(
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id), input_revision INTEGER NOT NULL,
 profile_json TEXT NOT NULL,snapshot_json TEXT NOT NULL,results_json TEXT NOT NULL,outcome TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),version_id TEXT,evaluation_id TEXT,
 actor_id TEXT NOT NULL,action_type TEXT NOT NULL,detail_json TEXT NOT NULL,reason TEXT NOT NULL,
 resulting_revision INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS request_keys(
 scope TEXT NOT NULL,request_key TEXT NOT NULL,payload_hash TEXT NOT NULL,response_json TEXT NOT NULL,
 PRIMARY KEY(scope,request_key));
"""


class Database:
    def __init__(self, path):
        self.path = path

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise RuntimeError("Versi database tidak didukung")
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA user_version=1")
            connection.execute(
                "UPDATE process_runs SET status='FAILED', "
                "error_code='PROCESS_INTERRUPTED' WHERE status='RUNNING'"
            )

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
