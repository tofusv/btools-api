"""One disposable process per job, so a stalled renderer cannot block the queue."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys


def run_isolated(raw_text, api_keys, output_path, source_document, options, timeout=1500):
    from job_store import JobProcessingError
    payload = {"raw_text": raw_text, "api_keys": api_keys, "output_path": output_path,
               "source_document": source_document, "options": options}
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        output, _ = process.communicate(json.dumps(payload), timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()  # Reap BEFORE freeing the queue slot or allowing a retry.
        raise JobProcessingError("Worker exceeded its time limit and was stopped.", code="worker_timeout") from None
    except BaseException:
        process.kill()
        process.communicate()
        raise
    if process.returncode:
        raise JobProcessingError("Worker exited before producing a result.", code="worker_exit")
    try:
        message = json.loads(output)
    except ValueError:
        raise JobProcessingError("Worker returned an invalid result.", code="worker_protocol") from None
    if "error" in message:
        error = message["error"]
        raise JobProcessingError(error["message"], code=error["code"], diagnostics=error["diagnostics"])
    return message["result"]


def main():
    from app import render_background_job
    from job_store import JobProcessingError, exception_diagnostics
    payload = json.load(sys.stdin)
    try:
        # Libraries can print document content; never forward it to service logs.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = render_background_job(payload["raw_text"], payload["api_keys"],
                payload["output_path"], payload["source_document"], **payload["options"])
        message = {"result": result}
    except Exception as exc:
        message = {"error": {"message": str(exc) if isinstance(exc, JobProcessingError) else "Worker processing failed.",
                             "code": getattr(exc, "code", "worker_error"),
                             "diagnostics": getattr(exc, "diagnostics", None) or exception_diagnostics(exc, "worker")}}
    encoded = json.dumps(message)
    for key in payload["api_keys"].split(","):
        if key.strip():
            encoded = encoded.replace(key.strip(), "[redacted]")
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
