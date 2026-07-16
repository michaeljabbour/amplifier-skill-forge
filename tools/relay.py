#!/usr/bin/env python3
"""Deterministic, resumable multi-agent relays over Forge terminal sessions.

The controller keeps orchestration state outside the product repository by
default, generates role-specific prompts, drives existing or newly-created
Forge sessions, and refuses to advance until artifact, marker, and independent
verification gates pass.

Typical flow:
  relay.py init --cwd /repo --tag ticket-123 --goal "..." \
    --implementation-artifact src/widget.py \
    --implementation-artifact tests/test_widget.py --test-command "pytest -q"
  relay.py start planner --state STATE --harness claude
  relay.py send planner --state STATE
  relay.py wait planner --state STATE --attempts 10
  relay.py gate planner --state STATE
  relay.py status --state STATE
"""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


SCHEMA_VERSION = 1
ROLE_ORDER = ["planner", "implementer", "reviewer", "resolver", "acceptor"]
ROLE_DEFAULTS = {
    "planner": {
        "marker": "PLANNER_DONE",
        "artifacts": ["SPEC.md"],
        "allowed_verdicts": [],
        "passing_verdicts": [],
    },
    "implementer": {
        "marker": "IMPLEMENTER_DONE",
        "artifacts": [],
        "allowed_verdicts": [],
        "passing_verdicts": [],
    },
    "reviewer": {
        "marker": "REVIEWER_DONE",
        "artifacts": ["REVIEW.md"],
        "allowed_verdicts": ["PASS", "CHANGES_REQUIRED"],
        "passing_verdicts": ["PASS", "CHANGES_REQUIRED"],
    },
    "resolver": {
        "marker": "RESOLVER_DONE",
        "artifacts": ["RESOLUTION.md"],
        "allowed_verdicts": [],
        "passing_verdicts": [],
    },
    "acceptor": {
        "marker": "ACCEPTOR_DONE",
        "artifacts": ["ACCEPTANCE.md"],
        "allowed_verdicts": ["PASS", "FAIL"],
        "passing_verdicts": ["PASS"],
    },
}
HARNESS_EXECUTABLES = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "amplifier": "amplifier",
    "opencode": "opencode",
}
FORGE_CLIENT = Path(__file__).with_name("forge.py")
DASHBOARD_URL = os.environ.get("FORGE_DASHBOARD_URL", "http://127.0.0.1:3141/")


class RelayError(RuntimeError):
    """A user-actionable relay failure."""


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_tag(tag):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-.")
    if not safe:
        raise RelayError("tag must contain at least one letter or number")
    return safe


def _default_state_path(tag):
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "amplifier-skill-forge" / "relays" / _safe_tag(tag) / "relay.json"


def _state_path(value, tag=None):
    candidate = value or os.environ.get("FORGE_RELAY_STATE")
    if candidate:
        return Path(candidate).expanduser().resolve()
    if tag:
        return _default_state_path(tag).resolve()
    raise RelayError("pass --state PATH or set FORGE_RELAY_STATE")


def _event(state, kind, role=None, **details):
    item = {"at": _now(), "kind": kind}
    if role:
        item["role"] = role
    item.update(details)
    state["events"].append(item)
    state["updated_at"] = item["at"]


