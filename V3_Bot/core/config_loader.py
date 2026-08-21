"""Configuration loading with .env support and ${VAR} expansion."""

import os
import re
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def load_dotenv(path=".env"):
    """Minimal .env loader. Uses python-dotenv when available, else parses manually."""
    try:
        from dotenv import load_dotenv as _load

        _load(path)
        return True
    except ImportError:
        pass

    env_file = Path(path)
    if not env_file.exists():
        return False
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return True


def _expand(value):
    """Replace ${VAR} / ${VAR:-default} with environment values."""
    if not isinstance(value, str):
        return value

    def repl(match):
        name, default = match.group(1), match.group(2)
        env_value = os.environ.get(name)
        if env_value not in (None, ""):
            return env_value
        if default is not None:
            return default
        logger.warning(f"環境變數 {name} 未設定，替換為空值")
        return ""

    expanded = _VAR_PATTERN.sub(repl, value)
    return _coerce(expanded) if expanded != value else value


def _coerce(text):
    """Convert expanded strings back to int/float/bool where unambiguous."""
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    for caster in (int, float):
        try:
            return caster(text)
        except (TypeError, ValueError):
            continue
    return text


def _walk(node):
    if isinstance(node, dict):
        return {key: _walk(val) for key, val in node.items()}
    if isinstance(node, list):
        return [_walk(item) for item in node]
    return _expand(node)


def load_config(path="config.yaml", env_path=".env"):
    """Load YAML config, expanding ${VAR} placeholders from the environment."""
    load_dotenv(env_path)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return _walk(raw)
