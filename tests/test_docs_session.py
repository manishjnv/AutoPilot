"""O11: one documentation session per closed phase: RCA entries for retried tasks, a README section per feature,
DEVELOPING.md for a person; a second phase close appends and never duplicates; a code change drops the result."""
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project

PLAN = [
    {"id": "P01", "title": "One", "features": [{"id": "P01-F01", "title": "Check a file", "journey": "run check"},
                                              {"id": "P01-F02", "title": "Scan a tree", "journey": "run scan"}],
     "tasks": [{"id": "P01-T01", "title": "a", "risk": "low"}, {"id": "P01-T02", "title": "b", "risk": "low"}]},
    {"id": "P02", "title": "Two", "features": [{"id": "P02-F01", "title": "Report", "journey": "run report"}],
     "tasks": [{"id": "P02-T01", "title": "c", "risk": "low"}]},
]


def run(tmp_path, fake, extra=None):
    root = make_project(tmp_path, PLAN, {"profile": "lean", "decide": {"enabled": False},
                                         "docs": {"session": True}, **(extra or {})})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    return root, orch


def test_docs_session_writes_rca_readme_and_developing_once_per_phase(tmp_path):
    fake = FakeBackend(behaviours={"P01-T01": ["break", "ok"]})  # one retried task
    root, orch = run(tmp_path, fake)
    assert sum(1 for c in fake.calls if c[0] == "docs") == 2  # one per phase, not per task
    rca = (root / "docs" / "RCA.md").read_text()
    assert rca.count("· P01-T01 ") == 1 and "P01-T02" not in rca and "P02-T01" not in rca
    readme = (root / "README.md").read_text()
    assert [readme.count(f"## {t}\n") for t in ("Check a file", "Scan a tree", "Report")] == [1, 1, 1]
    dev = (root / "docs" / "DEVELOPING.md").read_text()
    assert dev.startswith("# Developing") and len(dev.splitlines()) < 200
    log = orch.git.run("log", "--format=%s", "--name-only")
    assert log.count("[autopilot] docs for phase") == 2 and "docs/DEVELOPING.md" in log and "docs/RCA.md" in log
    assert orch.git.is_clean()


def test_docs_session_that_edits_code_is_dropped(tmp_path):
    fake = FakeBackend()
    fake.docs_touches_code = True
    root, orch = run(tmp_path, fake)
    assert not (root / "src" / "sneaky.py").exists() and not (root / "docs" / "DEVELOPING.md").exists()
    assert any(e["kind"] == "docs" and "dropped" in e["message"] for e in orch.state.events(50))
    assert orch.git.is_clean()


def test_docs_session_secret_looking_prose_is_redacted_not_dropped(tmp_path):
    fake = FakeBackend(behaviours={"P01-T01": ["break", "ok"]})
    fake.docs_secret_line = True
    root, orch = run(tmp_path, fake)
    rca = (root / "docs" / "RCA.md").read_text()
    assert "hunter2" not in rca and "(removed: it looked like a secret)" in rca and "· P01-T01 " in rca
    assert orch.git.is_clean() and not any("dropped" in e["message"] for e in orch.state.events(50) if e["kind"] == "docs")


def test_docs_session_off_by_config(tmp_path):
    fake = FakeBackend()
    run(tmp_path, fake, {"docs": {"session": False}})
    assert not any(c[0] == "docs" for c in fake.calls)
