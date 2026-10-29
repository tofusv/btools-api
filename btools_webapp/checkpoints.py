"""Signed recovery data: no provider keys or credentials are written to disk."""
import hashlib
import hmac
import json
import os
import re

from job_store import JobProcessingError


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def source_digest(raw_text, source_document):
    return hashlib.sha256(canonical([raw_text, source_document]).encode()).hexdigest()


def signature(body):
    secret = os.environ.get("BTOOLS_API_TOKEN", "")
    if not secret:
        raise JobProcessingError("Recovery signing key is not configured.", code="configuration_error")
    return hmac.new(secret.encode(), canonical(body).encode(), hashlib.sha256).hexdigest()


def make_checkpoint(raw_text, source_document, data):
    body = {"version": 1, "source_digest": source_digest(raw_text, source_document), "data": data}
    return {"body": body, "signature": signature(body)}


def restore_checkpoint(checkpoint, raw_text, source_document):
    body = checkpoint.get("body")
    supplied = checkpoint.get("signature")
    if (not isinstance(body, dict) or body.get("version") != 1
            or not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied)
            or not hmac.compare_digest(signature(body), supplied)
            or body.get("source_digest") != source_digest(raw_text, source_document)
            or not isinstance(body.get("data"), dict)):
        raise JobProcessingError("Recovery data does not match this source or server key.", code="invalid_checkpoint")
    return body["data"]
