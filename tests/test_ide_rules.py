"""N6: Autopilot block in IDE rule files and CLAUDE.md."""
import argparse

from autopilot.cli import cmd_init


def init(root):
    cmd_init(argparse.Namespace(path=str(root), stack="generic", name=None, force=False, quiet=True))


def test_cursor_rule_written_once(tmp_path):
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    init(tmp_path)
    f = tmp_path / ".cursor" / "rules" / "autopilot.mdc"
    t = f.read_text(encoding="utf-8")
    assert t.startswith("---\n") and "alwaysApply: true" in t and "ap status" in t
    init(tmp_path)
    assert f.read_text(encoding="utf-8") == t and t.count("autopilot:begin") == 1


def test_agents_md_user_text_unchanged(tmp_path):
    user = b"# My rules\r\nbe nice"
    (tmp_path / "AGENTS.md").write_bytes(user)
    init(tmp_path)
    got = (tmp_path / "AGENTS.md").read_bytes()
    assert got.startswith(user) and got.count(b"autopilot:begin") == 1
    init(tmp_path)
    assert (tmp_path / "AGENTS.md").read_bytes() == got


def test_kiro_vscode_gemini(tmp_path):
    (tmp_path / ".kiro").mkdir()
    (tmp_path / ".vscode").mkdir()
    (tmp_path / "GEMINI.md").write_text("mine\n", encoding="utf-8")
    init(tmp_path)
    k = (tmp_path / ".kiro" / "steering" / "autopilot.md").read_text(encoding="utf-8")
    assert k.startswith("---\ninclusion: always\n---\n") and "ap next" in k
    assert "ap start" in (tmp_path / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    g = (tmp_path / "GEMINI.md").read_text(encoding="utf-8")
    assert g.startswith("mine\n") and g.count("autopilot:begin") == 1


def test_no_marker_only_claude_md(tmp_path):
    init(tmp_path)
    assert not (tmp_path / ".cursor").exists() and not (tmp_path / ".kiro").exists()
    assert not (tmp_path / ".github").exists() and not (tmp_path / "AGENTS.md").exists()
    init(tmp_path)
    t = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    for c in ("ap status", "ap next", "ap start"):
        assert t.count(c) == 1


def test_old_claude_md_section_gets_ap_lines_once(tmp_path):
    # P08-T02: a CLAUDE.md written by an older Autopilot (no `ap status`) gets the two command lines, once
    old = "# Project\n\nUser text.\n\n## Autopilot (autonomous sessions)\nOld section line.\nDo not edit plan.yaml.\n"
    (tmp_path / "CLAUDE.md").write_text(old, encoding="utf-8")
    init(tmp_path)
    t = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert t.startswith(old)
    for c in ("ap status", "ap next", "ap start"):
        assert t.count(c) == 1
    assert t[len(old):].startswith("Commands: `ap status`")
    init(tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == t


def test_claude_md_with_ap_status_untouched(tmp_path):
    cur = "# Project\n\n## Autopilot (autonomous sessions)\nUse ap status first.\n"
    (tmp_path / "CLAUDE.md").write_text(cur, encoding="utf-8")
    init(tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == cur
