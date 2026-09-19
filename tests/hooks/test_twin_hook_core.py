"""T3 test layer 1-4: `scripts/report_twin_lifecycle.sh` in dry-run mode (no network, no key).

Exit 0 and byte-empty stdout/stderr on every input, the canary and decoy payloads, the body
allow-list, and the per-session state lifecycle including the heartbeat throttle and
concurrent hook runs. Payloads are synthetic (built from field names with placeholder
values generated at run time).
"""
from __future__ import annotations

import json
import re
import secrets
import time

import pytest

from twin_hook_harness import BASH, SESSIONS, Hook, new_agent_id, new_session_id, payload_bytes

pytestmark = [pytest.mark.unit, pytest.mark.skipif(BASH is None, reason="bash is not available")]

ROSTER = ["planner", "architect", "code-reviewer", "tdd-guide", "security-reviewer"]
EVENTS = ["SessionStart", "SubagentStart", "SubagentStop", "SessionEnd", "Stop", "UserPromptSubmit"]
LOG_LINE = re.compile(
    r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ (SessionStart|SubagentStart|SubagentStop|SessionEnd|Stop|UserPromptSubmit|-) "
    r"[a-z_]+ (\d{3}|-) \d+ ([A-Za-z0-9._-]{1,8}|-)$"
)


@pytest.fixture
def hook(tmp_path) -> Hook:
    return Hook(tmp_path)


def _start(hook: Hook, session_id: str, source: str = "startup") -> str:
    hook.fire("SessionStart", session_id, source=source)
    return hook.state(session_id)[0]


# ---------------------------------------------------------------------------
# Test 1 -- exit 0 and byte-empty output on every input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event", EVENTS)
def test_each_event_exits_zero_with_byte_empty_stdout_and_stderr(hook, event):
    session_id = new_session_id()
    fields = {"source": "startup"} if event == "SessionStart" else {}
    if event.startswith("Subagent"):
        fields = {"agent_id": new_agent_id(), "agent_type": "planner"}
    if event == "SessionEnd":
        fields = {"reason": "other"}

    result = hook.run(payload_bytes(event, session_id, **fields))

    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize(
    "stdin",
    [
        b"",
        b"  \n",
        b"{",
        b'{"session_id":',
        b"not json at all",
        b"[1,2,3]",
        b"\x00\x01\x02\xff\xfe binary",
        b'{"hook_event_name":"Stop"}',
        b'{"session_id":"not-a-uuid","hook_event_name":"Stop"}',
    ],
)
def test_empty_or_malformed_stdin_sends_nothing_and_stays_silent(hook, stdin):
    result = hook.run(stdin)

    assert result.returncode == 0
    assert result.stdout == b"" and result.stderr == b""
    assert hook.requests() == []


def test_a_64_kib_payload_is_processed_normally(hook):
    session_id = new_session_id()

    hook.fire("SessionStart", session_id, source="startup", padding="p" * 65536)

    assert [r["method"] for r in hook.requests()] == ["POST"]
    assert hook.last_log()[2] == "ok"


def test_a_2_mib_payload_is_refused_without_a_request(hook):
    result = hook.run(payload_bytes("SessionStart", new_session_id(), source="startup", padding="p" * (2 * 1024 * 1024)))

    assert result.returncode == 0
    assert result.stdout == b"" and result.stderr == b""
    assert hook.requests() == []
    assert hook.last_log()[2] == "oversize"


def test_a_crlf_payload_is_read(hook):
    session_id = new_session_id()
    text = json.dumps({"session_id": session_id, "hook_event_name": "SessionStart", "source": "startup"}, indent=2)

    result = hook.run(text.replace("\n", "\r\n").encode())

    assert result.returncode == 0 and result.stdout == b""
    assert len(hook.requests()) == 1
    assert hook.state(session_id) is not None


def test_the_event_name_falls_back_to_argv_when_the_payload_omits_it(hook):
    session_id = new_session_id()
    raw = json.dumps({"session_id": session_id, "source": "startup"}).encode()

    result = hook.run(raw, event_arg="SessionStart")

    assert result.returncode == 0
    assert len(hook.requests()) == 1


