import json
import os
import subprocess
import sys
from pathlib import Path

from autopilot import gate

ROOT = Path(__file__).resolve().parent.parent
SEAL = ROOT / "plugin" / "scripts" / "seal.py"
FAIL = 'python -c "raise SystemExit(1)"'


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def repo(tmp_path, test_cmd="python -c pass", tests_text="def test_a():\n    assert 1\n"):
    r = tmp_path / "proj"
    (r / ".agent").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / ".agent" / "project.yaml").write_text(f"commands:\n  test: {test_cmd}\n  lint: echo\nagent:\n  x: 1\n")
    (r / "tests" / "test_a.py").write_text(tests_text)
    sh(r, "git", "init", "-q")
    sh(r, "git", "add", "-A")
    sh(r, "git", "-c", "user.name=example", "-c", "user.email=example@example.com", "commit", "-qm", "x")
    return r


def seal(tmp_path, r, session="s1"):
    env = {**os.environ, "TMP": str(tmp_path), "TEMP": str(tmp_path), "TMPDIR": str(tmp_path)}
    p = subprocess.run([sys.executable, str(SEAL)], input=json.dumps({"session_id": session, "cwd": str(r)}),
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0
    return p.stdout.strip()


def test_failing_test_command_blocks(tmp_path):
    out = json.loads(seal(tmp_path, repo(tmp_path, FAIL)))
    assert out["decision"] == "block" and "python -c" in out["reason"]


def test_clean_repo_prints_nothing(tmp_path):
    assert seal(tmp_path, repo(tmp_path)) == ""


def test_shrunk_test_file_blocks(tmp_path):
    r = repo(tmp_path, tests_text="def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n")
    (r / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n")
    out = json.loads(seal(tmp_path, r))
    assert out["decision"] == "block" and "tests/test_a.py" in out["reason"]


def test_sixth_block_is_silent(tmp_path):
    r = repo(tmp_path, FAIL)
    assert [bool(seal(tmp_path, r)) for _ in range(6)] == [True] * 5 + [False]
    assert seal(tmp_path, r, "other") != ""


def test_no_test_command_is_silent(tmp_path):
    r = tmp_path / "bare"
    r.mkdir()
    assert seal(tmp_path, r) == ""


def test_globs_match_gate():
    sys.path.insert(0, str(SEAL.parent))
    try:
        import seal as s
    finally:
        sys.path.remove(str(SEAL.parent))
    assert s.TEST_GLOBS == gate.TEST_GLOBS


def test_hooks_and_marketplace_parse():
    h = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())
    cmd = h["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/seal.py" in cmd and "python3" in cmd and "python " in cmd
    m = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert m["plugins"][0]["source"] == "./plugin"


def seal_timeout():
    sys.path.insert(0, str(SEAL.parent))
    try:
        import seal as s
    finally:
        sys.path.remove(str(SEAL.parent))
    return s.TIMEOUT


def ref_section(title, nxt):
    text = (ROOT / "REFERENCE.md").read_text(encoding="utf-8")
    return text.split(f"### {title}", 1)[1].split(f"### {nxt}", 1)[0]


def test_reference_stop_hook_matches_hooks_json():
    h = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())
    timeout = h["hooks"]["Stop"][0]["hooks"][0]["timeout"]
    sec = ref_section("Stop hook in the plugin", "Routine")
    assert "plugin/scripts/seal.py" in sec and f"{timeout} s timeout" in sec
    assert f"{seal_timeout()} s" in sec and "autopilot-seal-<session>.count" in sec


def test_reference_routine_links_howto_and_prompt():
    sec = (ROOT / "REFERENCE.md").read_text(encoding="utf-8").split("### Routine", 1)[1].split("## VS Code extension", 1)[0]
    assert "examples/routine/prompt.md" in sec and "HOWTO.md#run-with-the-laptop-off-claude-code-routines" in sec
    assert "max_sessions_per_run: 3" in sec and "not run live yet" in sec
