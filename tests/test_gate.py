import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from autopilot.config import Config, scope_always
from autopilot.config import tests_mode as gate_tests_mode
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


def test_task_gate_fails_a_file_outside_scope_unless_declared(repo):  # O1
    put(repo, "src/other.py", "x = 1\n")
    put(repo, "lib/mine.py", "y = 1\n")
    cfg = Config.load(repo)
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=True, files_in_scope=["lib/**"], verify=[])
    g = task_gate(cfg, Git(repo), task, report={})
    assert not g.ok and any("outside files_in_scope: ['src/other.py']" in m for m in g.problems)
    put(repo, "src/x.py", "z = 1\n")
    adds = {"src/other.py": "shared constant lives here"}
    g = task_gate(cfg, Git(repo), task, report={"scope_additions": adds})  # attempt 1: additions do not count
    assert not g.ok and any("attempt 2" in m for m in g.problems)
    g = task_gate(cfg, Git(repo), task, report={"scope_additions": {**adds, "src/x.py": "also"}}, attempt=2)
    assert g.ok and not any("outside" in m for m in g.problems)
    assert "scope added: src/other.py: shared constant lives here" in g.warnings and len(g.warnings) == 2
    four = {f"src/{i}.py": "why" for i in range(4)}
    g = task_gate(cfg, Git(repo), task, report={"scope_additions": four}, attempt=2)
    assert not g.ok and any("at most 3" in m for m in g.problems)
    g = task_gate(cfg, Git(repo), task, report={"scope_additions": {"*": "everything"}}, attempt=2)  # no pattern
    assert not g.ok and any("exactly" in m for m in g.problems)
    task.files_in_scope = ["lib/**", "src/**"]
    assert task_gate(cfg, Git(repo), task, report={}).ok
    cfg.data["gate"] = {"scope_fail": False}
    task.files_in_scope = ["lib/**"]
    g = task_gate(cfg, Git(repo), task, report={})
    assert g.ok and any("outside files_in_scope: src/other.py" in w for w in g.warnings)


def test_file_growth_budget_with_a_baseline(repo):  # O2
    import json

    from autopilot.gate import file_growth, write_baseline
    put(repo, "src/big.py", "x = 1\n" * 390)
    put(repo, "src/old.py", "y = 1\n" * 500)
    sh(repo, "add", "-A"), sh(repo, "commit", "-qm", "base")
    assert write_baseline(repo) >= 2
    base = json.loads((repo / ".agent" / "quality_baseline.json").read_text())
    assert base["src/big.py"] == 390 and base["src/old.py"] == 500 and "tests/test_x.py" not in base
    cfg = Config.load(repo)
    put(repo, "src/big.py", "x = 1\n" * 420)  # 390 -> 420: past 400 and the file was under the budget before
    sh(repo, "add", "-A")
    grew = file_growth(cfg, Git(repo))
    assert len(grew) == 1 and grew[0].startswith("file grew past the budget: src/big.py 390 -> 420 lines (limit 400)")
    put(repo, "src/big.py", "x = 1\n" * 390)
    put(repo, "src/old.py", "y = 1\n" * 500 + "z = 2\n")  # 500 -> 501: within 25 percent of its baseline
    sh(repo, "add", "-A")
    assert file_growth(cfg, Git(repo)) == []
    put(repo, "src/old.py", "y = 1\n" * 700)  # 500 -> 700: past 25 percent in one task
    sh(repo, "add", "-A")
    assert len(file_growth(cfg, Git(repo))) == 1
    cfg.data["gate"]["file_growth"] = True
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=False, files_in_scope=[], verify=[])
    assert not task_gate(cfg, Git(repo), task).ok


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
    _fake("c", "f_", "m" * 24),
    _fake("r", "e_", "n" * 24),
    _fake("pmark", "_live_", "p" * 24),
    _fake("-----BEGIN ", "RSA PRIVATE", " KEY-----"),
    _fake("-----BEGIN ", "EC PRIVATE", " KEY-----"),
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
    # session 27: test data with the placeholder word inside the value itself passes (the hint promises this)
    'AWS = "AKIAIOSFODNN7EXAMPLE"',
    'GITHUB = "ghp_fakefakefakefakefakefake1234"',
    'HEADER = "-----BEGIN RSA PRIVATE KEY-----"  # fake fixture header',
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
    assert run_commands([cmd], tmp_path, 20)[0].output == ""  # X6: the default env is minimal too
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


def test_platform_skipif_still_fails_and_the_hint_says_so(repo):
    # envguard run 2026-10-03: the old hint said "guard it on a real platform condition"; the agent wrote a
    # platform skipif twice and failed twice. A text match cannot tell a real guard from os.name == os.name.
    put(repo, "tests/test_n.py", "import shutil\nimport pytest\n\n\n"
        '@pytest.mark.skipif(shutil.which("git") is None, reason="no git")\ndef test_a():\n    assert 1\n')
    found = [f for f in tamper(repo) if "skip/focus" in f]
    assert len(found) == 1 and "`skipif` on a platform condition too" in found[0]


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


def test_task_report_schema_names_every_field_the_gate_reads():
    """Session 27: the structured report follows the schema; a field the schema omits never arrives (O1 hatch, O3 deps)."""
    from autopilot.schemas import REPORTS  # noqa: PLC0415
    props = REPORTS["task"]["properties"]
    assert props["scope_additions"]["type"] == "object" and props["new_deps"]["type"] == "array"
    assert {"name", "reason"} <= set(props["new_deps"]["items"]["properties"])


class Fake:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, key, default=None):
        return self.kv.get(key, default)