def test_an_unknown_event_is_ignored_and_a_missing_one_is_a_counted_failure(hook):
    session_id = new_session_id()

    hook.fire("PreToolUse", session_id)
    assert hook.last_log()[2] == "ignored" and hook.failure_count("unknown") == 0
    hook.run(json.dumps({"session_id": session_id}).encode())
    assert hook.last_log()[2] == "bad_event" and hook.failure_count("unknown") == 1
    assert hook.requests() == []


@pytest.mark.parametrize(
    "failing",
    [["sed"], ["od"], ["mkdir"], ["mv"], ["rm"], ["timeout"], ["head"], ["timeout", "head"]],
)
def test_any_single_internal_command_failing_still_exits_zero_silently(hook, failing):
    hook.make_shims(failing)
    session_id = new_session_id()

    for event, fields in (
        ("SessionStart", {"source": "startup"}),
        ("SubagentStart", {"agent_id": new_agent_id(), "agent_type": "planner"}),
        ("Stop", {}),
        ("SessionEnd", {"reason": "other"}),
    ):
        result = hook.run(payload_bytes(event, session_id, **fields))
        assert result.returncode == 0
        assert result.stdout == b"" and result.stderr == b""


def test_every_external_command_failing_at_once_still_exits_zero_silently(hook):
    hook.make_shims(["sed", "od", "mkdir", "mv", "rm", "timeout", "head", "cat", "date", "tr", "curl", "wc", "tail", "grep"])

    result = hook.run(payload_bytes("SessionStart", new_session_id(), source="startup"))

    assert result.returncode == 0
    assert result.stdout == b"" and result.stderr == b""


# ---------------------------------------------------------------------------
# Test 2 -- canaries, decoys, hostile values
# ---------------------------------------------------------------------------

_CANARY_FIELDS = [
    "prompt", "user_prompt", "cwd", "transcript_path", "agent_transcript_path", "last_assistant_message",
    "session_title", "permission_mode", "scratchpad_dir", "model", "message", "notification_text",
]


def _canaries() -> dict:
    tokens = {name: f"CANARY-{name}-{secrets.token_hex(6)}" for name in _CANARY_FIELDS}
    tokens["tool_input"] = {"command": f"CANARY-tool_input-{secrets.token_hex(6)}"}
    tokens["tool_result"] = {"stdout": f"CANARY-tool_result-{secrets.token_hex(6)}"}
    tokens["background_tasks"] = [{"label": f"CANARY-background_tasks-{secrets.token_hex(6)}"}]
    tokens["session_crons"] = [{"expr": f"CANARY-session_crons-{secrets.token_hex(6)}"}]
    return tokens


def _all_tokens(canaries: dict) -> list[str]:
    return re.findall(r"CANARY-[a-z_]+-[0-9a-f]{12}", json.dumps(canaries))


def test_no_canary_field_reaches_a_request_the_log_the_state_or_the_output(hook):
    canaries = _canaries()
    tokens = _all_tokens(canaries)
    session_id = new_session_id()
    agent_id = new_agent_id()
    outputs = b""

    for event, fields in (
        ("SessionStart", {"source": "startup"}),
        ("UserPromptSubmit", {}),
        ("SubagentStart", {"agent_id": agent_id, "agent_type": "planner"}),
        ("SubagentStop", {"agent_id": agent_id, "agent_type": "planner"}),
        ("Stop", {}),
        ("SessionEnd", {"reason": "prompt_input_exit"}),
    ):
        # canaries first, so nothing depends on the allow-listed fields coming first
        raw = json.dumps({**canaries, "session_id": session_id, "hook_event_name": event, **fields}).encode()
        result = hook.run(raw)
        outputs += result.stdout + result.stderr

    haystack = (
        hook.dry_file.read_text() + hook.tree_text() + outputs.decode(errors="replace")
    )
    for token in tokens:
        assert token not in haystack
    assert len(hook.requests()) == 4  # start, subagent start, subagent stop, end (Stop/prompt throttled)


