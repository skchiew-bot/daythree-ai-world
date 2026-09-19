"""T3 test layer 7: repository assertions for the twin-hook deliverables.

The gitignore covers the state directory and the key path; no key-shaped token, real path,
user name, prompt, e-mail or common secret format sits in any tracked hook fixture; the
script keeps its structural safety properties; and `.claude/settings.local.json.example`
carries the six hooks in PR #13's Windows-safe shape with the Read deny rule for the key.
Text-only checks: nothing here runs bash, so this file needs no shell.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "report_twin_lifecycle.sh"
SETTINGS_EXAMPLE = REPO / ".claude" / "settings.local.json.example"
KEY_EXAMPLE = REPO / ".claude" / "twin_env.sh.example"
HOOKS_TESTS = Path(__file__).resolve().parent

pytestmark = pytest.mark.unit

_needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Ignore rules and secret-shaped content
# ---------------------------------------------------------------------------


@_needs_git
@pytest.mark.parametrize("path", [".hook-debug/x.json", ".hook-debug/twin-state/x", ".claude/twin_env.sh"])
def test_gitignore_covers_the_state_directory_and_the_key_path(path):
    result = _git("check-ignore", "-v", path)

    assert result.returncode == 0, result.stderr
    assert ".gitignore" in result.stdout


@_needs_git
def test_no_key_shaped_token_sits_in_any_tracked_or_untracked_file():
    key_shape = r"dtk_[0-9a-f]{32}_[A-Za-z0-9_-]{16,}"

    result = _git("grep", "-I", "-n", "--untracked", "-E", key_shape)

    assert result.returncode == 1, f"a key-shaped token is in the repo: {result.stdout.splitlines()[:1]}"


_FORBIDDEN_IN_FIXTURES = {
    "a Windows user path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]"),
    "a macOS home path": re.compile(r"/Users/"),
    "a Linux home path": re.compile(r"/home/"),
    "a transcript file": re.compile(r"\.jsonl"),
    "a literal UUID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I),
    "an e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "an API key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "a GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "an AWS key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "a JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    "a key-shaped token": re.compile(r"dtk_[0-9a-f]{32}_"),
}


def _fixture_files() -> list[Path]:
    files = [p for p in HOOKS_TESTS.glob("*.py") if p.name != Path(__file__).name]
    return files + [SCRIPT, KEY_EXAMPLE, SETTINGS_EXAMPLE, REPO / "tests" / "e2e" / "test_twin_hooks_e2e.py"]


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_hook_files_and_fixtures_hold_no_real_looking_data(path):
    text = path.read_text(encoding="utf-8")

    hits = [label for label, pattern in _FORBIDDEN_IN_FIXTURES.items() if pattern.search(text)]

    assert hits == [], f"{path.name} contains {hits}"


# ---------------------------------------------------------------------------
# Script structure (data-warden D32..D36, gatekeeper T3-F6..F9, F14)
# ---------------------------------------------------------------------------

_SCRIPT_TEXT = SCRIPT.read_text(encoding="utf-8")
_CODE_LINES = [line for line in _SCRIPT_TEXT.splitlines() if not line.lstrip().startswith("#")]
_CODE_TEXT = "\n".join(_CODE_LINES)


@pytest.mark.parametrize(
    "pattern",
    [r"\beval\b", r"\bset\s+-[a-zA-Z]*[ex]", r"\bset\s+-o\b", r"\bjq\b", r"\bpython3?\b", r"\bnode\b", r"\bperl\b",
     r"\bsource\s+/dev", r"/dev/tcp", r"\bnc\b", r"\bwget\b"],
)
def test_the_script_uses_no_forbidden_construct(pattern):
    assert re.search(pattern, _CODE_TEXT) is None


def test_the_script_silences_itself_and_always_exits_zero():
    assert _SCRIPT_TEXT.count("exec >/dev/null 2>&1") == 1
    assert "trap 'exit 0' EXIT" in _SCRIPT_TEXT
    assert not re.search(r"\bexit\s+[1-9]", _CODE_TEXT)
    assert not re.search(r"\becho\b", _CODE_TEXT)  # nothing can print by accident


def test_the_script_never_exports_or_echoes_the_key_and_never_writes_the_payload():
    assert not re.search(r"\bexport\b", _CODE_TEXT)
    assert not re.search(r"<<<", _CODE_TEXT)  # a here-string can spill a large payload to a temp file
    assert "-H " not in _CODE_TEXT and "--header" not in _CODE_TEXT  # headers travel in the stdin config
    assert '"$KEY"' in _CODE_TEXT and "-K -" in _CODE_TEXT


def test_the_transport_flags_are_pinned():
    for flag in ("--connect-timeout 1", "--max-time 2", "--max-redirs 0", "--proto '=http,https'", "%{http_code}", "--noproxy '*'"):
        assert flag in _CODE_TEXT
    assert "read -r -t 2" in _CODE_TEXT


def test_the_key_file_location_is_fixed_and_outside_the_repo_and_the_payload_never_names_a_path():
    assert '"$HOME_DIR/.daythree/twin_env.sh"' in _CODE_TEXT
    assert "KEY_FILE=" in _CODE_TEXT and _CODE_TEXT.count("KEY_FILE=") == 1


def test_the_script_reads_only_the_documented_payload_fields():
    extracted = set(re.findall(r'extract_from "[^"]*" (\w+)', _CODE_TEXT))

    assert extracted == {"hook_event_name", "session_id", "source", "reason", "agent_id", "agent_type", "id"}
    for never in ("prompt", "cwd", "transcript_path", "last_assistant_message", "tool_input", "tool_result"):
        assert not re.search(rf'extract_from "[^"]*" {never}\b', _CODE_TEXT)
    assert "tool_call_count" not in _CODE_TEXT


# ---------------------------------------------------------------------------
# Settings example and key-file example
# ---------------------------------------------------------------------------

_TWIN_EVENTS = ["SessionStart", "SubagentStart", "SubagentStop", "SessionEnd", "Stop", "UserPromptSubmit"]
_settings = json.loads(SETTINGS_EXAMPLE.read_text(encoding="utf-8"))


def _twin_commands(event: str) -> list[dict]:
    return [
        hook
        for group in _settings["hooks"][event]
        for hook in group["hooks"]
        if "report_twin_lifecycle.sh" in hook["command"]
    ]


@pytest.mark.parametrize("event", _TWIN_EVENTS)
def test_each_of_the_six_events_runs_the_twin_script_in_the_windows_safe_shape(event):
    (hook,) = _twin_commands(event)

    command = hook["command"]
    assert command.startswith('"C:\\Program Files\\Git\\usr\\bin\\bash.exe" --login "')  # fully qualified, never bare bash
    assert command.endswith(f'/scripts/report_twin_lifecycle.sh" {event}')
    assert "&" not in command and "|" not in command and ";" not in command  # no backgrounding, no chaining
    assert not re.match(r"^\s*\w+=", command) and " KEY" not in command and "dtk_" not in command
    assert hook["timeout"] == 5 and hook["type"] == "command"


def test_the_existing_presence_hooks_are_kept():
    for event, script in (("UserPromptSubmit", "hook_working.sh"), ("Stop", "hook_stop.sh")):
        commands = [h["command"] for group in _settings["hooks"][event] for h in group["hooks"]]
        assert any(script in command for command in commands)


def test_a_read_deny_rule_covers_the_key_path():
    assert "Read(~/.daythree/**)" in _settings["permissions"]["deny"]


def test_the_key_example_has_placeholders_only_and_the_operator_instructions():
    text = KEY_EXAMPLE.read_text(encoding="utf-8")

    assert "DAYTHREE_TWIN_BASE_URL=" in text and "DAYTHREE_TWIN_KEY=" in text
    assert re.search(r"DAYTHREE_TWIN_KEY=PASTE\w*", text)
    assert "dtk_" not in text
    for required in ("icacls", "--expires-in-days 90", "OUTSIDE Claude Code", "--revoke", ".daythree/twin_env.sh"):
        assert required in text


@pytest.mark.parametrize("name", ["hook_working.sh.example", "hook_stop.sh.example"])
def test_the_presence_scripts_are_relabelled_legacy(name):
    text = (REPO / ".claude" / name).read_text(encoding="utf-8")

    assert re.search(r"legacy", text, re.I) and re.search(r"presence", text, re.I)
    assert "report_twin_lifecycle.sh" in text
