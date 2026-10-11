"""O6: helper index in every task prompt."""
from autopilot.orchestrator import Orchestrator
from autopilot.repomap import helper_index
from test_autopilot import FakeBackend, make_project, phases_basic


def fixture(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "util.py").write_text("def slugify(s):\n    return s\n\ndef _private():\n    pass\n\nclass Box:\n    pass\n")
    (root / "pkg" / "app.py").write_text("from pkg.util import slugify\nimport pkg.util\n\ndef run():\n    pass\n")
    (root / "web").mkdir()
    (root / "web" / "api.js").write_text("export function fetchUser() {}\nexport const BASE = 1\nconst hidden = 2\n")
    (root / "web" / "main.js").write_text("import { fetchUser } from './api'\nexport function boot() {}\n")
    (root / "web" / "api.test.js").write_text("export function testOnly() {}\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x():\n    pass\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.js").write_text("export function dep() {}\n")


def test_index_lists_public_names_ranks_by_imports_and_skips_noise(tmp_path):
    fixture(tmp_path)
    lines = helper_index(tmp_path).splitlines()
    assert {l.split(":")[0] for l in lines} == {"pkg/util.py", "pkg/app.py", "web/api.js", "web/main.js"}
    assert lines[0] == "pkg/util.py: slugify, Box"  # imported twice, api.js once
    assert lines[1] == "web/api.js: fetchUser, BASE"
    text = "\n".join(lines)
    assert "_private" not in text and "hidden" not in text and "testOnly" not in text and "dep" not in text


def test_index_respects_the_cap(tmp_path):
    for i in range(50):
        (tmp_path / f"mod{i}.py").write_text(f"def helper_number_{i}():\n    pass\n")
    out = helper_index(tmp_path, cap=300)
    assert 0 < len(out) <= 300


def test_task_prompt_has_index_and_rule(tmp_path):
    root = make_project(tmp_path, phases_basic())
    fixture(root)
    fake = FakeBackend()
    Orchestrator(root, backend=fake, sleep=lambda s: None).run()
    prompt = dict(fake.prompts)["P01-T01"]
    assert "pkg/util.py: slugify, Box" in prompt
    assert "a new helper with the same job as a listed one is a defect" in prompt.lower()
    assert "{{" not in prompt