def test_decoy_keys_inside_a_message_string_change_nothing(hook):
    session_id = new_session_id()
    decoy_session, decoy_agent = new_session_id(), new_agent_id()
    run = _start(hook, session_id)
    real_agent = new_agent_id()
    message = f'note "session_id":"{decoy_session}" "agent_type":"planner" "agent_id":"{decoy_agent}" end'

    raw = json.dumps(
        {"last_assistant_message": message, "session_id": session_id, "hook_event_name": "SubagentStart",
         "agent_id": real_agent, "agent_type": "general-purpose"}
    ).encode()
    hook.run(raw)
    raw_stop = json.dumps(
        {"last_assistant_message": message, "session_id": session_id, "hook_event_name": "SubagentStop",
         "agent_id": real_agent, "agent_type": "general-purpose"}
    ).encode()
    hook.run(raw_stop)

    _start_request, sub_start, sub_stop = hook.requests()
    assert sub_start["body"] == {
        "kind": "subagent", "external_instance_ref": real_agent, "parent_external_session_ref": run,
    }
    assert sub_stop["path"] == f"/api/v1/agent-runtime/subagents/{real_agent}/close"
    assert decoy_session not in hook.tree_text() and decoy_agent not in hook.dry_file.read_text()


@pytest.mark.parametrize(
    "bad_ref", ["../", "..", ".", 'a"b', "a b", "a/b", "x;id", "a" * 65, "", "-lead", "a\\b", "a%2fb", "\u00e9x", "a\nb"]
)
def test_a_hostile_agent_id_sends_nothing(hook, bad_ref):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SubagentStart", session_id, agent_id=bad_ref, agent_type="planner")
    hook.fire("SubagentStop", session_id, agent_id=bad_ref, agent_type="planner")

    assert len(hook.requests()) == 1  # only the SessionStart registration
    assert hook.last_log()[2] == "bad_ref"


@pytest.mark.parametrize("good_ref", ["a" * 64, "abc.def_1-2", "0123456789abcdef0", "A1"])
def test_a_well_formed_agent_id_is_sent_exactly_as_validated(hook, good_ref):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SubagentStop", session_id, agent_id=good_ref)

    assert hook.requests()[-1]["path"] == f"/api/v1/agent-runtime/subagents/{good_ref}/close"


@pytest.mark.parametrize(
    "bad_session",
    ["../../x", "not-a-uuid", "", "a" * 36, "{0}-x", "urn:uuid:", "UPPER", "nodashes", "extra\nline"],
)
def test_a_session_id_that_is_not_a_canonical_uuid_sends_nothing_and_creates_no_state(hook, bad_session):
    if bad_session == "UPPER":
        bad_session = new_session_id().upper()
    elif bad_session == "nodashes":
        bad_session = new_session_id().replace("-", "")
    elif bad_session == "{0}-x":
        bad_session = new_session_id() + "x"

    hook.fire("SessionStart", bad_session, source="startup")

    assert hook.requests() == []
    assert hook.last_log()[2] == "bad_session"
    assert not hook.state_dir.exists() or list(hook.state_dir.iterdir()) == []


def test_a_missing_agent_id_sends_nothing(hook):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SubagentStart", session_id, agent_type="planner")
    hook.fire("SubagentStop", session_id)

    assert len(hook.requests()) == 1


# ---------------------------------------------------------------------------
# Test 3 -- body allow-list, roster-only agent_type, declared-not-measured outcome
# ---------------------------------------------------------------------------


def _validated_bodies(hook: Hook) -> list:
    from api.schemas.agent_runtime import (
        AgentRuntimeCloseRequest,
        AgentRuntimeSessionCreateRequest,
        AgentRuntimeSessionUpdateRequest,
    )

    checked = []
    for request in hook.requests():
        body = request["body"]
        if request["path"] == SESSIONS and request["method"] == "POST":
            model = AgentRuntimeSessionCreateRequest
        elif request["method"] == "PATCH":
            model = AgentRuntimeSessionUpdateRequest
        else:
            model = AgentRuntimeCloseRequest
        assert set(body) <= set(model.model_fields)
        model.model_validate(body)  # extra="forbid": a stray field would raise
        checked.append(request)
    return checked


