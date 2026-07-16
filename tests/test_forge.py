import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("forge_client", ROOT / "tools" / "forge.py")
FORGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FORGE)


class ForgeClientTests(unittest.TestCase):
    def run_main(self, argv, response=None):
        response = response or {"output": "ok", "exitCode": 0}
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["forge.py", *argv]), \
                mock.patch.object(FORGE, "call", return_value=response) as call, \
                contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exited:
                FORGE.main()
        self.assertEqual(exited.exception.code, 0)
        return call, stdout.getvalue()

    def test_codex_exec_defaults_to_read_only_and_current_directory(self):
        with mock.patch.object(FORGE, "_require_executable", return_value="/usr/bin/codex"):
            call, output = self.run_main(["codex-exec", "review this diff"])

        tool, payload = call.call_args.args
        self.assertEqual(tool, "run_command")
        self.assertEqual(payload["command"], "/usr/bin/codex")
        self.assertEqual(payload["args"], ["exec", "--sandbox", "read-only", "review this diff"])
        self.assertEqual(payload["cwd"], os.getcwd())
        self.assertEqual(output.strip(), "ok")

    def test_codex_exec_passes_explicit_permissions_and_flags(self):
        with mock.patch.object(FORGE, "_require_executable", return_value="/usr/bin/codex"):
            call, _ = self.run_main([
                "codex-exec", "fix it", "--cwd", "/tmp", "--sandbox", "workspace-write",
                "--model", "test-model", "--skip-git-repo-check", "--ephemeral", "--json",
            ])

        payload = call.call_args.args[1]
        self.assertEqual(payload["cwd"], "/tmp")
        self.assertEqual(payload["args"], [
            "exec", "--sandbox", "workspace-write", "--model", "test-model",
            "--skip-git-repo-check", "--ephemeral", "--json", "fix it",
        ])

    def test_exec_uses_resolved_portable_shell(self):
        with mock.patch.object(FORGE, "_resolve_shell", return_value="/bin/sh"):
            call, _ = self.run_main(["exec", "printf ok", "--cwd", "/tmp"])

        payload = call.call_args.args[1]
        self.assertEqual(payload["command"], "/bin/sh")
        self.assertEqual(payload["args"], ["-lc", "printf ok"])
        self.assertEqual(payload["cwd"], "/tmp")

    def test_shell_resolution_falls_back_to_posix_sh(self):
        def which(name):
            return "/bin/sh" if name == "sh" else None

        with mock.patch.dict(os.environ, {"SHELL": "/missing/shell"}), \
                mock.patch.object(FORGE.shutil, "which", side_effect=which):
            self.assertEqual(FORGE._resolve_shell(), "/bin/sh")

    def test_calls_use_distinct_json_rpc_ids(self):
        seen_ids = []

        def post(payload, _sid):
            seen_ids.append(payload["id"])
            return ({
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": "{}"}]},
            }, None)

        with mock.patch.object(FORGE, "_sid", return_value="session"), \
                mock.patch.object(FORGE, "_post", side_effect=post):
            FORGE.call("read_screen", {"id": "claude"})
            FORGE.call("read_screen", {"id": "codex"})

        self.assertEqual(len(seen_ids), 2)
        self.assertNotEqual(seen_ids[0], seen_ids[1])

    def test_submit_separates_text_escape_and_enter(self):
        with mock.patch.object(sys, "argv", ["forge.py", "submit", "session", "hello"]), \
                mock.patch.object(FORGE, "call") as call, \
                mock.patch.object(FORGE.time, "sleep"):
            FORGE.main()

        self.assertEqual(call.call_args_list, [
            mock.call("write_terminal", {"id": "session", "input": "hello", "newline": False}),
            mock.call("send_control", {"id": "session", "key": "escape"}),
            mock.call("send_control", {"id": "session", "key": "enter"}),
        ])

    def test_new_accepts_repeated_literal_program_arguments(self):
        stdout = io.StringIO()
        argv = [
            "forge.py", "new", "--cwd", "/tmp", "--program", "/usr/bin/codex",
            "--arg=--sandbox", "--arg=workspace-write",
        ]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(FORGE, "call", return_value={"id": "safe-codex"}) as call, \
                contextlib.redirect_stdout(stdout):
            FORGE.main()

        self.assertEqual(call.call_args.args, (
            "create_terminal",
            {
                "cols": 120,
                "rows": 36,
                "cwd": "/tmp",
                "command": "/usr/bin/codex",
                "args": ["--sandbox", "workspace-write"],
            },
        ))
        self.assertEqual(stdout.getvalue().strip(), "safe-codex")


if __name__ == "__main__":
    unittest.main()
