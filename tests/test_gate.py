import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from autopilot.config import Config
from autopilot.gate import run_commands, scan_secrets, task_gate, test_tamper
from autopilot.gitops import Git
from autopilot.proc import agent_env

TESTS2 = "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"
PYPROJECT = '[tool.pytest.ini_options]\naddopts = "-q"\n'
PKG = '{\n  "scripts": {\n    "test": "jest"\n  }\n}\n'
CI = "name: ci\non: push\n"


def sh(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def put(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path):
    sh(tmp_path, "init", "-q")
    sh(tmp_path, "config", "user.name", "t")
    sh(tmp_path, "config", "user.email", "t@example.com")
    sh(tmp_path, "config", "core.autocrlf", "false")
    put(tmp_path, "tests/test_x.py", TESTS2)
    put(tmp_path, "pyproject.toml", PYPROJECT)
    put(tmp_path, "package.json", PKG)
    put(tmp_path, ".github/workflows/ci.yml", CI)
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-qm", "init")
    return tmp_path


def tamper(root, allow=False):
    sh(root, "add", "-A")
    return test_tamper(Config.load(root), Git(root), allow)


def test_clean_and_additions_not_flagged(repo):
    put(repo, "tests/test_y.py", "def test_new():\n    pass\n")
    put(repo, "tests/test_x.py", TESTS2 + "\n\ndef test_c():\n    pass\n")
    put(repo, "src/app.py", "x = 1\n")
    assert tamper(repo) == []


def test_new_ci_workflow_flagged(repo):
    put(repo, ".github/workflows/new.yml", CI)
    assert any("CI pipeline file added" in f for f in tamper(repo))


def test_secret_scan_ignores_kebab_identifiers():
    assert scan_secrets(['cls = "task-list-item-container-wide"', 'url = "/ask-question-and-answer-now"']) == []


def test_deleted_test_file(repo):
    (repo / "tests/test_x.py").unlink()
    assert any("deleted" in f and "tests/test_x.py" in f for f in tamper(repo))


def test_renamed_to_non_test(repo):
    sh(repo, "mv", "tests/test_x.py", "keep.txt")
    assert any("renamed" in f and "keep.txt" in f for f in tamper(repo))


def test_count_drop(repo):
    put(repo, "tests/test_x.py", "def test_a():\n    pass\n")
    f = tamper(repo)
    assert any("count dropped" in m and "2 -> 1" in m for m in f)


def test_skip_marker(repo):
    put(repo, "tests/test_x.py", "import pytest\n\n@pytest.mark.skip\n" + TESTS2)
    assert any("skip/focus" in f and "tests/test_x.py" in f for f in tamper(repo))


def test_skip_marker_in_new_test_file(repo):
    put(repo, "tests/test_n.py", "import pytest\n\n\ndef test_n():\n    pytest.skip('x')\n")
    assert any("skip/focus" in f and "test_n.py" in f for f in tamper(repo))


def test_workflow_edit_flagged(repo):
    put(repo, ".github/workflows/ci.yml", CI + "# changed\n")
    assert any("CI pipeline file changed" in f and "ci.yml" in f for f in tamper(repo))


def test_workflow_delete_flagged(repo):
    (repo / ".github/workflows/ci.yml").unlink()
    assert any("CI pipeline file deleted" in f for f in tamper(repo))


def test_package_json_test_script_changed(repo):
    put(repo, "package.json", PKG.replace("jest", "echo ok"))
    assert any("package.json" in f and "removed" in f for f in tamper(repo))


def test_addopts_k_added(repo):
    put(repo, "pyproject.toml", PYPROJECT.replace('"-q"', '"-q -k smoke"'))
    f = tamper(repo)
    assert any("pyproject.toml" in m and "weakened" in m for m in f)


def test_allow_labels_findings(repo):
    (repo / "tests/test_x.py").unlink()
    assert tamper(repo, allow=True)[0].startswith("(allowed)")


@pytest.mark.parametrize("allow", [False, True])
def test_task_gate_routes_findings(repo, allow):
    (repo / "tests/test_x.py").unlink()
    cfg = Config.load(repo)
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=allow, files_in_scope=[], verify=[])
    g = task_gate(cfg, Git(repo), task)
    bucket, other = (g.warnings, g.problems) if allow else (g.problems, g.warnings)
    assert any("test file deleted" in m for m in bucket)
    assert not any("test file deleted" in m for m in other)
    assert g.ok is allow


def _fake(*parts):
    return "".join(parts)


POSITIVE = [
    _fake("AK", "IA", "ABCDEFGHIJKLMNOP"),
    _fake("AS", "IA", "ABCDEFGHIJKLMNOP"),
    _fake("sk", "-", "a" * 24),
    _fake("sk", "-proj-", "b1_" * 8),
    _fake("sk", "-ant-", "c" * 24),
    _fake("xa", "i-", "d" * 24),
    _fake("h", "f_", "e" * 34),
    _fake("github", "_pat_", "f" * 24),
    _fake("gh", "p_", "g" * 24),
    _fake("gh", "s_", "g" * 24),
    _fake("gl", "pat-", "h" * 24),
    _fake("AI", "za", "i" * 35),
    _fake("GOC", "SPX-", "j" * 24),
    _fake("s", "k_live_", "k" * 24),
    _fake("r", "k_live_", "k" * 24),
    _fake("xo", "xb-", "1234567890ab"),
    _fake("https://hooks.", "slack.com/services/", "T0ABC123/", "B0DEF456/", "abcDEF123"),
    _fake("12345678", "9:", "AA", "l" * 33),
    _fake("-----BEGIN ", "OPENSSH PRIVATE", " KEY-----"),
    _fake("-----BEGIN PRIVATE", " KEY-----"),
    'password = "hunter2hunter2hunter2"',
]
NEGATIVE = [
    "x = os.environ['API_KEY']",
    "key = os.getenv('OPENAI_API_KEY')",
    "use sk-xxx as the key",
    "token = get_token()",
    "ghp_short",
    "hf_short",
    "AKIAshort",
]


