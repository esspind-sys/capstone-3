"""
confirmation.py -- signed confirmation tokens for Stretch Goal B.
Any edit to the SQL, question or plan invalidates the signature, so a confirmation
can only ever run the exact query that was flagged. Tokens expire after TTL_SECONDS.
Set CONFIRMATION_SECRET as a Lambda environment variable (any long random string).
"""
import hashlib
import hmac
import json
import os
import time

TTL_SECONDS = 600
_DEV_SECRET = "local-dev-only-secret"  # used only outside Lambda


def _secret() -> bytes:
    secret = os.getenv("CONFIRMATION_SECRET")
    if not secret:
        if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            raise RuntimeError("CONFIRMATION_SECRET is not set on this Lambda function")
        secret = _DEV_SECRET
    return secret.encode()


def _sign(fields: dict) -> str:
    msg = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def make_confirmation(question: str, sql: str, plan: dict, now: float | None = None) -> dict:
    fields = {"question": question, "sql": sql, "plan": plan,
              "exp": int((now if now is not None else time.time()) + TTL_SECONDS)}
    return {**fields, "token": _sign(fields)}


def verify_confirmation(conf, now: float | None = None) -> dict:
    """Return the signed fields, or raise ValueError if missing, altered or expired."""
    if not isinstance(conf, dict) or not all(k in conf for k in ("question", "sql", "plan", "exp", "token")):
        raise ValueError("confirmation must contain question, sql, plan, exp and token")
    fields = {k: conf[k] for k in ("question", "sql", "plan", "exp")}
    if not isinstance(conf["token"], str) or not hmac.compare_digest(_sign(fields), conf["token"]):
        raise ValueError("confirmation rejected: the query does not match the one that was flagged")
    if (now if now is not None else time.time()) > fields["exp"]:
        raise ValueError("confirmation expired; ask the question again")
    return fields