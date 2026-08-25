#!/usr/bin/env python3
"""Minimal HTTP bridge between a phone/finance app and the bot's signal inbox.

Runs on the stdlib only — no extra dependency, no framework. It writes into the
same JSONL inbox the bot polls, so the bot needs no network access to the app.

    python scripts/signal_server.py --port 8787

    curl -X POST http://127.0.0.1:8787/signals \
         -H "X-Api-Token: $SIGNAL_API_TOKEN" \
         -d '{"symbol":"AVAH","note":"Q3 beat, raised guidance","action_hint":"REVIEW"}'

    curl http://127.0.0.1:8787/verdicts -H "X-Api-Token: $SIGNAL_API_TOKEN"

Bind to 127.0.0.1 and reach it through an SSH tunnel or Tailscale; this server
does TLS-less token auth only and is not meant to face the open internet.
"""

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config_loader import load_config
from core.external_signals import ExternalSignalInbox

logger = logging.getLogger("signal_server")

MAX_BODY_BYTES = 64 * 1024


def build_handler(inbox, token):
    class Handler(BaseHTTPRequestHandler):
        server_version = "V45SignalBridge/1.0"

        def _authorized(self):
            if not token:
                return True
            supplied = self.headers.get("X-Api-Token") or ""
            return supplied == token

        def _respond(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/health"):
                self._respond(200, {"ok": True, "enabled": inbox.enabled})
                return
            if not self._authorized():
                self._respond(401, {"error": "unauthorized"})
                return
            if self.path.startswith("/verdicts"):
                self._respond(200, {"verdicts": inbox.verdicts(limit=20)})
                return
            self._respond(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                self._respond(401, {"error": "unauthorized"})
                return
            if not self.path.startswith("/signals"):
                self._respond(404, {"error": "not found"})
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                self._respond(400, {"error": "invalid content length"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                self._respond(400, {"error": f"invalid json: {exc}"})
                return

            try:
                signal = inbox.submit(payload)
            except ValueError as exc:
                self._respond(422, {"error": str(exc)})
                return

            logger.info("queued %s from %s", signal.symbol, signal.source)
            self._respond(202, {"queued": True, "id": signal.id, "symbol": signal.symbol})

        def log_message(self, fmt, *args):
            logger.debug(fmt, *args)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description="外部訊號 HTTP 橋接")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default="data/.env")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    config = load_config(args.config, args.env)
    ext_cfg = dict(config.get("external_signals", {}) or {})
    # The bridge must accept submissions even when the bot has polling disabled.
    ext_cfg["enabled"] = True
    inbox = ExternalSignalInbox(ext_cfg)

    token = ext_cfg.get("api_token") or os.environ.get("SIGNAL_API_TOKEN", "")
    if not token:
        logger.warning("未設定 api_token — 任何本機程序都可提交訊號")

    server = ThreadingHTTPServer((args.host, args.port), build_handler(inbox, token))
    logger.info("訊號橋接啟動於 http://%s:%d (inbox=%s)", args.host, args.port, inbox.inbox_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("關閉中…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