def test_every_emitted_body_validates_against_the_t1_t2_request_schemas(hook):
    session_id, agent_id = new_session_id(), new_agent_id()
    _start(hook, session_id)
    hook.fire("SubagentStart", session_id, agent_id=agent_id, agent_type="planner")
    hook.put_state(session_id, hook.state(session_id)[0], hook.state(session_id)[1], 0)
    hook.fire("Stop", session_id)
    hook.fire("SubagentStop", session_id, agent_id=agent_id, last_assistant_message="anything")
    hook.fire("SessionEnd", session_id, reason="clear")

    checked = _validated_bodies(hook)

    assert [(r["method"], r["path"].rsplit("/", 1)[-1] if r["method"] != "PATCH" else "patch") for r in checked] == [
        ("POST", "sessions"), ("POST", "sessions"), ("PATCH", "patch"), ("POST", "close"), ("PATCH", "patch"),
    ]
    assert not any("tool_call_count" in (r["body"] or {}) for r in checked)


@pytest.mark.parametrize("name", ROSTER)
def test_a_roster_agent_type_is_sent(hook, name):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type=name)

    assert hook.requests()[-1]["body"]["agent_type"] == name


@pytest.mark.parametrize(
    "custom",
    ["general-purpose", "Planner", "planner ", "ecc:planner", "planner2", "security_reviewer", "AGT-CC-PLANNER",
     "custom-CANARY-abc123", "", "planner\nx"],
)
def test_any_other_agent_type_is_omitted(hook, custom):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type=custom)

    body = hook.requests()[-1]["body"]
    assert "agent_type" not in body
    assert "CANARY" not in json.dumps(body)


def test_the_hook_roster_is_a_subset_of_the_platform_persona_registry():
    from api.persona_registry import _REGISTRY
    from twin_hook_harness import SCRIPT

    declared = re.search(r'readonly ROSTER="([^"]*)"', SCRIPT.read_text(encoding="utf-8")).group(1).split()

    assert set(declared) == set(ROSTER)
    assert set(declared) <= set(_REGISTRY)


def test_a_last_assistant_message_saying_error_and_failed_still_closes_as_completed(hook):
    session_id, agent_id = new_session_id(), new_agent_id()
    _start(hook, session_id)

    hook.fire(
        "SubagentStop", session_id, agent_id=agent_id, last_assistant_message="error: it failed with an exception"
    )

    request = hook.requests()[-1]
    assert request["method"] == "POST" and request["path"].endswith("/close")
    assert request["body"] == {"outcome": "completed", "reason_code": "hook_reported"}


@pytest.mark.parametrize(
    "reason,outcome",
    [("clear", "completed"), ("resume", "completed"), ("logout", "completed"), ("prompt_input_exit", "completed"),
     ("other", "abandoned"), ("bypass_permissions_disabled", "abandoned"), ("made-up-CANARY", "abandoned"), (None, "abandoned")],
)
def test_session_end_maps_the_reason_through_a_fixed_table_and_forwards_only_the_outcome(hook, reason, outcome):
    session_id = new_session_id()
    _start(hook, session_id)
    runtime_id = hook.state(session_id)[1]

    hook.fire("SessionEnd", session_id, **({} if reason is None else {"reason": reason}))

    request = hook.requests()[-1]
    assert request["method"] == "PATCH" and request["path"] == f"{SESSIONS}/{runtime_id}"
    assert request["body"] == {"outcome": outcome}


# ---------------------------------------------------------------------------
# Test 4 -- state lifecycle and the heartbeat throttle
# ---------------------------------------------------------------------------


