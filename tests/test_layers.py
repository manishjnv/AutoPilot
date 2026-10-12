"""O4: the import-boundary check with a baseline."""
import json

from autopilot.layers import check_imports, read_layers

BRAIN = "# Brain\n\n```layers\na: a/**\nb: b/**\n```\n"


def repo(tmp_path, brain=BRAIN, b_code="import a.y\n", a_code="X = 1\n"):
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "BRAIN.md").write_text(brain, encoding="utf-8")
    for d, code in (("a", a_code), ("b", b_code)):
        (tmp_path / d).mkdir()
        (tmp_path / d / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "a" / "y.py").write_text(a_code, encoding="utf-8")
    (tmp_path / "b" / "x.py").write_text(b_code, encoding="utf-8")
    return tmp_path


def test_lower_layer_importing_a_higher_one_is_a_problem(tmp_path):
    root = repo(tmp_path)
    layers = read_layers(root)
    assert layers == [("a", "a/**"), ("b", "b/**")]
    out = check_imports(root, ["b/x.py"], layers, root / ".agent" / "layers_baseline.json")
    assert len(out) == 1 and "b/x.py -> a.y (layer b imports layer a)" in out[0]
    assert (root / ".agent" / "layers_baseline.json").exists()  # day one is written when missing


def test_higher_layer_importing_a_lower_one_is_fine(tmp_path):
    root = repo(tmp_path, b_code="X = 1\n", a_code="from b import x\n")
    assert check_imports(root, ["a/y.py"], read_layers(root), root / ".agent" / "layers_baseline.json") == []


def test_a_violation_in_the_baseline_is_not_new(tmp_path):
    root = repo(tmp_path)
    base = root / ".agent" / "layers_baseline.json"
    base.write_text(json.dumps(["b/x.py -> a.y (layer b imports layer a)"]), encoding="utf-8")
    assert check_imports(root, ["b/x.py"], read_layers(root), base) == []


def test_no_layers_block_means_no_check(tmp_path):
    root = repo(tmp_path, brain="# Brain\n")
    assert read_layers(root) is None
    assert check_imports(root, ["b/x.py"], None, root / ".agent" / "layers_baseline.json") == []
