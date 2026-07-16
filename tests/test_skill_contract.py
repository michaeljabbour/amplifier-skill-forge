from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def frontmatter_and_body():
    content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) != 3:
        raise AssertionError("SKILL.md must contain one YAML frontmatter block")
    return parts[1].strip().splitlines(), parts[2].lstrip()


def folded_field(lines, key):
    prefix = f"{key}:"
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        inline = line[len(prefix):].strip()
        if inline not in (">", ">-", "|", "|-"):
            return inline.strip('"\'')
        values = []
        for following in lines[index + 1:]:
            if following and not following[0].isspace():
                break
            values.append(following.strip())
        return " ".join(value for value in values if value)
    raise AssertionError(f"missing frontmatter field: {key}")


class SkillContractTests(unittest.TestCase):
    def test_name_matches_repository_directory(self):
        lines, _ = frontmatter_and_body()
        self.assertEqual(folded_field(lines, "name"), ROOT.name)
        self.assertRegex(ROOT.name, r"^[a-z0-9-]+$")

    def test_description_is_trigger_rich_and_within_limit(self):
        lines, _ = frontmatter_and_body()
        description = folded_field(lines, "description")
        self.assertLessEqual(len(description), 1024)
        for trigger in ("terminal", "Claude Code", "Codex", "Amplifier", "coordinate"):
            self.assertIn(trigger, description)

    def test_version_is_nested_for_cross_harness_compatibility(self):
        lines, _ = frontmatter_and_body()
        top_level_fields = {
            line.split(":", 1)[0]
            for line in lines
            if line and not line[0].isspace() and ":" in line
        }
        self.assertNotIn("version", top_level_fields)
        self.assertTrue(any(line.startswith("  version:") for line in lines))

    def test_skill_body_is_portable_and_under_500_lines(self):
        _, body = frontmatter_and_body()
        self.assertLess(len(body.splitlines()), 500)
        for forbidden in ("$ARGUMENTS", "${CLAUDE_SKILL_DIR}"):
            self.assertNotIn(forbidden, body)
        self.assertIsNone(re.search(r"!`[^`]+`", body))

    def test_relay_reference_is_directly_routed_from_skill(self):
        _, body = frontmatter_and_body()
        self.assertIn("references/multi-agent-relay.md", body)
        self.assertIn("tools/relay.py", body)

    def test_openai_metadata_mentions_the_skill(self):
        content = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('default_prompt: "Use $amplifier-skill-forge', content)
        self.assertIn('display_name: "', content)
        self.assertIn('short_description: "', content)

    def test_installer_remains_idempotent(self):
        content = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("ln -sfn", content)
        self.assertIn("--check", content)

    def test_python_tools_remain_stdlib_only(self):
        allowed = {
            "argparse", "datetime", "glob", "hashlib", "json", "os", "pathlib", "re",
            "shutil", "subprocess", "sys", "tempfile", "time", "typing", "urllib", "uuid",
        }
        for relative in ("tools/forge.py", "tools/relay.py"):
            imports = set()
            for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
                match = re.match(r"(?:from|import)\s+([A-Za-z0-9_]+)", line)
                if match:
                    imports.add(match.group(1))
            self.assertFalse(imports - allowed, f"third-party import in {relative}: {imports - allowed}")


if __name__ == "__main__":
    unittest.main()
