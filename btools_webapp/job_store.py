"""Single-process background jobs; mount BTOOLS_JOB_DIR on a Render disk.

Input text and Gemini keys stay in worker memory. Interrupted jobs become failed
on restart so the Drive client can retry instead of waiting forever.
"""
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


class JobConflict(ValueError):
    pass


class QueueFull(ValueError):
    pass


class JobProcessingError(ValueError):
    """A safe, actionable message that can be returned to the Drive client."""

    def __init__(self, message, code="processing_error", diagnostics=None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics


_job_context = ContextVar("btools_job", default="direct")


def exception_diagnostics(exc, stage):
    # No exception messages, source lines, locals, absolute paths or HTTP bodies.
    files = {"app.py", "job_store.py", "reference_parser.py", "reference_renderer.py",
             "generate_course_outline.py", "source_reader.py"}
    frames = [{"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
              for f in traceback.extract_tb(exc.__traceback__) if Path(f.filename).name in files]
    return {"stage": stage, "exception_type": type(exc).__name__, "frames": frames}


def job_event(event, **fields):
    logging.getLogger("uvicorn.error").info("BTools %s", json.dumps(
        {"job_id": _job_context.get(), "event": event, **fields}, ensure_ascii=False))


@contextmanager
def job_stage(stage):
    started = time.monotonic()
    job_event("stage_started", stage=stage)
    try:
        yield
    except Exception as exc:
        info = getattr(exc, "diagnostics", None) or exception_diagnostics(exc, stage)
        job_event("stage_failed", **info)
        if isinstance(exc, JobProcessingError):
            exc.diagnostics = info
            raise
        raise JobProcessingError(
            f"{stage} failed ({type(exc).__name__}); check job diagnostics.",
            code=stage + "_error", diagnostics=info) from None
    else:
        job_event("stage_completed", stage=stage, elapsed_seconds=round(time.monotonic() - started, 2))


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
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "review_required" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0")
            if "audit_available" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN audit_available INTEGER NOT NULL DEFAULT 0")
            if "diagnostics" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN diagnostics TEXT")
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
        public = {key: row[key] for key in (
            "id", "status", "created", "updated", "filename", "model", "error"
        )}
        public.update(review_required=bool(row["review_required"]), audit_available=bool(row["audit_available"]))
        public["diagnostics"] = json.loads(row["diagnostics"]) if row["diagnostics"] else None
        return public

    def get(self, job_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._public(row) if row else None

    def result_path(self, job_id):
        # Never accept a path from the caller or from the model.
        canonical = str(uuid.UUID(job_id))
        return self.directory / (canonical + ".docx")

    def submit(self, request_id, raw_text, api_keys, render, source_document=None):
        content = raw_text if source_document is None else json.dumps(
            {"raw_text": raw_text, "source_document": source_document}, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
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
                self.executor.submit(self._run, job_id, raw_text, api_keys, render, source_document)
            except RuntimeError:
                self._update(job_id, "failed", error="Worker is shutting down; submit a new request.")
            return self.get(job_id)

    def _update(self, job_id, status, filename=None, model=None, error=None, review_required=False, audit_available=False, diagnostics=None):
        with self._connect() as db:
            db.execute("UPDATE jobs SET status=?,updated=?,filename=?,model=?,error=?,review_required=?,audit_available=?,diagnostics=? WHERE id=?",
                       (status, time.time(), filename, model, error, int(review_required), int(audit_available),
                        json.dumps(diagnostics) if diagnostics else None, job_id))

    def _run(self, job_id, raw_text, api_keys, render, source_document=None):
        context_token = _job_context.set(job_id)
        self._update(job_id, "processing")
        path = self.result_path(job_id)
        try:
            result = render(raw_text, api_keys, str(path), source_document) if source_document is not None else render(raw_text, api_keys, str(path))
            filename, model = result[:2]
            audit = result[2] if len(result) > 2 else None
            with job_stage("result_persistence"):
                if not path.is_file() or path.stat().st_size == 0:
                    raise JobProcessingError("Renderer produced no document.", code="missing_document")
                if audit is not None:
                    path.with_suffix(".audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            self._update(job_id, "succeeded", filename=filename, model=model,
                         review_required=bool(audit and audit.get("review_required")), audit_available=audit is not None)
        except Exception as exc:
            # Do not return exceptions containing Gemini request URLs/API keys.
            info = getattr(exc, "diagnostics", None) or exception_diagnostics(exc, "worker")
            info["code"] = getattr(exc, "code", "worker_error")
            job_event("job_failed", **info)
            path.unlink(missing_ok=True)
            path.with_suffix(".audit.json").unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, JobProcessingError) else f"Worker failed ({type(exc).__name__}); check job diagnostics."
            for key in api_keys.split(","):
                if key.strip():
                    message = message.replace(key.strip(), "[redacted]")
            self._update(job_id, "failed", error=message, diagnostics=info)
        finally:
            _job_context.reset(context_token)

    def cleanup(self, retention_seconds=7 * 24 * 3600):
        with self._connect() as db:
            rows = db.execute("SELECT id FROM jobs WHERE status IN ('succeeded','failed') AND updated<?",
                              (time.time() - retention_seconds,)).fetchall()
            for row in rows:
                self.result_path(row["id"]).unlink(missing_ok=True)
                self.result_path(row["id"]).with_suffix(".audit.json").unlink(missing_ok=True)
                db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))

    def close(self):
        self.executor.shutdown(wait=True)
