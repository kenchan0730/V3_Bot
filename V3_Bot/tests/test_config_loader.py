import pytest

from core.config_loader import load_config, load_dotenv


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_expands_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_PORT", "4002")
    config_path = write(tmp_path, "config.yaml", "ibkr:\n  port: ${TEST_PORT}\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["ibkr"]["port"] == 4002


def test_uses_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("ABSENT_VAR", raising=False)
    config_path = write(tmp_path, "config.yaml", "capital:\n  total: ${ABSENT_VAR:-385.0}\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["capital"]["total"] == 385.0


def test_env_overrides_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CAP", "999")
    config_path = write(tmp_path, "config.yaml", "capital:\n  total: ${CAP:-385.0}\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["capital"]["total"] == 999


def test_missing_var_without_default_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("NO_SUCH_KEY", raising=False)
    config_path = write(tmp_path, "config.yaml", "news:\n  finnhub_key: ${NO_SUCH_KEY}\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["news"]["finnhub_key"] == ""


def test_boolean_coercion(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAG", "true")
    config_path = write(tmp_path, "config.yaml", "trading:\n  auto_trade: ${FLAG}\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["trading"]["auto_trade"] is True


def test_expansion_inside_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SYM", "AVAH")
    config_path = write(tmp_path, "config.yaml", "watchlist:\n  - ${SYM}\n  - QXO\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["watchlist"] == ["AVAH", "QXO"]


def test_plain_values_untouched(tmp_path):
    config_path = write(tmp_path, "config.yaml", "risk:\n  max_risk_percent: 2.0\n  label: hello\n")
    config = load_config(config_path, env_path=str(tmp_path / "missing.env"))
    assert config["risk"]["max_risk_percent"] == 2.0
    assert config["risk"]["label"] == "hello"


def test_empty_config_returns_dict(tmp_path):
    config_path = write(tmp_path, "config.yaml", "")
    assert load_config(config_path, env_path=str(tmp_path / "missing.env")) == {}


def test_load_dotenv_reads_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTENV_SAMPLE", raising=False)
    env_path = write(tmp_path, ".env", "# comment\nDOTENV_SAMPLE=hello\nBAD_LINE\n")
    load_dotenv(env_path)
    import os

    assert os.environ.get("DOTENV_SAMPLE") == "hello"


def test_load_dotenv_missing_file(tmp_path):
    assert load_dotenv(str(tmp_path / "nope.env")) in (False, True)
