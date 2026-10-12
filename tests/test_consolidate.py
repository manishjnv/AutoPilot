"""O9: growth numbers at phase close and the [consolidate] task."""
import json

import yaml

from autopilot.growth import consolidate

PLAN = {"goal": "g", "phases": [{"id": f"P0{i}", "title": f"Phase {i}", "tasks": [{"id": f"P0{i}-T01", "title": f"Task {i}"}]}
                                for i in (1, 2, 3)]}
BLOCK = "".join(f"value_{i} = compute_total(items, {i}) + offset_for_region(region_name)\n" for i in range(6))


def repo(tmp_path):
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "plan.yaml").write_text(yaml.safe_dump(PLAN), encoding="utf-8")
    (tmp_path / "one.py").write_text(BLOCK, encoding="utf-8")
    return tmp_path, tmp_path / ".agent" / "plan.yaml"


def tasks(plan):
    return [t for p in yaml.safe_load(plan.read_text(encoding="utf-8"))["phases"] for t in p["tasks"]
            if t["title"].startswith("[consolidate]")]


def test_a_new_duplicate_block_adds_one_task_naming_both_files(tmp_path):
    root, plan = repo(tmp_path)
    assert consolidate(root, plan, "P01") is None  # the first close only records
    (root / "two.py").write_text(BLOCK, encoding="utf-8")
    assert consolidate(root, plan, "P02") == "P03-T00"
    [t] = tasks(plan)
    assert "one.py ~ two.py" in t["description"] and t["risk"] == "medium"
    assert yaml.safe_load(plan.read_text(encoding="utf-8"))["phases"][2]["tasks"][0]["id"] == "P03-T00"
    assert json.loads((root / ".agent" / "quality_baseline.json").read_text())["growth"]["P02"]["dup_blocks"] == 1


def test_flat_numbers_add_no_task(tmp_path):
    root, plan = repo(tmp_path)
    assert consolidate(root, plan, "P01") is None
    assert consolidate(root, plan, "P02") is None
    assert tasks(plan) == []


def test_the_same_list_does_not_add_a_second_task(tmp_path):
    root, plan = repo(tmp_path)
    consolidate(root, plan, "P01")
    (root / "two.py").write_text(BLOCK, encoding="utf-8")
    assert consolidate(root, plan, "P02") == "P03-T00"
    path = root / ".agent" / "quality_baseline.json"
    data = json.loads(path.read_text())
    data["growth"]["P02"]["dup_blocks"] = 0  # the numbers rise again, the list is the same
    path.write_text(json.dumps(data), encoding="utf-8")
    assert consolidate(root, plan, "P02") is None
    assert len(tasks(plan)) == 1