def test_a_double_session_start_is_one_run(hook):
    session_id = new_session_id()

    first = _start(hook, session_id)
    second = _start(hook, session_id)

    assert first == second
    assert len(hook.requests()) == 1
    assert hook.last_log()[2] == "duplicate"


def test_the_claude_session_id_is_never_the_platform_ref(hook):
    session_id = new_session_id()

    run = _start(hook, session_id)

    assert run != session_id
    assert session_id not in hook.dry_file.read_text()
    assert hook.requests()[0]["body"] == {"kind": "session", "external_session_ref": run}
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", run)


def test_compact_reuses_the_existing_run_and_sends_nothing(hook):
    session_id = new_session_id()
    run = _start(hook, session_id)

    hook.fire("SessionStart", session_id, source="compact")

    assert hook.state(session_id)[0] == run
    assert len(hook.requests()) == 1
    assert hook.last_log()[2] == "reused"


def test_compact_with_no_state_mints_and_registers_a_run(hook):
    session_id = new_session_id()

    hook.fire("SessionStart", session_id, source="compact")

    assert len(hook.requests()) == 1 and hook.state(session_id) is not None


@pytest.mark.parametrize("source", ["resume", "clear", "fork"])
def test_resume_clear_and_fork_mint_a_new_run(hook, source):
    session_id = new_session_id()
    first = _start(hook, session_id)

    hook.fire("SessionStart", session_id, source=source)

    assert hook.state(session_id)[0] != first
    assert len(hook.requests()) == 2


@pytest.mark.parametrize("source", [None, "weird", "STARTUP", ""])
def test_a_missing_or_unknown_source_sends_nothing(hook, source):
    hook.fire("SessionStart", new_session_id(), **({} if source is None else {"source": source}))

    assert hook.requests() == []
    assert hook.last_log()[2] == "bad_source"


def test_subagent_start_without_state_sends_nothing_and_counts_a_failure(hook):
    hook.fire("SubagentStart", new_session_id(), agent_id=new_agent_id(), agent_type="planner")

    assert hook.requests() == []
    assert hook.last_log()[2] == "no_state"
    assert hook.failure_count("SubagentStart") == 1


def test_subagent_start_with_a_registered_state_never_registers_a_second_session(hook):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type="planner")

    kinds = [r["body"]["kind"] for r in hook.requests()]
    assert kinds == ["session", "subagent"]


def test_a_session_whose_registration_never_landed_is_registered_again_before_its_first_subagent(hook):
    session_id, run = new_session_id(), new_session_id()
    hook.put_state(session_id, run, "-", 0)

    hook.fire("SubagentStart", session_id, agent_id=new_agent_id(), agent_type="planner")

    first, second = hook.requests()
    assert first["body"] == {"kind": "session", "external_session_ref": run}
    assert second["body"]["parent_external_session_ref"] == run
    assert hook.state(session_id)[1] != "-"


def test_session_end_removes_the_state_file_and_a_second_one_sends_nothing(hook):
    session_id = new_session_id()
    _start(hook, session_id)

    hook.fire("SessionEnd", session_id, reason="clear")
    assert hook.state(session_id) is None
    count = len(hook.requests())
    hook.fire("SessionEnd", session_id, reason="clear")

    assert len(hook.requests()) == count
    assert hook.last_log()[2] == "no_state"


def test_a_corrupt_state_file_is_treated_as_no_state_and_overwritten_by_the_next_start(hook):
    session_id = new_session_id()
    hook.state_dir.mkdir(parents=True)
    (hook.state_dir / session_id).write_text("garbage not a state\n")

    hook.fire("SubagentStart", session_id, agent_id=new_agent_id())
    assert hook.requests() == []
    hook.fire("SessionStart", session_id, source="startup")

    assert hook.state(session_id) is not None


def test_twenty_stop_events_after_a_fresh_start_emit_no_heartbeat_at_all(hook):
    session_id = new_session_id()
    _start(hook, session_id)

    for _ in range(20):
        hook.fire("Stop", session_id)

    assert [r["method"] for r in hook.requests()] == ["POST"]