def _write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="relay-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_state(path):
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError as exc:
        raise RelayError(f"relay state not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RelayError(f"invalid relay state at {path}: {exc}") from exc
    if state.get("schema_version") != SCHEMA_VERSION:
        raise RelayError(
            f"unsupported relay schema {state.get('schema_version')}; expected {SCHEMA_VERSION}"
        )
    return state


def _workspace(state):
    path = Path(state["workspace"])
    if not path.is_dir():
        raise RelayError(f"workspace no longer exists: {path}")
    return path


def _role(state, role):
    try:
        return state["roles"][role]
    except KeyError as exc:
        raise RelayError(f"unknown role: {role}") from exc


def _artifact_path(workspace, relative):
    value = Path(relative)
    if value.is_absolute():
        raise RelayError(f"artifact paths must be relative to the workspace: {relative}")
    resolved = (workspace / value).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError as exc:
        raise RelayError(f"artifact escapes the workspace: {relative}") from exc
    return resolved


def _validate_artifacts(workspace, artifacts):
    if not artifacts:
        raise RelayError("at least one implementation artifact is required")
    normalized = []
    for artifact in artifacts:
        _artifact_path(workspace, artifact)
        if artifact not in normalized:
            normalized.append(artifact)
    return normalized


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_shell():
    candidates = [os.environ.get("SHELL"), shutil.which("bash"), shutil.which("sh"), "/bin/sh"]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RelayError("no executable shell found for verification commands")


def _run_verification(command, workspace, timeout):
    try:
        completed = subprocess.run(
            [_resolve_shell(), "-lc", command],
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "output": (completed.stdout + completed.stderr)[-12000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "command": command,
            "exit_code": None,
            "output": (stdout + stderr)[-12000:],
            "timed_out": True,
        }


def _run_forge(arguments, timeout=45, check=True):
    client = Path(os.environ.get("FORGE_CLIENT", FORGE_CLIENT)).expanduser()
    if not client.is_file():
        raise RelayError(f"Forge client not found: {client}")
    try:
        completed = subprocess.run(
            [sys.executable, str(client), *arguments],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RelayError(f"Forge command timed out: {' '.join(arguments)}") from exc
    if check and completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RelayError(detail or f"Forge command failed: {' '.join(arguments)}")
    return completed


def _prior_roles_passed(state, role):
    position = state["role_order"].index(role)
    return [name for name in state["role_order"][:position]
            if state["roles"][name]["status"] != "passed"]


def _marker_instruction(marker):
    tokens = marker.split("_")
    spaced = " _ ".join(tokens)
    return (
        f"After the artifact is complete and checks pass, reply with the concatenation of "
        f"{spaced}, with no spaces. Do not write that concatenated token in any file."
    )


def _artifact_list(items):
    return ", ".join(f"`{item}`" for item in items)


def _build_prompt(state, role):
    info = _role(state, role)
    goal = state["goal"]
    test_command = state["test_command"]
    implementation = state["roles"]["implementer"]["artifacts"]
    marker = _marker_instruction(info["marker"])
    common = (
        f"You are the {role} in an artifact-gated relay. Work in {state['workspace']}.\n"
        f"Goal: {goal}\n"
    )

    if role == "planner":
        body = (
            "Create only `SPEC.md`. Define scope, exact behavior, edge cases, owned "
            f"implementation files ({_artifact_list(implementation)}), and acceptance commands. "
            "Do not implement the solution."
        )
    elif role == "implementer":
        body = (
            "Read `SPEC.md` completely and do not modify it. Implement the solution and tests "
            f"using the declared files: {_artifact_list(implementation)}. Run `{test_command}` "
            "and release only after it passes."
        )
    elif role == "reviewer":
        body = (
            "Independently read `SPEC.md` and the implementation files "
            f"({_artifact_list(implementation)}). Run `{test_command}` plus focused edge probes. "
            "Modify no existing artifact. Create only `REVIEW.md` with a standalone line "
            "`Verdict: PASS` or `Verdict: CHANGES_REQUIRED`, commands and observed evidence, "
            "severity-ranked findings, and repository-debris and scope checks."
        )
    elif role == "resolver":
        body = (
            "Read `SPEC.md` and `REVIEW.md`. Resolve every review finding explicitly. You may "
            f"modify only the implementation files ({_artifact_list(implementation)}) and must "
            f"create `RESOLUTION.md`. Run `{test_command}`. Preserve the spec and review."
        )
    else:
        body = (
            "Act as the independent final acceptor. Read `SPEC.md`, `REVIEW.md`, "
            "`RESOLUTION.md`, and every implementation file directly. Modify no earlier artifact. "
            f"Verify the frozen spec hash and run `{test_command}` plus all spec acceptance "
            "commands. Check scope and debris. Create only `ACCEPTANCE.md` with a standalone "
            "line `Verdict: PASS` or `Verdict: FAIL`, evidence, hashes, remaining risks, and the "
            "complete role chain."
        )
    return f"{common}{body}\n{marker}"


def _extract_verdict(path, allowed):
    if not allowed:
        return None
    pattern = re.compile(
        r"^\s*(?:#+\s*)?(?:verdict\s*:\s*)?\*{0,2}("
        + "|".join(map(re.escape, allowed))
        + r")\*{0,2}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = {match.upper() for match in pattern.findall(path.read_text(encoding="utf-8"))}
    if len(matches) != 1:
        return None
    return matches.pop()


def _check_marker(info):
    if info.get("marker_seen"):
        return True, "recorded by wait"
    if not info.get("session_id"):
        return False, "no session registered"
    completed = _run_forge(
        ["grep", info["session_id"], info["marker"], "--max", "5"],
        timeout=45,
        check=False,
    )
    output = completed.stdout + completed.stderr
    return completed.returncode == 0 and info["marker"] in output, output.strip()


def command_init(args):
    workspace = Path(args.cwd).expanduser().resolve()
    if not workspace.is_dir():
        raise RelayError(f"workspace is not a directory: {workspace}")
    implementation = _validate_artifacts(workspace, args.implementation_artifact)
    path = _state_path(args.state, args.tag)
    if path.exists() and not args.force:
        raise RelayError(f"relay state already exists: {path}; pass --force to replace it")

    now = _now()
    roles = {}
    verification = {
        "planner": args.planner_command,
        "implementer": args.test_command,
        "reviewer": args.reviewer_command or args.test_command,
        "resolver": args.resolver_command or args.test_command,
        "acceptor": args.acceptor_command or args.test_command,
    }
    for role in ROLE_ORDER:
        defaults = ROLE_DEFAULTS[role]
        artifacts = implementation if role == "implementer" else list(defaults["artifacts"])
        roles[role] = {
            "allowed_verdicts": list(defaults["allowed_verdicts"]),
            "artifacts": artifacts,
            "attempts": 0,
            "cost_usd": 0.0,
            "gates": {},
            "harness": None,
            "marker": defaults["marker"],
            "marker_seen": False,
            "passing_verdicts": list(defaults["passing_verdicts"]),
            "sandbox": None,
            "session_id": None,
            "status": "pending",
            "verification_command": verification[role],
            "verdict": None,
        }
    state = {
        "closed_at": None,
        "created_at": now,
        "events": [],
        "goal": args.goal,
        "id": uuid.uuid4().hex,
        "role_order": list(ROLE_ORDER),
        "roles": roles,
        "schema_version": SCHEMA_VERSION,
        "spec_sha256": None,
        "tag": _safe_tag(args.tag),
        "test_command": args.test_command,
        "updated_at": now,
        "workspace": str(workspace),
    }
    _event(state, "relay_initialized", state_path=str(path))
    _write_state(path, state)
    print(path)


def command_preflight(args, path, state):
    workspace = _workspace(state)
    doctor = _run_forge(["doctor"], timeout=90, check=False)
    git = shutil.which("git")
    git_workspace = False
    if git:
        git_workspace = subprocess.run(
            [git, "-C", str(workspace), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        ).returncode == 0
    checks = {
        "forge": doctor.returncode == 0,
        "git": git is not None,
        "git_workspace": git_workspace,
    }
    harnesses = args.harness or sorted({
        role["harness"] for role in state["roles"].values() if role.get("harness")
    })
    for harness in harnesses:
        checks[f"executable:{harness}"] = shutil.which(HARNESS_EXECUTABLES[harness]) is not None
    _event(state, "preflight", checks=checks)
    _write_state(path, state)
    print(json.dumps({"checks": checks, "dashboard": DASHBOARD_URL}, indent=2))
    if not all(checks.values()):
        return 1
    return 0


def command_session(args, path, state):
    info = _role(state, args.role)
    if args.marker:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", args.marker):
            raise RelayError("--marker must be 3-64 uppercase letters, digits, or underscores")
        info["marker"] = args.marker
    info["session_id"] = args.session_id
    info["harness"] = args.harness
    if info["status"] == "pending":
        info["status"] = "ready"
    _event(
        state,
        "session_registered",
        args.role,
        session_id=args.session_id,
        harness=args.harness,
        marker=info["marker"],
    )
    _write_state(path, state)
    print(f"{args.role}: {args.session_id} ({args.harness})")
    return 0


def command_start(args, path, state):
    info = _role(state, args.role)
    if info.get("session_id") and not args.replace:
        raise RelayError(
            f"{args.role} already has session {info['session_id']}; pass --replace to register a new one"
        )
    if info.get("session_id") and args.replace:
        old_session = info["session_id"]
        _run_forge(["close", old_session], timeout=45, check=False)
        _event(state, "session_replaced", args.role, old_session_id=old_session)
    executable = HARNESS_EXECUTABLES[args.harness]
    resolved = shutil.which(executable)
    if not resolved:
        raise RelayError(f"{executable} is not installed or is not on PATH")
    name = f"{state['tag']}-{args.harness}-{args.role}"
    common = ["--cwd", state["workspace"], "--name", name, "--tag", state["tag"], "--tag", args.harness]
    if args.harness == "codex":
        if not args.sandbox:
            raise RelayError(
                "Codex sessions require --sandbox read-only|workspace-write|danger-full-access"
            )
        completed = _run_forge(
            [
                "new", *common, "--program", resolved,
                f"--arg=--sandbox", f"--arg={args.sandbox}",
            ],
            timeout=90,
        )
    elif args.sandbox:
        raise RelayError("--sandbox is supported only for Codex sessions")
    elif args.harness in ("claude", "gemini"):
        completed = _run_forge([f"spawn-{args.harness}", *common], timeout=90)
    else:
        completed = _run_forge(
            ["new", *common, "--program", resolved],
            timeout=90,
        )
    session_id = completed.stdout.strip().splitlines()[-1]
    if not session_id:
        raise RelayError(f"Forge did not return a session id for {args.role}")
    info.update({
        "session_id": session_id,
        "harness": args.harness,
        "sandbox": args.sandbox,
        "status": "ready",
    })
    _event(
        state,
        "session_started",
        args.role,
        session_id=session_id,
        harness=args.harness,
        sandbox=args.sandbox,
    )
    _write_state(path, state)
    print(json.dumps({"role": args.role, "session_id": session_id, "dashboard": DASHBOARD_URL}, indent=2))
    if not args.no_screen:
        time.sleep(args.settle)
        screen = _run_forge(["screen", session_id], timeout=45, check=False)
        print("\nInitial screen (resolve any trust/auth/update gate before `send`):")
        print(screen.stdout or screen.stderr)
    return 0


def command_prompt(args, state):
    print(_build_prompt(state, args.role))
    return 0


def command_send(args, path, state):
    info = _role(state, args.role)
    blocked = _prior_roles_passed(state, args.role)
    if blocked:
        raise RelayError(f"cannot send {args.role}; incomplete predecessors: {', '.join(blocked)}")
    if not info.get("session_id") or not info.get("harness"):
        raise RelayError(f"register or start a session for {args.role} first")
    prompt = _build_prompt(state, args.role)
    if info["harness"] == "claude":
        _run_forge(["submit", info["session_id"], prompt], timeout=90)
    else:
        _run_forge(["type", info["session_id"], prompt, "--no-newline"], timeout=90)
        time.sleep(0.4)
        _run_forge(["key", info["session_id"], "enter"], timeout=90)
    info["status"] = "running"
    info["attempts"] += 1
    info["marker_seen"] = False
    _event(state, "prompt_sent", args.role, session_id=info["session_id"], attempt=info["attempts"])
    _write_state(path, state)
    if not args.no_screen:
        time.sleep(args.screen_wait)
        screen = _run_forge(["screen", info["session_id"]], timeout=45, check=False)
        print(screen.stdout or screen.stderr)
    return 0


def command_wait(args, path, state):
    info = _role(state, args.role)
    if not info.get("session_id"):
        raise RelayError(f"no session registered for {args.role}")
    if args.timeout > 29000:
        raise RelayError("--timeout must be at most 29000ms; increase --attempts for longer waits")
    for attempt in range(1, args.attempts + 1):
        completed = _run_forge(
            ["wait", info["session_id"], info["marker"], "--timeout", str(args.timeout)],
            timeout=(args.timeout / 1000) + 20,
            check=False,
        )
        if completed.returncode == 0:
            info["marker_seen"] = True
            _event(state, "marker_seen", args.role, wait_attempt=attempt)
            _write_state(path, state)
            print(completed.stdout.strip())
            return 0
        screen = _run_forge(["screen", info["session_id"]], timeout=45, check=False)
        print(
            f"relay: {args.role} wait {attempt}/{args.attempts} timed out; current screen:\n"
            f"{screen.stdout or screen.stderr}",
            file=sys.stderr,
        )
    _event(state, "marker_timeout", args.role, attempts=args.attempts)
    _write_state(path, state)
    return 1


def command_gate(args, path, state):
    info = _role(state, args.role)
    workspace = _workspace(state)
    blocked = _prior_roles_passed(state, args.role)
    gates = {
        "predecessors": {"passed": not blocked, "incomplete": blocked},
        "artifacts": {"passed": True, "files": {}},
        "marker": {"passed": False, "detail": "not checked"},
        "spec_hash": {"passed": True, "expected": state.get("spec_sha256"), "actual": None},
        "verification": {"passed": False},
        "verdict": {"passed": True, "value": None},
    }

    for artifact in info["artifacts"]:
        artifact_path = _artifact_path(workspace, artifact)
        passed = artifact_path.is_file() and artifact_path.stat().st_size > 0
        entry = {"passed": passed}
        if passed:
            entry.update({"bytes": artifact_path.stat().st_size, "sha256": _hash_file(artifact_path)})
        gates["artifacts"]["files"][artifact] = entry
        gates["artifacts"]["passed"] = gates["artifacts"]["passed"] and passed

    marker_passed, marker_detail = _check_marker(info)
    gates["marker"] = {"passed": marker_passed, "detail": marker_detail[-2000:]}

    spec_path = _artifact_path(workspace, "SPEC.md")
    if args.role != "planner" and state.get("spec_sha256"):
        actual = _hash_file(spec_path) if spec_path.is_file() else None
        gates["spec_hash"]["actual"] = actual
        gates["spec_hash"]["passed"] = actual == state["spec_sha256"]

    verification = _run_verification(info["verification_command"], workspace, args.timeout)
    verification["passed"] = verification["exit_code"] == 0 and not verification["timed_out"]
    gates["verification"] = verification

    if info["allowed_verdicts"] and gates["artifacts"]["passed"]:
        verdict_path = _artifact_path(workspace, info["artifacts"][0])
        verdict = _extract_verdict(verdict_path, info["allowed_verdicts"])
        info["verdict"] = verdict
        gates["verdict"] = {
            "passed": verdict in info["passing_verdicts"],
            "value": verdict,
            "allowed": info["allowed_verdicts"],
        }

    passed = all(gate["passed"] for gate in gates.values())
    if passed and args.role == "planner":
        state["spec_sha256"] = gates["artifacts"]["files"]["SPEC.md"]["sha256"]
        gates["spec_hash"] = {
            "passed": True,
            "expected": state["spec_sha256"],
            "actual": state["spec_sha256"],
        }
    info["gates"] = gates
    info["status"] = "passed" if passed else "blocked"
    _event(state, "gate_passed" if passed else "gate_blocked", args.role)
    _write_state(path, state)
    print(json.dumps({"role": args.role, "passed": passed, "gates": gates}, indent=2))
    return 0 if passed else 1


def command_cost(args, path, state):
    if args.usd < 0:
        raise RelayError("cost cannot be negative")
    info = _role(state, args.role)
    info["cost_usd"] = round(info["cost_usd"] + args.usd, 6)
    _event(state, "cost_recorded", args.role, usd=args.usd, total_usd=info["cost_usd"])
    _write_state(path, state)
    print(f"{args.role}: ${info['cost_usd']:.4f}")
    return 0


def _next_role(state):
    for role in state["role_order"]:
        if state["roles"][role]["status"] != "passed":
            return role
    return None


def command_status(args, path, state):
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    print(f"Relay: {state['tag']}\nState: {path}\nWorkspace: {state['workspace']}")
    print(f"Dashboard: {DASHBOARD_URL}\nSpec SHA-256: {state.get('spec_sha256') or '-'}")
    print("\nROLE         STATUS    HARNESS     SESSION       VERDICT            COST")
    for role in state["role_order"]:
        info = state["roles"][role]
        print(
            f"{role:<12} {info['status']:<9} {(info.get('harness') or '-'):<11} "
            f"{(info.get('session_id') or '-')[:13]:<13} {(info.get('verdict') or '-'):<18} "
            f"${info['cost_usd']:.4f}"
        )
    print(f"\nNext role: {_next_role(state) or 'complete'}")
    return 0


def _evidence_markdown(state, state_path):
    lines = [
        f"# Relay evidence: {state['tag']}",
        "",
        f"- Goal: {state['goal']}",
        f"- Workspace: `{state['workspace']}`",
        f"- State ledger: `{state_path}`",
        f"- Updated: {state['updated_at']}",
        f"- Frozen SPEC.md SHA-256: `{state.get('spec_sha256') or 'not frozen'}`",
        f"- Test command: `{state['test_command']}`",
        f"- Forge dashboard: {DASHBOARD_URL}",
        "",
        "| Role | Harness | Session | Status | Verdict | Cost |",
        "|---|---|---|---|---|---:|",
    ]
    for role in state["role_order"]:
        info = state["roles"][role]
        lines.append(
            f"| {role} | {info.get('harness') or '-'} | `{info.get('session_id') or '-'}` | "
            f"{info['status']} | {info.get('verdict') or '-'} | ${info['cost_usd']:.4f} |"
        )
    lines.extend(["", "## Artifact hashes", ""])
    for role in state["role_order"]:
        files = state["roles"][role].get("gates", {}).get("artifacts", {}).get("files", {})
        for name, details in files.items():
            lines.append(f"- `{name}`: `{details.get('sha256', 'missing')}`")
    lines.extend(["", "## Verification", ""])
    for role in state["role_order"]:
        verification = state["roles"][role].get("gates", {}).get("verification", {})
        lines.append(
            f"- {role}: exit `{verification.get('exit_code', 'not run')}` — "
            f"`{state['roles'][role]['verification_command']}`"
        )
    total = sum(role["cost_usd"] for role in state["roles"].values())
    lines.extend(["", f"Total recorded cost: **${total:.4f}**", ""])
    return "\n".join(lines)


def command_evidence(args, path, state):
    output = Path(args.output).expanduser().resolve() if args.output else path.with_name("EVIDENCE.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_evidence_markdown(state, path), encoding="utf-8")
    _event(state, "evidence_written", output=str(output))
    _write_state(path, state)
    print(output)
    return 0


def command_close(args, path, state):
    completed = _run_forge(["close-tag", state["tag"]], timeout=90, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RelayError(detail or f"could not close Forge tag {state['tag']}")
    state["closed_at"] = _now()
    _event(state, "sessions_closed")
    _write_state(path, state)
    print(f"closed Forge sessions tagged {state['tag']}")
    return 0


def _add_state_argument(parser):
    parser.add_argument("--state", help="relay.json path (or set FORGE_RELAY_STATE)")


def build_parser():
    parser = argparse.ArgumentParser(prog="relay.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a durable relay ledger")
    init.add_argument("--cwd", required=True)
    init.add_argument("--tag", required=True)
    init.add_argument("--goal", required=True)
    init.add_argument("--implementation-artifact", action="append", required=True)
    init.add_argument("--test-command", required=True)
    init.add_argument("--planner-command", default="test -s SPEC.md")
    init.add_argument("--reviewer-command")
    init.add_argument("--resolver-command")
    init.add_argument("--acceptor-command")
    init.add_argument("--state")
    init.add_argument("--force", action="store_true")

    preflight = sub.add_parser("preflight", help="check Forge, Git, and harness executables")
    _add_state_argument(preflight)
    preflight.add_argument("--harness", action="append", choices=sorted(HARNESS_EXECUTABLES))

    session = sub.add_parser("session", help="register an existing Forge session")
    session.add_argument("role", choices=ROLE_ORDER)
    session.add_argument("session_id")
    session.add_argument("--harness", required=True, choices=sorted(HARNESS_EXECUTABLES))
    session.add_argument("--marker", help="override the completion marker for an existing session")
    _add_state_argument(session)

    start = sub.add_parser("start", help="start and register a role session")
    start.add_argument("role", choices=ROLE_ORDER)
    start.add_argument("--harness", required=True, choices=sorted(HARNESS_EXECUTABLES))
    start.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="required for Codex; passed explicitly to the interactive CLI",
    )
    start.add_argument("--replace", action="store_true")
    start.add_argument("--settle", type=float, default=2.0)
    start.add_argument("--no-screen", action="store_true")
    _add_state_argument(start)

    prompt = sub.add_parser("prompt", help="print the deterministic prompt for a role")
    prompt.add_argument("role", choices=ROLE_ORDER)
    _add_state_argument(prompt)

    send = sub.add_parser("send", help="send a role prompt to its registered session")
    send.add_argument("role", choices=ROLE_ORDER)
    send.add_argument("--no-screen", action="store_true")
    send.add_argument("--screen-wait", type=float, default=1.5)
    _add_state_argument(send)

    wait = sub.add_parser("wait", help="wait in bounded loops for a role marker")
    wait.add_argument("role", choices=ROLE_ORDER)
    wait.add_argument("--attempts", type=int, default=1)
    wait.add_argument("--timeout", type=int, default=29000)
    _add_state_argument(wait)

    gate = sub.add_parser("gate", help="enforce artifact, marker, hash, verdict, and test gates")
    gate.add_argument("role", choices=ROLE_ORDER)
    gate.add_argument("--timeout", type=int, default=300)
    _add_state_argument(gate)

    cost = sub.add_parser("cost", help="add a provider cost to a role")
    cost.add_argument("role", choices=ROLE_ORDER)
    cost.add_argument("--usd", type=float, required=True)
    _add_state_argument(cost)

    status = sub.add_parser("status", help="show resumable relay state")
    status.add_argument("--json", action="store_true")
    _add_state_argument(status)

    evidence = sub.add_parser("evidence", help="write a Markdown evidence report")
    evidence.add_argument("--output", help="default: EVIDENCE.md next to relay.json")
    _add_state_argument(evidence)

    close = sub.add_parser("close", help="close all sessions tagged for this relay")
    _add_state_argument(close)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            command_init(args)
            return 0
        path = _state_path(args.state)
        state = _load_state(path)
        handlers = {
            "preflight": command_preflight,
            "session": command_session,
            "start": command_start,
            "send": command_send,
            "wait": command_wait,
            "gate": command_gate,
            "cost": command_cost,
            "status": command_status,
            "evidence": command_evidence,
            "close": command_close,
        }
        if args.command == "prompt":
            return command_prompt(args, state)
        return handlers[args.command](args, path, state)
    except RelayError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
