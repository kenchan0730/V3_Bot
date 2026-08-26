"""Inbox for ideas pushed in from an external app.

The bot scans on its own schedule, but the trader also finds ideas by hand. A
JSONL inbox lets any external process (a phone app, a webhook relay, a shell
script) drop a symbol with an optional headline; the bot picks it up on the next
cycle, runs the full review, and writes a verdict back to a second JSONL that
the app can poll.

Files are append-only so a crash mid-write cannot corrupt earlier entries.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_HINTS = ("BUY", "SELL", "WATCH", "REVIEW")


@dataclass
class ExternalSignal:
    id: str
    symbol: str
    source: str = "app"
    kind: str = "idea"              # idea | news | alert
    note: str = ""
    url: str = ""
    action_hint: str = "REVIEW"     # BUY | SELL | WATCH | REVIEW
    received_at: str = ""
    payload: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        symbol = str(data.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError("external signal requires a symbol")
        hint = str(data.get("action_hint", "REVIEW")).strip().upper()
        if hint not in VALID_HINTS:
            hint = "REVIEW"
        received = data.get("received_at") or datetime.now().isoformat(timespec="seconds")
        note = str(data.get("note", ""))
        signal_id = str(data.get("id") or "").strip()
        if not signal_id:
            seed = f"{symbol}|{note}|{data.get('url', '')}|{received}"
            signal_id = hashlib.sha1(seed.encode()).hexdigest()[:16]
        return cls(
            id=signal_id,
            symbol=symbol,
            source=str(data.get("source", "app")),
            kind=str(data.get("kind", "idea")),
            note=note,
            url=str(data.get("url", "")),
            action_hint=hint,
            received_at=received,
            payload=data.get("payload") or {},
        )

    @property
    def claim_text(self) -> str:
        """Text used for the credibility audit."""
        return " ".join(part for part in (self.note, self.payload.get("headline", "")) if part).strip()


class ExternalSignalInbox:
    DEFAULTS = {
        "enabled": False,
        "directory": "data/external_signals",
        "inbox_file": "inbox.jsonl",
        "verdict_file": "verdicts.jsonl",
        "processed_file": "processed.json",
        "max_per_cycle": 5,
        "max_age_hours": 48,
        "allowed_symbols": [],
    }

    def __init__(self, config=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", False))
        base = Path(cfg["directory"])
        self.inbox_path = base / cfg["inbox_file"]
        self.verdict_path = base / cfg["verdict_file"]
        self.processed_path = base / cfg["processed_file"]
        self._processed: set[str] = set()
        self._load_processed()

    # ----- state -----

    def _load_processed(self):
        if not self.processed_path.exists():
            return
        try:
            payload = json.loads(self.processed_path.read_text())
            self._processed = set(payload.get("ids", []))
        except (OSError, ValueError) as exc:
            logger.warning("外部訊號處理記錄讀取失敗: %s", exc)

    def _save_processed(self):
        try:
            self.processed_path.parent.mkdir(parents=True, exist_ok=True)
            recent = list(self._processed)[-2000:]
            self.processed_path.write_text(json.dumps({"ids": recent}, indent=2))
        except OSError as exc:
            logger.warning("外部訊號處理記錄寫入失敗: %s", exc)

    # ----- producer side (called by the app / webhook relay) -----

    def submit(self, data: dict) -> ExternalSignal:
        signal = ExternalSignal.from_dict(data)
        allowed = [s.upper() for s in (self.cfg.get("allowed_symbols") or [])]
        if allowed and signal.symbol not in allowed:
            raise ValueError(f"symbol {signal.symbol} not in allowed_symbols")
        self.inbox_path.parent.mkdir(parents=True, exist_ok=True)
        with self.inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(signal.to_dict(), ensure_ascii=False) + "\n")
        return signal

    # ----- consumer side (called by the bot) -----

    def _read_all(self):
        if not self.inbox_path.exists():
            return []
        signals = []
        try:
            lines = self.inbox_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("外部訊號讀取失敗: %s", exc)
            return []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                signals.append(ExternalSignal.from_dict(json.loads(line)))
            except (ValueError, TypeError) as exc:
                logger.warning("外部訊號格式錯誤，已略過: %s", exc)
        return signals

    def poll(self, limit=None, now=None):
        """Return unprocessed, non-stale signals (newest last)."""
        if not self.enabled:
            return []
        now = now or datetime.now()
        max_age = float(self.cfg.get("max_age_hours", 48))
        limit = int(limit or self.cfg.get("max_per_cycle", 5))

        pending = []
        for signal in self._read_all():
            if signal.id in self._processed:
                continue
            try:
                received = datetime.fromisoformat(signal.received_at)
            except (TypeError, ValueError):
                received = now
            if (now - received).total_seconds() / 3600.0 > max_age:
                self.mark_processed(signal.id, persist=False)
                continue
            pending.append(signal)
        if pending:
            self._save_processed()
        return pending[:limit]

    def mark_processed(self, signal_id, persist=True):
        self._processed.add(signal_id)
        if persist:
            self._save_processed()

    def write_verdict(self, signal: ExternalSignal, verdict: dict):
        record = {
            "signal_id": signal.id,
            "symbol": signal.symbol,
            "source": signal.source,
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
            **verdict,
        }
        try:
            self.verdict_path.parent.mkdir(parents=True, exist_ok=True)
            with self.verdict_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("外部訊號結論寫入失敗: %s", exc)
        return record

    def verdicts(self, limit=20):
        if not self.verdict_path.exists():
            return []
        try:
            lines = self.verdict_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
