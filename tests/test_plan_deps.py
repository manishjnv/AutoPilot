from autopilot.plan import Plan, independent_groups


def phase(pid, files, **kw):
    return {"id": pid, "name": pid, "tasks": [{"id": pid + "-T1", "title": "t", "files_in_scope": files,
                                                "acceptance_criteria": ["x"]}], **kw}


def test_three_disjoint_phases_run_side_by_side():
    plan = Plan.from_dict({"phases": [phase(f"P{i}", [f"src/m{i}.py"], depends_on=[]) for i in range(3)]})
    groups, shared = independent_groups(plan)
    assert max(len(g) for g in groups) == 3 and shared == []


def test_shared_file_is_reported():
    plan = Plan.from_dict({"phases": [phase("P1", ["a.py", "shared.py"], depends_on=[]),
                                      phase("P2", ["shared.py"], depends_on=[]),
                                      phase("P3", ["c/*.py"], depends_on=[])]})
    groups, shared = independent_groups(plan)
    assert shared == [("P1", "P2", ["shared.py"])]
    assert max(len(g) for g in groups) == 2


def test_missing_depends_on_keeps_the_chain():
    plan = Plan.from_dict({"phases": [phase("P1", ["a.py"]), phase("P2", ["b.py"]), phase("P3", ["c.py"])]})
    assert [p.depends_on for p in plan.phases] == [[], ["P1"], ["P2"]]
    groups, _ = independent_groups(plan)
    assert max(len(g) for g in groups) == 1