def test_scope_always_and_tests_mode_defaults():  # P02-T00 contract
    assert scope_always(Fake()) == ["REFERENCE.md", "CHANGELOG.md", "HOWTO.md", "README.md"]
    assert gate_tests_mode(Fake()) == "changed"
    assert scope_always(Fake(**{"gate.scope_always": ["NOTES.md"]})) == ["NOTES.md"]
    assert gate_tests_mode(Fake(**{"gate.tests": "full"})) == "full"


def test_old_project_yaml_without_the_keys(tmp_path):  # a project.yaml from before W19/W22
    cfg = Config.load(tmp_path)
    cfg.data.get("gate", {}).pop("scope_always", None)
    cfg.data.get("gate", {}).pop("tests", None)
    assert scope_always(cfg) == ["REFERENCE.md", "CHANGELOG.md", "HOWTO.md", "README.md"]
    assert gate_tests_mode(cfg) == "changed"
    assert not [e for e in cfg.validate() if "gate." in e]


def _pytest_project(tmp_path, tests="changed"):  # W22
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("def test_a():\n    pass\n")
    cfg = Config.load(tmp_path)
    cfg.data["profile"] = "full"
    cfg.data["commands"] = {"test": ["python -m pytest -q"], "phase_verify": ["echo phase"]}
    cfg.data.setdefault("gate", {})["tests"] = tests
    return cfg


def test_full_profile_task_gate_narrows_tests(tmp_path):
    from autopilot.gate import verify_commands
    cfg = _pytest_project(tmp_path)
    cmds = verify_commands(cfg, files=["autopilot/foo.py"])
    assert cmds == ["python -m pytest -q tests/test_foo.py"]


def test_phase_close_runs_the_full_command(tmp_path):
    from autopilot.gate import verify_commands
    cfg = _pytest_project(tmp_path)
    cmds = verify_commands(cfg, phase=True, files=["autopilot/foo.py"])
    assert cmds == ["python -m pytest -q", "echo phase"]


def test_gate_tests_full_runs_the_full_command_per_task(tmp_path):
    from autopilot.gate import verify_commands
    cfg = _pytest_project(tmp_path, tests="full")
    assert verify_commands(cfg, files=["autopilot/foo.py"]) == ["python -m pytest -q"]


def test_task_prompt_says_not_to_run_the_full_suite():
    text = (Path(__file__).parent.parent / "autopilot" / "prompts" / "task.md").read_text(encoding="utf-8")
    assert "Run the tests of the files you changed. The gate runs the full suite at the phase close." in text


def test_gate_keys_validation(tmp_path):
    cfg = Config.load(tmp_path)
    cfg.data.setdefault("gate", {})["scope_always"] = "REFERENCE.md"
    assert any("gate.scope_always must be a list" in e for e in cfg.validate())
    cfg.data["gate"]["scope_always"] = ["REFERENCE.md", 3]
    assert any("gate.scope_always must be a list" in e for e in cfg.validate())
    cfg.data["gate"]["scope_always"] = ["NOTES.md"]
    assert not [e for e in cfg.validate() if "gate." in e]
    cfg.data["gate"]["tests"] = "some"
    assert any("gate.tests must be changed or full, got 'some'" in e for e in cfg.validate())
    cfg.data["gate"]["tests"] = "full"
    assert not [e for e in cfg.validate() if "gate." in e]


def test_template_gate_block_has_both_keys_with_comments():
    root = Path(__file__).resolve().parents[1]
    text = (root / "autopilot" / "templates" / "agent" / "project.yaml").read_text(encoding="utf-8")
    block = text[text.index("\ngate:\n") + 1:].splitlines()[1:]
    scope = next(line for line in block if line.startswith("  scope_always:"))
    tests = next(line for line in block if line.startswith("  tests:"))
    assert "# " in scope and "# " in tests
    assert yaml.safe_load(scope.strip())["scope_always"] == ["REFERENCE.md", "CHANGELOG.md", "HOWTO.md", "README.md"]
    assert yaml.safe_load(tests.strip())["tests"] == "changed"


def scope_task():
    return SimpleNamespace(allow_no_changes=False, allow_test_changes=True, files_in_scope=["lib/**"], verify=[])


def scope_cfg(repo):
    cfg = Config.load(repo)
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    return cfg


def test_docs_files_are_always_in_scope(repo):  # W19
    put(repo, "lib/mine.py", "y = 1\n")
    put(repo, "REFERENCE.md", "ref\n")
    put(repo, "HOWTO.md", "how\n")
    g = task_gate(scope_scfg := scope_cfg(repo), Git(repo), scope_task(), report={})
    assert g.ok and not g.warnings and not any("outside" in m for m in g.problems)
    put(repo, "src/other.py", "x = 1\n")
    g = task_gate(scope_scfg, Git(repo), scope_task(), report={})
    assert not g.ok and any("outside files_in_scope: ['src/other.py']" in m for m in g.problems)


def test_entry_added_to_scope_always_passes(repo):  # W19
    put(repo, "lib/mine.py", "y = 1\n")
    put(repo, "NOTES.md", "n\n")
    cfg = scope_cfg(repo)
    assert not task_gate(cfg, Git(repo), scope_task(), report={}).ok
    cfg.data.setdefault("gate", {})["scope_always"] = ["NOTES.md"]
    g = task_gate(cfg, Git(repo), scope_task(), report={})
    assert g.ok and not g.warnings


def test_howto_has_the_work_branch_recipe():  # W19
    text = (Path(__file__).resolve().parent.parent / "HOWTO.md").read_text(encoding="utf-8")
    assert "main_branch: autopilot/work" in text and "git.mode: direct" in text and "git.mode: pr" in text
