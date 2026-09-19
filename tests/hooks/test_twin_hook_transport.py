"""T3 test layer 5-6: the real transport of `scripts/report_twin_lifecycle.sh`.

Response table against a stub of the agent-runtime routes on 127.0.0.1 (real curl, real
config), the ended-parent recovery that must re-register exactly once and never loop, and
key hygiene: a `curl` shim records argv, environment and stdin, and the key must appear on
stdin only. The key used here is generated at run time; nothing real is read or sent.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import uuid

import pytest

from twin_hook_harness import BASH, SESSIONS, Hook, Stub, new_agent_id, new_session_id, payload_bytes

pytestmark = [pytest.mark.unit, pytest.mark.skipif(BASH is None, reason="bash is not available")]

RUNTIME_ID = str(uuid.uuid4())  # generated at run time: no literal UUID in the file
NEW_RUNTIME_ID = str(uuid.uuid4())
CREATED = (201, json.dumps({"id": RUNTIME_ID}))


@pytest.fixture
def stub():
    server = Stub().start()
    yield server
    server.stop()


@pytest.fixture
def live(tmp_path, stub) -> Hook:
    hook = Hook(tmp_path, dry_run=False)
    hook.key = hook.write_key_file(stub.base_url)
    return hook


def _register(hook: Hook, stub: Stub, session_id: str) -> str:
    stub.on("POST", SESSIONS, CREATED)
    hook.fire("SessionStart", session_id, source="startup")
    return hook.state(session_id)[0]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# Routes, methods, headers
# ---------------------------------------------------------------------------


def test_the_full_lifecycle_uses_the_expected_routes_methods_headers_and_bodies(live, stub):
    session_id, agent_id = new_session_id(), new_agent_id()
    stub.on("POST", SESSIONS, CREATED)
    stub.on("POST", _CLOSE_PATH.format(ref=agent_id), (200, "{}"))
    stub.on("PATCH", f"{SESSIONS}/{RUNTIME_ID}", (200, "{}"))

    live.fire("SessionStart", session_id, source="startup")
    run = live.state(session_id)[0]
    live.fire("SubagentStart", session_id, agent_id=agent_id, agent_type="planner")
    live.put_state(session_id, run, RUNTIME_ID, 0)
    live.fire("Stop", session_id)
    live.fire("SubagentStop", session_id, agent_id=agent_id)
    live.fire("SessionEnd", session_id, reason="logout")

    seen = stub.seen
    assert [(r["method"], r["path"]) for r in seen] == [
        ("POST", SESSIONS), ("POST", SESSIONS), ("PATCH", f"{SESSIONS}/{RUNTIME_ID}"),
        ("POST", f"/api/v1/agent-runtime/subagents/{agent_id}/close"), ("PATCH", f"{SESSIONS}/{RUNTIME_ID}"),
    ]
    assert all(r["headers"]["Authorization"] == f"Bearer {live.key}" for r in seen)
    assert all(r["headers"]["Content-Type"] == "application/json" for r in seen)
    assert json.loads(seen[0]["body"]) == {"kind": "session", "external_session_ref": run}
    assert json.loads(seen[1]["body"]) == {
        "kind": "subagent", "external_instance_ref": agent_id, "parent_external_session_ref": run, "agent_type": "planner",
    }
    assert json.loads(seen[2]["body"]) == {}
    assert json.loads(seen[3]["body"]) == {"outcome": "completed", "reason_code": "hook_reported"}
    assert json.loads(seen[4]["body"]) == {"outcome": "completed"}
    assert session_id not in json.dumps(seen)  # the Claude session id never reaches the platform
    assert live.state(session_id) is None
    assert live.failure_count("SessionStart") == 0


# ---------------------------------------------------------------------------
# Response table
# ---------------------------------------------------------------------------

_CLOSE_PATH = "/api/v1/agent-runtime/subagents/{ref}/close"


@pytest.mark.parametrize(
    "responses,expected_class,expected_requests",
    [
        ([(200, "{}")], "ok", 1),
        ([(404, '{"detail":"Runtime session not found."}')], "close_miss", 1),
        ([(409, '{"detail":"This is a session, not a subagent; use PATCH."}')], "client_error", 1),
        ([(422, '{"detail":"validation"}')], "client_error", 1),
        ([(429, '{"detail":"Too many agent-runtime calls"}')], "client_error", 1),
        ([(403, '{"detail":"forbidden"}')], "client_error", 1),
        ([(500, "{}"), (500, "{}")], "server_error", 2),
        ([(500, "{}"), (200, "{}")], "ok", 2),
        ([(503, "{}"), (503, "{}"), (200, "{}")], "server_error", 2),
    ],
)
def test_close_response_table(live, stub, responses, expected_class, expected_requests):
    session_id, agent_id = new_session_id(), new_agent_id()
    _register(live, stub, session_id)
    stub.seen.clear()
    stub.on("POST", _CLOSE_PATH.format(ref=agent_id), *responses)

    result = live.run(payload_bytes("SubagentStop", session_id, agent_id=agent_id))

    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    assert len(stub.seen) == expected_requests  # 4xx terminal; one retry only, only on 5xx
    assert live.last_log()[2] == expected_class
    assert live.failure_count("SubagentStop") == (0 if expected_class == "ok" else 1)
    assert all(r["path"] != SESSIONS for r in stub.seen)  # a miss never registers-then-closes


def test_a_platform_with_no_listener_is_a_quiet_counted_failure(tmp_path):
    hook = Hook(tmp_path, dry_run=False)
    hook.write_key_file(f"http://127.0.0.1:{_free_port()}")

    started = time.monotonic()
    result = hook.run(payload_bytes("SessionStart", new_session_id(), source="startup"))

    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    assert time.monotonic() - started < 10  # bounded (two 2 s attempts at most), with slack for a loaded runner
    assert hook.last_log()[2:4] == ["conn_fail", "000"]
    assert hook.failure_count("SessionStart") == 1


def test_a_registration_that_could_not_connect_leaves_a_recoverable_state(tmp_path):
    hook = Hook(tmp_path, dry_run=False)
    hook.write_key_file(f"http://127.0.0.1:{_free_port()}")
    session_id = new_session_id()

    hook.fire("SessionStart", session_id, source="startup")

    run, runtime, _heartbeat = hook.state(session_id)
    assert runtime == "-" and run != session_id


def test_a_client_error_on_registration_leaves_no_state(live, stub):
    stub.on("POST", SESSIONS, (403, '{"detail":"forbidden"}'))
    session_id = new_session_id()

    live.fire("SessionStart", session_id, source="startup")

    assert live.state(session_id) is None and len(stub.seen) == 1
    assert live.last_log()[2] == "client_error"


def test_a_platform_that_never_answers_cannot_hold_the_hook_past_its_budget(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    held = []

    def accept_and_hold():
        while True:
            try:
                held.append(listener.accept()[0])
            except OSError:
                return

    threading.Thread(target=accept_and_hold, daemon=True).start()
    hook = Hook(tmp_path, dry_run=False)
    hook.write_key_file(f"http://127.0.0.1:{listener.getsockname()[1]}")

    started = time.monotonic()
    result = hook.run(payload_bytes("SessionStart", new_session_id(), source="startup"))
    elapsed = time.monotonic() - started
    listener.close()

    assert result.returncode == 0 and result.stdout == b""
    assert elapsed < 10  # a hung platform costs one 2 s attempt, never a hang (60 s subprocess cap)
    assert hook.last_log()[2] == "conn_fail"


def test_a_stdin_that_never_closes_and_never_carries_data_cannot_hang_the_hook(tmp_path):
    import subprocess

    from twin_hook_harness import SCRIPT

    hook = Hook(tmp_path)
    process = subprocess.Popen(
        [BASH, SCRIPT.as_posix()], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=hook.env()
    )
    started = time.monotonic()
    try:
        code = process.wait(timeout=20)
    finally:
        process.kill()
    assert code == 0 and time.monotonic() - started < 12  # 2 s head timeout plus the 2 s read fallback


# ---------------------------------------------------------------------------
# Ended-parent recovery (T3-F2): re-register once, retry the subagent once, never loop
# ---------------------------------------------------------------------------


def test_a_409_parent_session_ended_mints_a_new_run_and_retries_the_subagent_once(live, stub):
    session_id, agent_id = new_session_id(), new_agent_id()
    old_run = _register(live, stub, session_id)
    stub.seen.clear()
    stub.on(
        "POST", SESSIONS,
        (409, '{"detail":"parent_session_ended"}'),  # the subagent, refused
        (201, json.dumps({"id": NEW_RUNTIME_ID})),  # the new run's session
        (201, "{}"),  # the subagent, retried
    )

    live.fire("SubagentStart", session_id, agent_id=agent_id, agent_type="planner")

    first, second, third = stub.bodies("POST", SESSIONS)
    assert first["kind"] == "subagent" and first["parent_external_session_ref"] == old_run
    assert second["kind"] == "session" and second["external_session_ref"] != old_run
    assert third["kind"] == "subagent" and third["external_instance_ref"] == agent_id
    assert third["parent_external_session_ref"] == second["external_session_ref"]
    assert live.state(session_id)[:2] == (second["external_session_ref"], NEW_RUNTIME_ID)
    assert live.last_log()[2] == "reregistered"


def test_a_second_409_after_the_retry_is_terminal_and_the_hook_never_loops(live, stub):
    session_id = new_session_id()
    _register(live, stub, session_id)
    stub.seen.clear()
    stub.on(
        "POST", SESSIONS,
        (409, '{"detail":"parent_session_ended"}'), (201, json.dumps({"id": NEW_RUNTIME_ID})),
        (409, '{"detail":"parent_session_ended"}'),
    )

    live.fire("SubagentStart", session_id, agent_id=new_agent_id())

    assert len(stub.seen) == 3
    assert live.last_log()[2] == "client_error" and live.failure_count("SubagentStart") == 1


def test_a_409_from_a_failed_re_registration_is_terminal(live, stub):
    session_id = new_session_id()
    _register(live, stub, session_id)
    stub.seen.clear()
    stub.on("POST", SESSIONS, (409, '{"detail":"parent_session_ended"}'), (403, '{"detail":"no"}'))

    live.fire("SubagentStart", session_id, agent_id=new_agent_id())

    assert len(stub.seen) == 2 and live.last_log()[2] == "client_error"


@pytest.mark.parametrize("detail", ["This persona is suspended.", "Persona cap reached", "AGT-CLAUDE-CODE is not seeded"])
def test_any_other_409_on_a_subagent_is_terminal_with_no_re_registration(live, stub, detail):
    session_id = new_session_id()
    _register(live, stub, session_id)
    stub.seen.clear()
    stub.on("POST", SESSIONS, (409, json.dumps({"detail": detail})))

    live.fire("SubagentStart", session_id, agent_id=new_agent_id())

    assert len(stub.seen) == 1 and live.last_log()[2] == "client_error"


def test_a_404_for_an_unregistered_parent_is_terminal(live, stub):
    session_id = new_session_id()
    _register(live, stub, session_id)
    stub.seen.clear()
    stub.on("POST", SESSIONS, (404, '{"detail":"Parent session is not registered."}'))

    live.fire("SubagentStart", session_id, agent_id=new_agent_id())

    assert len(stub.seen) == 1 and live.last_log()[2] == "client_error"


def test_heartbeat_and_session_end_responses(live, stub):
    session_id = new_session_id()
    run = _register(live, stub, session_id)
    live.put_state(session_id, run, RUNTIME_ID, 0)
    stub.on("PATCH", f"{SESSIONS}/{RUNTIME_ID}", (404, '{"detail":"Runtime session not found."}'))

    live.fire("Stop", session_id)
    assert live.last_log()[2] == "client_error" and live.failure_count("Stop") == 1
    assert live.state(session_id)[2] > 0  # the attempt is stamped, so an outage adds no slow call per prompt

    live.fire("SessionEnd", session_id, reason="clear")
    assert live.last_log()[1:3] == ["SessionEnd", "client_error"]
    assert live.state(session_id) is None  # the state file goes even when the platform refused


# ---------------------------------------------------------------------------
# Test 6 -- key hygiene
# ---------------------------------------------------------------------------

_SHIM = (
    'p="$SHIM_RECORD_DIR/$$"\n'
    'printf \'%s\\n\' "$@" > "$p.argv"\n'
    'env > "$p.env"\n'
    'cat > "$p.stdin"\n'
    'printf \'{"id":"%s"}201\' "$SHIM_RUNTIME_ID"\n'
)


def _shimmed(tmp_path, base_url: str, *, export: bool = False) -> tuple[Hook, str]:
    hook = Hook(tmp_path, dry_run=False)
    record = tmp_path / "record"
    record.mkdir()
    hook.make_shims(["curl"], _SHIM)
    hook.env_extra.update({"SHIM_RECORD_DIR": record.as_posix(), "SHIM_RUNTIME_ID": RUNTIME_ID})
    key = hook.write_key_file(base_url, export=export)
    return hook, key


def _records(tmp_path, suffix: str) -> list[str]:
    return [p.read_text(errors="replace") for p in sorted((tmp_path / "record").glob(f"*.{suffix}"))]


def test_the_key_is_only_ever_on_the_curl_shims_stdin(tmp_path):
    hook, key = _shimmed(tmp_path, "http://127.0.0.1:9")
    session_id, agent_id = new_session_id(), new_agent_id()
    outputs = b""

    for event, fields in (
        ("SessionStart", {"source": "startup"}),
        ("SubagentStart", {"agent_id": agent_id, "agent_type": "planner", "prompt": "CANARY-prompt-000000000000"}),
    ):
        result = hook.run(payload_bytes(event, session_id, **fields))
        outputs += result.stdout + result.stderr
    run, _runtime, _hb = hook.state(session_id)
    hook.put_state(session_id, run, RUNTIME_ID, 0)
    for event, fields in (("Stop", {}), ("SubagentStop", {"agent_id": agent_id}), ("SessionEnd", {"reason": "clear"})):
        result = hook.run(payload_bytes(event, session_id, **fields))
        outputs += result.stdout + result.stderr

    argv, env, stdin = _records(tmp_path, "argv"), _records(tmp_path, "env"), _records(tmp_path, "stdin")
    assert len(argv) == len(env) == len(stdin) == 5
    for text in argv + env:
        assert key not in text and "dtk_" not in text
    # (the environment is not checked for the URL: NO_PROXY and friends legitimately hold hosts)
    assert all("127.0.0.1" not in text for text in argv)  # the URL travels in the config on stdin too
    assert all(key in text for text in stdin)  # present only where curl reads its config
    for text in (hook.tree_text(), outputs.decode(errors="replace")):
        assert key not in text and "dtk_" not in text
    joined = "\n".join(argv[0].split())
    for expected in ("--connect-timeout", "--max-time", "--max-redirs", "--noproxy", "--proto", "=http,https", "%{http_code}"):
        assert expected in joined


@pytest.mark.parametrize("url", ["http://localhost:9", "http://127.0.0.1:9", "http://[::1]:9"])
def test_loopback_http_is_allowed(tmp_path, url):
    hook, _key = _shimmed(tmp_path, url)

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert len(_records(tmp_path, "argv")) == 1
    assert hook.last_log()[2] == "ok"


def test_a_non_loopback_http_url_makes_no_call(tmp_path):
    hook, _key = _shimmed(tmp_path, "http://platform.example.invalid")

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert _records(tmp_path, "argv") == []
    assert hook.last_log()[2] == "insecure_transport" and hook.failure_count("SessionStart") == 1


def test_a_non_loopback_https_url_is_allowed_and_does_not_disable_proxies(tmp_path):
    hook, _key = _shimmed(tmp_path, "https://platform.example.invalid")

    hook.fire("SessionStart", new_session_id(), source="startup")

    (argv,) = _records(tmp_path, "argv")
    assert "--noproxy" not in argv and "=http,https" in argv


@pytest.mark.parametrize(
    "lines,expected",
    [
        (None, "no_key"),  # no key file at all
        ("DAYTHREE_TWIN_BASE_URL=http://127.0.0.1:9\n", "no_key"),
        ("DAYTHREE_TWIN_KEY={key}\n", "no_key"),
        ("DAYTHREE_TWIN_BASE_URL=http://127.0.0.1:9\nDAYTHREE_TWIN_KEY=short\n", "bad_config"),
        ("DAYTHREE_TWIN_BASE_URL=ftp://127.0.0.1\nDAYTHREE_TWIN_KEY={key}\n", "bad_config"),
        ("DAYTHREE_TWIN_BASE_URL=http://127.0.0.1:9/path\nDAYTHREE_TWIN_KEY={key}\n", "bad_config"),
        ("DAYTHREE_TWIN_BASE_URL=\nDAYTHREE_TWIN_KEY={key}\n", "no_key"),
    ],
)
def test_missing_or_malformed_config_means_no_call_and_one_enum_line(tmp_path, lines, expected):
    from twin_hook_harness import synthetic_key

    hook, _key = _shimmed(tmp_path, "http://127.0.0.1:9")
    key_file = hook.home / ".daythree" / "twin_env.sh"
    if lines is None:
        key_file.unlink()
    else:
        key_file.write_text(lines.replace("{key}", synthetic_key()), newline="\n")

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert _records(tmp_path, "argv") == []
    assert [line[2] for line in hook.log_lines()] == [expected]


def test_a_key_in_the_ambient_environment_is_never_a_working_default(tmp_path):
    from twin_hook_harness import synthetic_key

    hook, _key = _shimmed(tmp_path, "http://127.0.0.1:9")
    (hook.home / ".daythree" / "twin_env.sh").unlink()

    result = hook.run(
        payload_bytes("SessionStart", new_session_id(), source="startup"),
        env={"DAYTHREE_TWIN_BASE_URL": "http://127.0.0.1:9", "DAYTHREE_TWIN_KEY": synthetic_key()},
    )

    assert result.returncode == 0 and _records(tmp_path, "argv") == []
    assert hook.last_log()[2] == "no_key"


def test_a_key_file_with_windows_line_endings_still_works(tmp_path):
    hook, key = _shimmed(tmp_path, "http://127.0.0.1:9")
    key_file = hook.home / ".daythree" / "twin_env.sh"
    key_file.write_bytes(key_file.read_bytes().replace(b"\n", b"\r\n"))

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert len(_records(tmp_path, "argv")) == 1 and hook.last_log()[2] == "ok"


# ---------------------------------------------------------------------------
# Limited re-registration (coordinator decision): only the SAME run, only when the state has
# no runtime id, at most once per invocation, never with no state at all
# ---------------------------------------------------------------------------


def test_re_registration_re_posts_only_the_run_already_in_the_state_and_only_once(live, stub):
    session_id, run = new_session_id(), str(uuid.uuid4())
    live.put_state(session_id, run, "-", 0)
    stub.on("POST", SESSIONS, (403, '{"detail":"forbidden"}'))

    live.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type="planner")

    assert len(stub.seen) == 1  # one re-POST, no retry on a 4xx, and the subagent is never sent
    assert json.loads(stub.seen[0]["body"]) == {"kind": "session", "external_session_ref": run}
    assert live.state(session_id)[:2] == (run, "-")  # still the same run, still unregistered


def test_re_registration_reuses_the_same_run_for_the_session_and_its_subagent(live, stub):
    session_id, run = new_session_id(), str(uuid.uuid4())
    live.put_state(session_id, run, "-", 0)
    stub.on("POST", SESSIONS, CREATED, (201, "{}"))

    live.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type="planner")

    first, second = stub.bodies("POST", SESSIONS)
    assert first == {"kind": "session", "external_session_ref": run}
    assert second["parent_external_session_ref"] == run  # one Mission's worth of refs, never a second run
    assert live.state(session_id)[:2] == (run, RUNTIME_ID)


def test_a_heartbeat_with_a_runtime_id_never_re_posts(live, stub):
    session_id, run = new_session_id(), str(uuid.uuid4())
    live.put_state(session_id, run, RUNTIME_ID, 0)
    stub.on("PATCH", f"{SESSIONS}/{RUNTIME_ID}", (500, "{}"))

    live.fire("Stop", session_id)

    assert {r["method"] for r in stub.seen} == {"PATCH"}  # only the PATCH (and its one 5xx retry)
    assert all(r["path"] != SESSIONS for r in stub.seen)


@pytest.mark.parametrize(
    "event,fields",
    [("SubagentStart", {"agent_id": "a1b2c3d4e5f60718", "agent_type": "planner"}), ("Stop", {}), ("UserPromptSubmit", {})],
)
def test_with_no_state_file_nothing_is_ever_registered(live, stub, event, fields):
    live.fire(event, new_session_id(), **fields)

    assert stub.seen == []
    assert live.last_log()[2] == "no_state"


# ---------------------------------------------------------------------------
# Review round 2: environment hygiene, registration outage, 409 race, key file parsing
# ---------------------------------------------------------------------------


def _script_text() -> str:
    from twin_hook_harness import SCRIPT

    return SCRIPT.read_text(encoding="utf-8")


def _assigned_identifiers(text: str) -> set[str]:
    """Every identifier the script assigns, derived from its text (not from a hand list)."""
    import re

    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    names = set(re.findall(r"(?<![\w$\-\"'/.])([A-Za-z_][A-Za-z0-9_]*)\+?=", code))
    for match in re.finditer(r"\blocal\s+([^\n;]*)", code):
        names.update(token.split("=", 1)[0] for token in match.group(1).split() if re.match(r"^[A-Za-z_]\w*", token))
    names.update(re.findall(r"printf -v (\w+)", code))
    for match in re.finditer(r"\bread -r (?:-[a-z] \S+ )*((?:[A-Za-z_]\w* ?)+)", code):
        names.update(match.group(1).split())
    names.update(re.findall(r"\bfor (\w+) in", code))
    names.update({"UUID_RE", "REF_RE", "KEY_RE", "URL_RE"})
    return {n for n in names if re.fullmatch(r"[A-Za-z_]\w*", n)} - {"IFS", "LC_ALL", "PATH"}


def _unset_list(text: str) -> set[str]:
    import re

    match = re.search(r"^unset -v ((?:.*\\\n)*.*)$", text, re.M)
    return set(match.group(1).replace("\\\n", " ").split())


def test_the_script_unsets_every_identifier_it_assigns_before_assigning_anything():
    text = _script_text()

    missing = _assigned_identifiers(text) - _unset_list(text)

    assert missing == set(), f"assigned but not unset at the top of the script: {sorted(missing)}"
    assert text.index("unset -v") < text.index("readonly ROSTER")


def test_no_ambient_exported_variable_of_any_name_the_script_assigns_can_carry_secrets_into_curl(tmp_path):
    import os

    hook, key = _shimmed(tmp_path, "http://127.0.0.1:9")
    existing = {name.casefold() for name in os.environ}  # Windows names are case-insensitive: never clobber PATH etc.
    ambient = {name: "AMBIENT" for name in _assigned_identifiers(_script_text()) if name.casefold() not in existing}
    canary = f"CANARY-prompt-{uuid.uuid4().hex[:12]}"
    session_id, agent_id = new_session_id(), new_agent_id()

    def run(event, **fields):
        result = hook.run(payload_bytes(event, session_id, prompt=canary, **fields), env=ambient)
        assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""

    run("SessionStart", source="startup")
    run("SubagentStart", agent_id=agent_id, agent_type="planner")
    hook.put_state(session_id, hook.state(session_id)[0], RUNTIME_ID, 0)
    run("Stop")
    run("SubagentStop", agent_id=agent_id)
    run("SessionEnd", reason="clear")

    envs = _records(tmp_path, "env")
    assert len(envs) == 5
    for text in envs:
        assert key not in text and "dtk_" not in text and canary not in text
        assert "Authorization" not in text and "external_session_ref" not in text and "url = " not in text
        assert "hook_reported" not in text and "outcome" not in text


def _hold_hook(tmp_path):
    from twin_hook_harness import HoldListener

    listener = HoldListener()
    hook = Hook(tmp_path, dry_run=False)
    hook.write_key_file(listener.base_url)
    return hook, listener


def test_a_registration_outage_costs_one_slow_call_then_every_event_is_quick(tmp_path):
    hook, listener = _hold_hook(tmp_path)
    session_id, run = new_session_id(), str(uuid.uuid4())
    hook.put_state(session_id, run, "-", 0)
    elapsed = {}

    try:
        for label, event, fields in (
            ("stop", "Stop", {}),
            ("prompt", "UserPromptSubmit", {}),
            ("subagent", "SubagentStart", {"agent_id": new_agent_id(), "agent_type": "planner"}),
            ("stop-again", "Stop", {}),
        ):
            started = time.monotonic()
            hook.fire(event, session_id, **fields)
            elapsed[label] = time.monotonic() - started
        connections = listener.connections
    finally:
        listener.close()

    assert connections == 1  # one registration attempt in total, never a second
    assert elapsed["stop"] < 6  # the 2 s attempt (no retry: the budget is spent), not two of them
    assert max(elapsed["prompt"], elapsed["subagent"], elapsed["stop-again"]) < elapsed["stop"] + 1
    assert [line[2] for line in hook.log_lines()] == ["conn_fail", "throttled", "backoff", "throttled"]
    assert hook.state(session_id)[:2] == (run, "-") and hook.state(session_id)[2] > 0  # the attempt is stamped


def test_a_failed_registration_stamps_the_state_so_the_next_minute_of_subagents_back_off(tmp_path):
    hook, listener = _hold_hook(tmp_path)
    session_id = new_session_id()

    try:
        hook.fire("SessionStart", session_id, source="startup")
        hook.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type="planner")
        connections = listener.connections
    finally:
        listener.close()

    assert connections == 1
    assert [line[2] for line in hook.log_lines()] == ["conn_fail", "backoff"]


def test_twenty_stop_events_with_an_unregistered_session_make_at_most_one_registration_post(live, stub):
    session_id, run = new_session_id(), str(uuid.uuid4())
    live.put_state(session_id, run, "-", 0)
    stub.on("POST", SESSIONS, (403, '{"detail":"forbidden"}'))

    for _ in range(20):
        live.fire("Stop", session_id)

    assert len([r for r in stub.seen if r["method"] == "POST"]) <= 1
    assert live.state(session_id)[1] == "-"


def test_two_parallel_subagent_starts_on_an_ended_run_share_one_new_run(live, stub):
    session_id = new_session_id()
    old_run = _register(live, stub, session_id)
    stub.seen.clear()
    first_agent, second_agent = new_agent_id(), new_agent_id()
    registered = threading.Event()
    refused = []

    def responder(request):
        if request["method"] != "POST" or request["path"] != SESSIONS:
            return None
        body = json.loads(request["body"])
        if body["kind"] == "session":
            registered.set()
            return 201, json.dumps({"id": NEW_RUNTIME_ID})
        if body["parent_external_session_ref"] == old_run:
            refused.append(body["external_instance_ref"])
            if len(refused) > 1:  # the second hook's refusal arrives once the first has re-registered
                registered.wait(timeout=5)
                time.sleep(0.5)
            return 409, '{"detail":"parent_session_ended"}'
        return 201, "{}"

    stub.responder = responder
    payloads = [
        payload_bytes("SubagentStart", session_id, agent_id=agent_id, agent_type="planner")
        for agent_id in (first_agent, second_agent)
    ]
    processes = [live.popen(raw) for raw in payloads]
    codes = [p.wait(timeout=60) for p in processes]

    assert codes == [0, 0]
    bodies = stub.bodies("POST", SESSIONS)
    new_sessions = [b for b in bodies if b["kind"] == "session"]
    assert len(new_sessions) == 1, "a second run (a second Mission) was minted"
    retried = [b for b in bodies if b["kind"] == "subagent" and b["parent_external_session_ref"] != old_run]
    assert {b["external_instance_ref"] for b in retried} == {first_agent, second_agent}
    assert {b["parent_external_session_ref"] for b in retried} == {new_sessions[0]["external_session_ref"]}
    assert live.state(session_id)[0] == new_sessions[0]["external_session_ref"]


# ---- the key file is read, never executed -------------------------------------------------


def _marker(tmp_path, name: str):
    return tmp_path / f"executed-{name}"


def test_a_key_file_full_of_shell_syntax_runs_nothing_and_yields_only_validated_values(tmp_path):
    from twin_hook_harness import synthetic_key

    hook, _key = _shimmed(tmp_path, "http://127.0.0.1:9")
    key = synthetic_key()
    markers = [_marker(tmp_path, name).as_posix() for name in ("subst", "tick", "semi", "export", "func", "and")]
    hook.write_key_text(
        f"# a comment with $(touch {markers[0]})\n"
        f"$(touch {markers[0]})\n"
        f"`touch {markers[1]}`\n"
        f"touch {markers[2]}; touch {markers[2]}\n"
        f"export FROM_THE_FILE=1; touch {markers[3]}\n"
        f"f() {{ touch {markers[4]}; }}; f\n"
        f"true && touch {markers[5]}\n"
        "export DAYTHREE_TWIN_KEY=ignored-because-of-the-export-prefix\n"
        "  DAYTHREE_TWIN_KEY=ignored-because-of-the-leading-spaces\n"
        "DAYTHREE_TWIN_BASE_URL=http://127.0.0.1:9\n"
        f"DAYTHREE_TWIN_KEY={key}\n"
        "DAYTHREE_TWIN_KEY=a-second-line-never-wins\n"
    )

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert [p for p in tmp_path.glob("executed-*")] == []
    (stdin,) = _records(tmp_path, "stdin")
    assert key in stdin and "ignored-because" not in stdin and "a-second-line" not in stdin
    assert hook.last_log()[2] == "ok"


@pytest.mark.parametrize(
    "value_line",
    [
        "DAYTHREE_TWIN_KEY=$(touch {marker})",
        "DAYTHREE_TWIN_KEY=`touch {marker}`",
        "DAYTHREE_TWIN_KEY={key}; touch {marker}",
        "DAYTHREE_TWIN_KEY={key} && touch {marker}",
        'DAYTHREE_TWIN_KEY="{key}"',
        "DAYTHREE_TWIN_KEY={key} # trailing comment",
    ],
)
def test_a_key_line_with_anything_but_the_bare_key_is_refused_and_nothing_runs(tmp_path, value_line):
    from twin_hook_harness import synthetic_key

    hook, _key = _shimmed(tmp_path, "http://127.0.0.1:9")
    marker = _marker(tmp_path, "value").as_posix()
    hook.write_key_text(
        "DAYTHREE_TWIN_BASE_URL=http://127.0.0.1:9\n" + value_line.format(marker=marker, key=synthetic_key()) + "\n"
    )

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert not _marker(tmp_path, "value").exists()
    assert _records(tmp_path, "argv") == []
    assert hook.last_log()[2] in {"no_key", "bad_config"}


def test_an_export_prefixed_key_file_is_not_honoured(tmp_path):
    hook, _key = _shimmed(tmp_path, "http://127.0.0.1:9", export=True)

    hook.fire("SessionStart", new_session_id(), source="startup")

    assert _records(tmp_path, "argv") == [] and hook.last_log()[2] == "no_key"


def test_the_dry_run_file_is_honoured_only_when_dry_run_is_on(tmp_path):
    hook, _key = _shimmed(tmp_path, "http://127.0.0.1:9")
    target = tmp_path / "should-not-exist.txt"

    result = hook.run(
        payload_bytes("SessionStart", new_session_id(), source="startup"), env={"TWIN_DRY_RUN_FILE": str(target)}
    )

    assert result.returncode == 0 and not target.exists()
    assert len(_records(tmp_path, "argv")) == 1  # a real (shimmed) call, not a dry run
