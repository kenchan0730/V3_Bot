"""Shared helpers for trading signal payloads."""

CONFIDENCE_MAP = {
    "HIGH": 0.85,
    "MEDIUM": 0.55,
    "MED": 0.55,
    "LOW": 0.30,
}


def parse_confidence(value, default=0.5):
    """Normalize confidence from TradingSignals (str) or tests (float/int)."""
    if value is None or value == "":
        return float(default)
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return float(default)
        upper = stripped.upper()
        if upper in CONFIDENCE_MAP:
            return CONFIDENCE_MAP[upper]
        try:
            return float(stripped)
        except ValueError:
            return float(default)
    return float(default)
