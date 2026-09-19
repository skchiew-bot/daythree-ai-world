"""Shared harness for the T3 twin-hook tests: runs `scripts/report_twin_lifecycle.sh`
under bash as a subprocess, with everything the script writes confined to a temporary
`TWIN_HOME`, and offers a stub of the platform's agent-runtime routes for the response
table tests.

Every payload here is synthetic: built from the documented field NAMES with placeholder
values generated at run time. No real session id, path, user name or prompt appears in any
test file (data-warden D41), and nothing here talks to a real platform or reads a real
key. The script is always run by absolute path (CI runs bare `pytest` from an install where
the repo root is not importable).
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "report_twin_lifecycle.sh"

SESSIONS = "/api/v1/agent-runtime/sessions"


def find_bash() -> Optional[str]:
    """Git Bash on Windows (an unqualified `bash` can resolve to the WSL launcher, which
    cannot see `C:/...` paths); the ordinary `bash` elsewhere."""
    override = os.environ.get("TWIN_TEST_BASH")
    if override:
        return override
    if sys.platform == "win32":
        for candidate in (r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe"):
            if os.path.exists(candidate):
                return candidate
        return None
    return shutil.which("bash")


BASH = find_bash()


def new_session_id() -> str:
    return str(uuid.uuid4())


def new_agent_id() -> str:
    return secrets.token_hex(8) + "0"  # 17 lowercase hex characters, the observed shape


def synthetic_key() -> str:
    """A key-shaped token generated at run time; never a literal in a tracked file."""
    return "dtk_" + secrets.token_hex(16) + "_" + secrets.token_urlsafe(32)


def payload_bytes(event: str, session_id: str, **fields) -> bytes:
    body = {"session_id": session_id, "hook_event_name": event}
    body.update(fields)
    return json.dumps(body, separators=(",", ":")).encode()


class Hook:
    """One isolated run environment: a private TWIN_HOME, an optional stub base URL."""

    def __init__(self, root: Path, *, dry_run: bool = True) -> None:
        self.root = root
        self.home = root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self.dry_file = root / "requests.txt"
        self.state_root = self.home / ".hook-debug"
        self.state_dir = self.state_root / "twin-state"
        self.fail_dir = self.state_root / "twin-failures"
        self.log_file = self.state_root / "twin_lifecycle.log"
        self.shim_dirs: list[Path] = []
        self.env_extra: dict[str, str] = {}

    # ------------------------------------------------------------ environment

    def env(self, extra: Optional[dict] = None) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TWIN_", "DAYTHREE_TWIN_"))}
        env["TWIN_HOME"] = str(self.home)
        if self.dry_run:
            env["TWIN_DRY_RUN"] = "1"
            env["TWIN_DRY_RUN_FILE"] = str(self.dry_file)
        if self.shim_dirs:
            env["PATH"] = os.pathsep.join([str(d) for d in self.shim_dirs] + [env.get("PATH", "")])
        env.update(self.env_extra)
        if extra:
            env.update(extra)
        return env

    def write_key_file(self, base_url: str, key: Optional[str] = None, *, export: bool = False) -> str:
        key = key or synthetic_key()
        prefix = "export " if export else ""
        target = self.home / ".daythree"
        target.mkdir(parents=True, exist_ok=True)
        (target / "twin_env.sh").write_text(
            f"{prefix}DAYTHREE_TWIN_BASE_URL={base_url}\n{prefix}DAYTHREE_TWIN_KEY={key}\n", encoding="utf-8", newline="\n"
        )
        return key

    def make_shims(self, names: list[str], body: str = "exit 1\n", *, name: str = "shims") -> Path:
        shim_dir = self.root / name
        shim_dir.mkdir(exist_ok=True)
        for shim_name in names:
            path = shim_dir / shim_name
            path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        self.shim_dirs.insert(0, shim_dir)
        return shim_dir

    # ------------------------------------------------------------ running

    def run(
        self, stdin: bytes, *, event_arg: Optional[str] = None, env: Optional[dict] = None, timeout: float = 60
    ) -> subprocess.CompletedProcess:
        argv = [BASH, SCRIPT.as_posix()]
        if event_arg is not None:
            argv.append(event_arg)
        return subprocess.run(
            argv, input=stdin, capture_output=True, env=self.env(env), timeout=timeout, cwd=str(self.root)
        )

    def popen(self, stdin: bytes, *, event_arg: Optional[str] = None) -> subprocess.Popen:
        argv = [BASH, SCRIPT.as_posix()]
        if event_arg is not None:
            argv.append(event_arg)
        process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env(), cwd=str(self.root)
        )
        process.stdin.write(stdin)
        process.stdin.close()
        return process

    def fire(self, event: str, session_id: str, **fields) -> subprocess.CompletedProcess:
        result = self.run(payload_bytes(event, session_id, **fields))
        assert result.returncode == 0
        assert result.stdout == b"" and result.stderr == b""
        return result

    # ------------------------------------------------------------ observations

    def requests(self) -> list[dict]:
        """Dry-run requests, oldest first: {method, path, body (parsed JSON or None)}."""
        if not self.dry_file.exists():
            return []
        parsed = []
        for line in self.dry_file.read_text(encoding="utf-8").splitlines():
            method, path, body = line.split(" ", 2)
            parsed.append({"method": method, "path": path, "body": json.loads(body)})
        return parsed

    def log_lines(self) -> list[list[str]]:
        if not self.log_file.exists():
            return []
        return [line.split(" ") for line in self.log_file.read_text(encoding="utf-8").splitlines()]

    def last_log(self) -> list[str]:
        return self.log_lines()[-1]

    def failure_count(self, event: str) -> int:
        path = self.fail_dir / event
        return int(path.read_text().strip()) if path.exists() else 0

    def state(self, session_id: str) -> Optional[tuple[str, str, int]]:
        path = self.state_dir / session_id
        if not path.exists():
            return None
        run, runtime, heartbeat = path.read_text(encoding="utf-8").split()
        return run, runtime, int(heartbeat)

    def put_state(self, session_id: str, run: str, runtime: str, heartbeat: int) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / session_id).write_text(f"{run} {runtime} {heartbeat}\n", encoding="utf-8", newline="\n")

    def tree_text(self) -> str:
        """Every byte written under TWIN_HOME's hook-debug tree, as text."""
        chunks = []
        for path in sorted(self.state_root.rglob("*")):
            if path.is_file():
                chunks.append(path.name + "\n" + path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(chunks)


# ---------------------------------------------------------------------- stub platform


@dataclass
class Stub:
    """A tiny stand-in for the agent-runtime routes on 127.0.0.1. Responses are queued per
    (method, path); the last queued response repeats. Anything unrouted is a 404."""

    routes: dict = field(default_factory=dict)
    seen: list = field(default_factory=list)
    server: Optional[ThreadingHTTPServer] = None

    def on(self, method: str, path: str, *responses: tuple[int, str]) -> None:
        self.routes[(method, path)] = list(responses)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> "Stub":
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep test output clean
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                stub.seen.append(
                    {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
                )
                queue = stub.routes.get((self.command, self.path))
                status, payload = (404, '{"detail":"no route"}') if not queue else (
                    queue.pop(0) if len(queue) > 1 else queue[0]
                )
                data = payload.encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_PATCH = do_GET = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def bodies(self, method: str, path: str) -> list[dict]:
        return [json.loads(r["body"]) for r in self.seen if r["method"] == method and r["path"] == path and r["body"]]
