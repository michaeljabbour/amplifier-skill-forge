import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("relay_controller", ROOT / "tools" / "relay.py")
RELAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELAY)


class RelayControllerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        self.state_path = self.root / "state" / "relay.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def run_cli(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = RELAY.main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def initialize(self, test_command="python3 -c 'raise SystemExit(0)'"):
        code, output, error = self.run_cli(
            "init",
            "--cwd", str(self.workspace),
            "--tag", "unit-relay",
            "--goal", "Build and independently verify a tiny utility",
            "--implementation-artifact", "solution.py",
            "--implementation-artifact", "test_solution.py",
            "--test-command", test_command,
            "--state", str(self.state_path),
        )
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(Path(output.strip()), self.state_path)
        return RELAY._load_state(self.state_path)

    def mark_ready(self, role):
        state = RELAY._load_state(self.state_path)
        info = state["roles"][role]
        info.update({
            "harness": "codex",
            "marker_seen": True,
            "session_id": f"session-{role}",
            "status": "running",
        })
        RELAY._write_state(self.state_path, state)

    def test_init_writes_private_resumable_state_outside_workspace(self):
        state = self.initialize()

        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["role_order"], RELAY.ROLE_ORDER)
        self.assertEqual(
            state["roles"]["implementer"]["artifacts"],
            ["solution.py", "test_solution.py"],
        )
        self.assertEqual(self.state_path.stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(self.state_path.parent, self.workspace)

    def test_role_prompts_are_specific_and_do_not_leak_literal_markers(self):
        self.initialize()
        for role in RELAY.ROLE_ORDER:
            code, output, error = self.run_cli(
                "prompt", role, "--state", str(self.state_path)
            )
            self.assertEqual((code, error), (0, ""))
            self.assertIn(f"You are the {role}", output)
            self.assertNotIn(RELAY.ROLE_DEFAULTS[role]["marker"], output)

        _, reviewer, _ = self.run_cli("prompt", "reviewer", "--state", str(self.state_path))
        self.assertIn("Modify no existing artifact", reviewer)
        self.assertIn("Verdict: CHANGES_REQUIRED", reviewer)

    def test_existing_session_can_register_a_compatible_marker(self):
        self.initialize()

        code, _, error = self.run_cli(
            "session", "resolver", "existing-id", "--harness", "codex",
            "--marker", "RESOLUTION_DONE", "--state", str(self.state_path),
        )

        self.assertEqual((code, error), (0, ""))
        resolver = RELAY._load_state(self.state_path)["roles"]["resolver"]
        self.assertEqual(resolver["marker"], "RESOLUTION_DONE")
        self.assertEqual(resolver["session_id"], "existing-id")

    def test_verdict_parser_accepts_heading_followed_by_markdown_bold_value(self):
        review = self.workspace / "REVIEW.md"
        review.write_text("## Verdict\n\n**PASS**\n", encoding="utf-8")

        verdict = RELAY._extract_verdict(review, ["PASS", "CHANGES_REQUIRED"])

        self.assertEqual(verdict, "PASS")

    def test_send_refuses_to_skip_incomplete_predecessors(self):
        self.initialize()
        code, _, error = self.run_cli("send", "implementer", "--state", str(self.state_path))

        self.assertEqual(code, 2)
        self.assertIn("incomplete predecessors: planner", error)

    def test_codex_start_requires_and_passes_explicit_sandbox(self):
        self.initialize()
        with mock.patch.object(RELAY.shutil, "which", return_value="/usr/bin/codex"), \
                mock.patch.object(RELAY, "_run_forge") as forge:
            code, _, error = self.run_cli(
                "start", "planner", "--harness", "codex", "--no-screen",
                "--state", str(self.state_path),
            )
        self.assertEqual(code, 2)
        self.assertIn("require --sandbox", error)
        forge.assert_not_called()

        completed = subprocess.CompletedProcess([], 0, stdout="safe-session\n", stderr="")
        with mock.patch.object(RELAY.shutil, "which", return_value="/usr/bin/codex"), \
                mock.patch.object(RELAY, "_run_forge", return_value=completed) as forge:
            code, _, error = self.run_cli(
                "start", "planner", "--harness", "codex",
                "--sandbox", "workspace-write", "--no-screen",
                "--state", str(self.state_path),
            )

        self.assertEqual((code, error), (0, ""))
        arguments = forge.call_args.args[0]
        self.assertEqual(arguments[0], "new")
        self.assertIn("--arg=--sandbox", arguments)
        self.assertIn("--arg=workspace-write", arguments)
        planner = RELAY._load_state(self.state_path)["roles"]["planner"]
        self.assertEqual(planner["sandbox"], "workspace-write")

    def test_gate_requires_marker_even_when_artifact_and_command_pass(self):
        self.initialize()
        (self.workspace / "SPEC.md").write_text("# Spec\n", encoding="utf-8")
        state = RELAY._load_state(self.state_path)
        state["roles"]["planner"]["session_id"] = "planner-session"
        RELAY._write_state(self.state_path, state)

        with mock.patch.object(
            RELAY,
            "_run_forge",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ):
            code, output, _ = self.run_cli(
                "gate", "planner", "--state", str(self.state_path)
            )

        self.assertEqual(code, 1)
        result = json.loads(output)
        self.assertTrue(result["gates"]["artifacts"]["passed"])
        self.assertTrue(result["gates"]["verification"]["passed"])
        self.assertFalse(result["gates"]["marker"]["passed"])

    def test_full_relay_freezes_spec_and_passes_all_roles(self):
        self.initialize()

        (self.workspace / "SPEC.md").write_text("# Frozen spec\n", encoding="utf-8")
        self.mark_ready("planner")
        self.assertEqual(
            self.run_cli("gate", "planner", "--state", str(self.state_path))[0], 0
        )
        frozen = RELAY._load_state(self.state_path)["spec_sha256"]
        self.assertTrue(frozen)

        (self.workspace / "solution.py").write_text("ANSWER = 42\n", encoding="utf-8")
        (self.workspace / "test_solution.py").write_text(
            "from solution import ANSWER\nassert ANSWER == 42\n", encoding="utf-8"
        )
        self.mark_ready("implementer")
        self.assertEqual(
            self.run_cli("gate", "implementer", "--state", str(self.state_path))[0], 0
        )

        (self.workspace / "REVIEW.md").write_text(
            "# Review\n\nVerdict: PASS\n\nIndependent checks passed.\n", encoding="utf-8"
        )
        self.mark_ready("reviewer")
        self.assertEqual(
            self.run_cli("gate", "reviewer", "--state", str(self.state_path))[0], 0
        )

        (self.workspace / "RESOLUTION.md").write_text(
            "# Resolution\n\nNo corrective findings; checks rerun.\n", encoding="utf-8"
        )
        self.mark_ready("resolver")
        self.assertEqual(
            self.run_cli("gate", "resolver", "--state", str(self.state_path))[0], 0
        )

        (self.workspace / "ACCEPTANCE.md").write_text(
            "# Acceptance\n\nVerdict: PASS\n\nFrozen hash verified.\n", encoding="utf-8"
        )
        self.mark_ready("acceptor")
        self.assertEqual(
            self.run_cli("gate", "acceptor", "--state", str(self.state_path))[0], 0
        )

        state = RELAY._load_state(self.state_path)
        self.assertEqual(RELAY._next_role(state), None)
        self.assertTrue(all(role["status"] == "passed" for role in state["roles"].values()))

    def test_mutating_frozen_spec_blocks_later_role(self):
        self.initialize()
        (self.workspace / "SPEC.md").write_text("version one\n", encoding="utf-8")
        self.mark_ready("planner")
        self.assertEqual(
            self.run_cli("gate", "planner", "--state", str(self.state_path))[0], 0
        )
        (self.workspace / "solution.py").write_text("ANSWER = 42\n", encoding="utf-8")
        (self.workspace / "test_solution.py").write_text("assert True\n", encoding="utf-8")
        (self.workspace / "SPEC.md").write_text("version two\n", encoding="utf-8")
        self.mark_ready("implementer")

        code, output, _ = self.run_cli(
            "gate", "implementer", "--state", str(self.state_path)
        )

        self.assertEqual(code, 1)
        result = json.loads(output)
        self.assertFalse(result["gates"]["spec_hash"]["passed"])

    def test_reviewer_changes_required_is_a_completed_review_gate(self):
        self.initialize()
        state = RELAY._load_state(self.state_path)
        state["roles"]["planner"]["status"] = "passed"
        state["roles"]["implementer"]["status"] = "passed"
        state["spec_sha256"] = "placeholder"
        RELAY._write_state(self.state_path, state)
        (self.workspace / "SPEC.md").write_text("spec\n", encoding="utf-8")
        state = RELAY._load_state(self.state_path)
        state["spec_sha256"] = RELAY._hash_file(self.workspace / "SPEC.md")
        RELAY._write_state(self.state_path, state)
        (self.workspace / "REVIEW.md").write_text(
            "Verdict: CHANGES_REQUIRED\n\n- Fix the edge case.\n", encoding="utf-8"
        )
        self.mark_ready("reviewer")

        code, _, _ = self.run_cli("gate", "reviewer", "--state", str(self.state_path))

        self.assertEqual(code, 0)
        reviewer = RELAY._load_state(self.state_path)["roles"]["reviewer"]
        self.assertEqual(reviewer["status"], "passed")
        self.assertEqual(reviewer["verdict"], "CHANGES_REQUIRED")

    def test_acceptance_fail_does_not_complete_relay(self):
        self.initialize()
        state = RELAY._load_state(self.state_path)
        for role in RELAY.ROLE_ORDER[:-1]:
            state["roles"][role]["status"] = "passed"
        (self.workspace / "SPEC.md").write_text("spec\n", encoding="utf-8")
        state["spec_sha256"] = RELAY._hash_file(self.workspace / "SPEC.md")
        RELAY._write_state(self.state_path, state)
        (self.workspace / "ACCEPTANCE.md").write_text(
            "Verdict: FAIL\n\nTest evidence is incomplete.\n", encoding="utf-8"
        )
        self.mark_ready("acceptor")

        code, output, _ = self.run_cli("gate", "acceptor", "--state", str(self.state_path))

        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["gates"]["verdict"]["passed"])
        self.assertEqual(RELAY._load_state(self.state_path)["roles"]["acceptor"]["status"], "blocked")

    def test_wait_retries_bounded_timeouts_and_records_marker(self):
        self.initialize()
        self.mark_ready("planner")
        responses = [
            subprocess.CompletedProcess([], 1, stdout='{"matched": false}', stderr=""),
            subprocess.CompletedProcess([], 0, stdout='{"matched": true}', stderr=""),
        ]

        def forge(arguments, **_kwargs):
            if arguments[0] == "screen":
                return subprocess.CompletedProcess([], 0, stdout="working", stderr="")
            return responses.pop(0)

        with mock.patch.object(RELAY, "_run_forge", side_effect=forge):
            code, _, error = self.run_cli(
                "wait", "planner", "--attempts", "2", "--timeout", "100",
                "--state", str(self.state_path),
            )

        self.assertEqual(code, 0)
        self.assertIn("wait 1/2 timed out", error)
        self.assertTrue(RELAY._load_state(self.state_path)["roles"]["planner"]["marker_seen"])

    def test_evidence_defaults_next_to_private_ledger(self):
        self.initialize()

        code, output, error = self.run_cli("evidence", "--state", str(self.state_path))

        self.assertEqual((code, error), (0, ""))
        evidence = Path(output.strip())
        self.assertEqual(evidence, self.state_path.with_name("EVIDENCE.md"))
        body = evidence.read_text(encoding="utf-8")
        self.assertIn("# Relay evidence: unit-relay", body)
        self.assertIn("| planner |", body)


if __name__ == "__main__":
    unittest.main()