def test_twenty_stop_and_prompt_events_past_the_interval_emit_exactly_one_heartbeat(hook):
    session_id = new_session_id()
    run = _start(hook, session_id)
    runtime_id = hook.state(session_id)[1]
    hook.put_state(session_id, run, runtime_id, int(time.time()) - 301)

    for index in range(20):
        hook.fire("Stop" if index % 2 else "UserPromptSubmit", session_id)

    patches = [r for r in hook.requests() if r["method"] == "PATCH"]
    assert len(patches) == 1
    assert patches[0]["path"] == f"{SESSIONS}/{runtime_id}" and patches[0]["body"] == {}
    assert abs(hook.state(session_id)[2] - int(time.time())) < 60


def test_ten_concurrent_hook_runs_never_corrupt_the_state_file(hook):
    session_id = new_session_id()
    run = _start(hook, session_id)
    runtime_id = hook.state(session_id)[1]
    hook.put_state(session_id, run, runtime_id, 0)

    processes = [hook.popen(payload_bytes("Stop", session_id)) for _ in range(10)]
    results = [(p.wait(timeout=60), p.stdout.read(), p.stderr.read()) for p in processes]

    assert all(code == 0 and out == b"" and err == b"" for code, out, err in results)
    state = hook.state(session_id)  # parses: exactly three well-formed fields
    assert state[0] == run and state[1] == runtime_id
    assert [p.name for p in hook.state_dir.iterdir() if p.name.startswith(".")] == []
    assert len([r for r in hook.requests() if r["method"] == "PATCH"]) >= 1


def test_ten_concurrent_session_starts_leave_one_readable_state_file(hook):
    session_id = new_session_id()

    processes = [hook.popen(payload_bytes("SessionStart", session_id, source="startup")) for _ in range(10)]
    codes = [p.wait(timeout=60) for p in processes]

    assert codes == [0] * 10
    assert hook.state(session_id) is not None
    assert [p.name for p in hook.state_dir.iterdir() if p.name.startswith(".")] == []


# ---------------------------------------------------------------------------
# Log grammar, failure counters, log cap
# ---------------------------------------------------------------------------


def test_every_log_line_follows_the_fixed_grammar_and_holds_no_payload_text(hook):
    session_id, agent_id = new_session_id(), new_agent_id()
    _start(hook, session_id)
    hook.fire("SubagentStart", session_id, agent_id=agent_id, agent_type="planner", prompt="CANARY-prompt-000000000000")
    hook.fire("SubagentStop", session_id, agent_id=agent_id)
    hook.fire("Stop", session_id)
    hook.fire("SessionEnd", session_id, reason="clear")
    hook.fire("SubagentStart", new_session_id(), agent_id="a" * 65)

    lines = hook.log_file.read_text().splitlines()

    assert len(lines) == 6
    assert all(LOG_LINE.match(line) for line in lines), lines
    text = "\n".join(lines)
    assert "planner" not in text and "CANARY" not in text and agent_id not in text  # 8-char prefix only
    assert agent_id[:8] in text


def test_the_log_is_capped_by_truncation_and_keeps_the_newest_line(hook):
    hook.state_root.mkdir(parents=True)
    filler = "2026-01-01T00:00:00Z Stop ok 200 1 aaaaaaaa\n" * 8000  # about 340 KiB
    hook.log_file.write_text(filler)

    hook.fire("Stop", new_session_id())

    size = hook.log_file.stat().st_size
    assert size < 262144
    assert hook.last_log()[1] == "Stop" and hook.last_log()[2] == "no_state"


def test_failure_counters_count_only_failures(hook):
    session_id = new_session_id()
    _start(hook, session_id)
    hook.fire("SubagentStart", new_session_id(), agent_id=new_agent_id())  # no_state
    hook.fire("SubagentStart", new_session_id(), agent_id=new_agent_id())  # no_state
    hook.fire("Stop", session_id)  # throttled: not a failure

    assert hook.failure_count("SubagentStart") == 2
    assert hook.failure_count("Stop") == 0 and hook.failure_count("SessionStart") == 0
