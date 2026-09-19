"""T3 deliverable 5 / T3-F18: `--expires-in-days` on `issue_agent_runtime_key.py`.

Pure CLI-wiring tests (no database): `issue` is replaced with a recorder, so what is
asserted is exactly what `main()` hands it. The database half (the stored `expires_at`)
lives in `tests/security/test_agent_runtime_key_expiry.py`. The script is loaded by
file path because `infrastructure/scripts/` is a plain directory and the repo root is
not on pytest's `pythonpath`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "infrastructure" / "scripts" / "issue_agent_runtime_key.py"
_SENTINEL = "dtk_" + ("0" * 32) + "_placeholder-not-a-real-secret"


def _load():
    name = "issue_agent_runtime_key"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch):
    from common.config import Settings

    module = _load()
    calls: list[dict] = []

    async def _recorder(tenant_code, **kwargs):
        calls.append({"tenant_code": tenant_code, **kwargs})
        return _SENTINEL

    monkeypatch.setattr(module, "issue", _recorder)
    monkeypatch.setattr(module, "get_settings", lambda: Settings())  # database_url defaults to localhost
    module._calls = calls
    return module


def _run(script, monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["issue_agent_runtime_key.py", *argv])
    script.main()


def test_expires_in_days_is_passed_through_to_issue(script, monkeypatch, capsys):
    _run(script, monkeypatch, "--tenant-code", "daythree-hq", "--expires-in-days", "90")

    assert script._calls == [
        {"tenant_code": "daythree-hq", "label": "issued via issue_agent_runtime_key.py", "expires_in_days": 90}
    ]
    assert capsys.readouterr().out.strip() == _SENTINEL  # print-once behaviour is unchanged


def test_without_the_flag_no_expiry_is_requested(script, monkeypatch):
    _run(script, monkeypatch, "--tenant-code", "daythree-hq")

    assert "expires_in_days" not in script._calls[0]


@pytest.mark.parametrize("value", ["0", "-1", "3651", "abc", "1.5", ""])
def test_a_non_positive_or_absurd_expiry_is_refused_before_any_key_is_issued(script, monkeypatch, capsys, value):
    with pytest.raises(SystemExit) as excinfo:
        _run(script, monkeypatch, "--tenant-code", "daythree-hq", "--expires-in-days", value)

    assert excinfo.value.code == 2
    assert script._calls == []
    assert _SENTINEL not in capsys.readouterr().out


def test_the_local_only_guard_still_applies_with_an_expiry(script, monkeypatch, capsys):
    from common.config import Settings

    remote = Settings(database_url="postgresql+asyncpg://u:p@db.example.invalid:5432/x")
    monkeypatch.setattr(script, "get_settings", lambda: remote)

    with pytest.raises(SystemExit) as excinfo:
        _run(script, monkeypatch, "--tenant-code", "daythree-hq", "--expires-in-days", "90")

    assert excinfo.value.code == 2
    assert script._calls == []
    assert _SENTINEL not in capsys.readouterr().out
