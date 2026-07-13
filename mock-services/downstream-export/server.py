from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer


class ExportHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/exports":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mode = self.headers.get("X-Mock-Export-Mode", "success")
        if mode == "timeout":
            time.sleep(3)
        status = {
            "success": HTTPStatus.ACCEPTED,
            "timeout": HTTPStatus.GATEWAY_TIMEOUT,
            "rate_limit": HTTPStatus.TOO_MANY_REQUESTS,
            "permanent_failure": HTTPStatus.UNPROCESSABLE_ENTITY,
        }.get(mode, HTTPStatus.BAD_REQUEST)
        body = json.dumps({"mode": mode, "accepted": status == HTTPStatus.ACCEPTED}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9010), ExportHandler).serve_forever()
