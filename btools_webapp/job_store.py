"""Single-process background jobs; mount BTOOLS_JOB_DIR on a Render disk.

Input text and Gemini keys stay in worker memory. Interrupted jobs become failed
on restart so the Drive client can retry instead of waiting forever.
"""
import hashlib
import logging
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path


class JobConflict(ValueError):
    pass


class QueueFull(ValueError):
    pass


class JobProcessingError(ValueError):
    """A safe, actionable message that can be returned to the Drive client."""


class JobStore:
    def __init__(self, directory, max_pending=2):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "jobs.sqlite3"
        self.max_pending = max_pending
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="course-outline")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                digest TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL,
                filename TEXT, model TEXT, error TEXT
            )""")
            db.execute("""UPDATE jobs SET status='failed', updated=?,
                error='Server restarted during processing; submit a new request.'
                WHERE status IN ('queued', 'processing')""", (time.time(),))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _public(row):
        return {key: row[key] for key in (
            "id", "status", "created", "updated", "filename", "model", "error"
        )}

    def get(self, job_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._public(row) if row else None

    def result_path(self, job_id):
        # Never accept a path from the caller or from the model.
        canonical = str(uuid.UUID(job_id))
        return self.directory / (canonical + ".docx")

    def submit(self, request_id, raw_text, api_keys, render):
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        with self.lock:
            self.cleanup()
            with self._connect() as db:
                existing = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
                if existing:
                    if existing["digest"] != digest:
                        raise JobConflict("request_id already belongs to different input")
                    return self._public(existing)
                count = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','processing')").fetchone()[0]
                if count >= self.max_pending:
                    raise QueueFull("Job queue is full; try again next trigger")
                job_id = str(uuid.uuid4())
                now = time.time()
                db.execute("INSERT INTO jobs (id,request_id,digest,status,created,updated) VALUES (?,?,?,'queued',?,?)",
                           (job_id, request_id, digest, now, now))
            try:
                self.executor.submit(self._run, job_id, raw_text, api_keys, render)
            except RuntimeError:
                self._update(job_id, "failed", error="Worker is shutting down; submit a new request.")
            return self.get(job_id)

    def _update(self, job_id, status, filename=None, model=None, error=None):
        with self._connect() as db:
            db.execute("UPDATE jobs SET status=?,updated=?,filename=?,model=?,error=? WHERE id=?",
                       (status, time.time(), filename, model, error, job_id))

    def _run(self, job_id, raw_text, api_keys, render):
        self._update(job_id, "processing")
        path = self.result_path(job_id)
        try:
            filename, model = render(raw_text, api_keys, str(path))
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("No document produced")
            self._update(job_id, "succeeded", filename=filename, model=model)
        except Exception as exc:
            # Do not return exceptions containing Gemini request URLs/API keys.
            logging.error("Course job %s failed; see formatter logs", job_id)
            path.unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, JobProcessingError) else "AI/document generation failed; check Render logs and retry."
            self._update(job_id, "failed", error=message)

    def cleanup(self, retention_seconds=7 * 24 * 3600):
        with self._connect() as db:
            rows = db.execute("SELECT id FROM jobs WHERE status IN ('succeeded','failed') AND updated<?",
                              (time.time() - retention_seconds,)).fetchall()
            for row in rows:
                self.result_path(row["id"]).unlink(missing_ok=True)
                db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))

    def close(self):
        self.executor.shutdown(wait=True)
