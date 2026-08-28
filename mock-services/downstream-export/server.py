from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock


class ExportHandler(BaseHTTPRequestHandler):
    attempts: dict[str, int] = {}
    accepted: set[str] = set()
    state_lock = Lock()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/exports":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mode = self.headers.get("X-Mock-Export-Mode", "success")
        idempotency_key = self.headers.get("Idempotency-Key", "missing-key")
        signature = self.headers.get("X-Signature", "missing-signature")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except (ValueError, json.JSONDecodeError):
            body = {}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        expected = hmac.new(
            os.getenv("DOWNSTREAM_HMAC_SECRET", "local-development-only").encode(),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        supplied = signature.removeprefix("sha256=")
        if not hmac.compare_digest(supplied, expected):
            self._respond(
                HTTPStatus.UNAUTHORIZED,
                {"accepted": False, "signature_valid": False, "error": "invalid signature"},
            )
            return
        with self.state_lock:
            if idempotency_key in self.accepted:
                self._respond(HTTPStatus.ACCEPTED, {"mode": "idempotent-replay", "accepted": True, "duplicate": False, "record_id": f"downstream-{idempotency_key[:12]}", "signature": signature, "signature_valid": True})
                return
            self.attempts[idempotency_key] = self.attempts.get(idempotency_key, 0) + 1
            attempt = self.attempts[idempotency_key]
        if mode == "first_attempt_rate_limit" and attempt == 1:
            self._respond(HTTPStatus.TOO_MANY_REQUESTS, {"mode": mode, "accepted": False, "retryable": True, "attempt": attempt, "signature": signature, "signature_valid": True})
            return
        if mode == "timeout":
            time.sleep(3)
        status = {
            "success": HTTPStatus.ACCEPTED,
            "timeout": HTTPStatus.GATEWAY_TIMEOUT,
            "rate_limit": HTTPStatus.TOO_MANY_REQUESTS,
            "permanent_failure": HTTPStatus.UNPROCESSABLE_ENTITY,
        }.get(mode, HTTPStatus.BAD_REQUEST)
        accepted = status == HTTPStatus.ACCEPTED
        if accepted:
            with self.state_lock:
                self.accepted.add(idempotency_key)
        self._respond(status, {"mode": mode, "accepted": accepted, "attempt": attempt, "duplicate": False, "record_id": f"downstream-{idempotency_key[:12]}" if accepted else None, "signature": signature, "signature_valid": True, "case_id": body.get("case_id")})

    def _respond(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "9010"))), ExportHandler).serve_forever()
