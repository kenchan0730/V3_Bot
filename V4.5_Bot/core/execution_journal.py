"""Post-trade execution journal — decision environment + execution score."""

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_FIELDS = [
    "timestamp_utc",
    "timestamp_local",
    "symbol",
    "action",
    "decision",
    "execution_score",
    "regime",
    "breadth_score",
    "vix",
    "exposure_pct",
    "market_structure",
    "macro_event",
    "deliberation",
    "emotion_state",
    "holding_days",
    "tax_bucket",
    "realized_pnl",
    "notes",
]


class ExecutionJournal:
    """Append-only professional post-mortem log (separate from trade blotter)."""

    def __init__(self, path="data/execution_journal.csv"):
        self.path = Path(path)
        self._ensure_header()

    def _ensure_header(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists() or self.path.stat().st_size == 0:
                with open(self.path, "a", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=JOURNAL_FIELDS).writeheader()
        except Exception as exc:
            logger.error(f"Journal init failed: {exc}")

    def record(self, **row):
        payload = {k: "" for k in JOURNAL_FIELDS}
        now = datetime.now(timezone.utc)
        payload["timestamp_utc"] = now.isoformat(timespec="seconds")
        payload["timestamp_local"] = datetime.now().isoformat(timespec="seconds")
        for key, value in row.items():
            if key in payload:
                payload[key] = value
        try:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=JOURNAL_FIELDS).writerow(payload)
                f.flush()
                os.fsync(f.fileno())
        except Exception as exc:
            logger.error(f"Journal write failed: {exc}")

    def log_decision(self, symbol, decision, deliberation, context=None, execution_score=""):
        ctx = context or {}
        self.record(
            symbol=symbol,
            action=ctx.get("action", ""),
            decision=decision,
            execution_score=execution_score,
            regime=ctx.get("regime", ""),
            breadth_score=ctx.get("breadth_score", ""),
            vix=ctx.get("vix", ""),
            exposure_pct=ctx.get("exposure_pct", ""),
            market_structure=ctx.get("market_structure", ""),
            macro_event=ctx.get("macro_event", ""),
            deliberation=" | ".join(deliberation) if isinstance(deliberation, list) else deliberation,
            emotion_state=ctx.get("emotion_state", ""),
            notes=ctx.get("notes", ""),
        )

    @staticmethod
    def tax_bucket(holding_days):
        if holding_days is None:
            return ""
        return "long_term" if holding_days > 365 else "short_term"