@pytest.mark.parametrize("line", POSITIVE)
def test_secret_positive(line):
    assert scan_secrets([line]), line


@pytest.mark.parametrize("line", NEGATIVE)
def test_secret_negative(line):
    assert scan_secrets([line]) == []


def test_blocking_errors(tmp_path):
    cfg = Config.load(tmp_path)
    assert any("no verify commands" in e for e in cfg.blocking_errors())
    cfg.data["gate"]["allow_no_checks"] = True
    assert cfg.blocking_errors() == []
    cfg.data["deploy"]["staging"] = {"enabled": True, "cmd": ""}
    assert any("deploy.staging" in e for e in cfg.blocking_errors())
    assert any("no verify commands" in e for e in cfg.validate())
    cfg.data["commands"]["test"] = ["x"]
    cfg.data["deploy"]["staging"]["cmd"] = "deploy"
    assert cfg.blocking_errors() == []


def test_run_commands_timeout(tmp_path):
    t0 = time.time()
    r = run_commands([f'"{sys.executable}" -c "import time; time.sleep(30)"'], tmp_path, 2)[0]
    assert r.rc == 124 and r.output.startswith("TIMEOUT after 2s")
    assert time.time() - t0 < 15


def test_run_commands_missing_cwd(tmp_path):
    r = run_commands(["echo hi"], tmp_path / "nope", 5)[0]
    assert r.rc == 127


def test_base_env_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TG_TOKEN", "sekret")
    cmd = f'"{sys.executable}" -c "import os; print(os.environ.get(\'AUTOPILOT_TG_TOKEN\', \'\'))"'
    cfg = Config.load(tmp_path)
    assert run_commands([cmd], tmp_path, 20)[0].output == "sekret"
    assert run_commands([cmd], tmp_path, 20, base_env=agent_env(cfg))[0].output == ""
    assert run_commands([cmd], tmp_path, 20, env={"AUTOPILOT_TG_TOKEN": "x"}, base_env=agent_env(cfg))[0].output == "x"


def test_emptied_test_body_flagged(repo):
    put(repo, "tests/test_y.py", "def test_real():\n    assert 1 + 1 == 2\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", "real test")
    put(repo, "tests/test_y.py", "def test_real():\n    pass\n")
    assert any("assertion count dropped" in f for f in tamper(repo))


def test_conftest_collection_hook_flagged(repo):
    put(repo, "tests/conftest.py", "def pytest_collection_modifyitems(items):\n    items.clear()\n")
    assert any("test collection hook" in f for f in tamper(repo))


def test_secret_messages_redacted_and_placeholders_skipped():
    key = "sk-ant-" + "api03-" + "Q" * 30
    msgs = scan_secrets([f'KEY = "{key}"'])
    assert msgs and key not in msgs[0]
    assert scan_secrets(['password = "changeme-please-123"', 'token = "${API_TOKEN_FROM_ENV}"']) == []
    assert scan_secrets(['password = "hunter2hunter2hunter2"'])


# ---- G2: the agent is told the gate's rules, and each finding says how to fix it (no rule is weakened) ----

def test_skip_finding_says_what_to_do_instead(repo):
    put(repo, "tests/test_n.py", "import pytest\n\n\ndef test_n():\n    pytest.skip('x')\n")
    assert any("skip/focus" in f and "not allowed" in f and "condition" in f for f in tamper(repo))
    assert not any("not allowed" in f for f in tamper(repo, allow=True))  # a task that may change tests: no such hint


def test_each_hint_appears_once_however_many_findings(repo):
    put(repo, "tests/test_n.py", "import pytest\n\n\ndef test_n():\n    pytest.skip('x')\n\n\n"
                                 "def test_m():\n    pytest.skip('y')\n\n\ndef test_o():\n    pytest.skip('z')\n")
    found = tamper(repo)  # the retry prompt keeps only the tail of the report: hints must not crowd findings out
    assert sum("skip/focus" in f for f in found) == 3 and sum("not allowed" in f for f in found) == 1
    creds = scan_secrets(['password = "hunter2hunter2hunter2"', 'token = "abcdefabcdefabcdef12"', 'secret = "qwertyqwertyqwerty"'])
    assert len(creds) == 3 and sum("example, dummy or fake" in c for c in creds) == 1


def test_credential_finding_says_how_to_write_test_data():
    assert "example, dummy or fake" in scan_secrets(['password = "hunter2hunter2hunter2"'])[0]
    key = "sk-ant-" + "api03-" + "Q" * 30
    assert "dummy" not in scan_secrets([f'KEY = "{key}"'])[0]  # a real-looking key gets no "just rename it" hint


def test_the_agent_is_told_the_gate_rules_and_the_advice_passes_the_gate():
    from autopilot.context import PROMPTS
    system = (PROMPTS / "system.md").read_text(encoding="utf-8")
    assert "skip" in system and all(w in system for w in ("example", "dummy", "fake"))
    for word in ("example", "dummy", "fake"):  # the advice must be true: such values pass the secret scan
        assert scan_secrets([f'token = "{word}-token-for-tests-123"']) == []


def test_needs_you_file_is_protected(tmp_path):
    from autopilot.gate import protected_files
    assert "docs/NEEDS-YOU.md" in protected_files(Config.load(tmp_path))   # an agent must not answer its own decision
