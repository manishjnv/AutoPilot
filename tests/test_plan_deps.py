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


def test_bad_ids_rejected_and_good_pass():
    import pytest
    from autopilot.plan import PlanError
    for bad in ("../x", "a b", "..\\..\\x", "x" * 41):
        with pytest.raises(PlanError, match="bad task id"):
            Plan.from_dict({"phases": [{"id": "P1", "tasks": [{"id": bad, "title": "t"}]}]})
        with pytest.raises(PlanError, match="bad phase id"):
            Plan.from_dict({"phases": [{"id": bad, "tasks": [{"id": "T1", "title": "t"}]}]})
    Plan.from_dict({"phases": [{"id": "P-1_a", "tasks": [{"id": "P1-T1", "title": "t"}]}]})


def test_drop_worktree_refuses_outside_path(tmp_path):
    from autopilot.gitops import Git
    repo = tmp_path / "repo"
    repo.mkdir()
    victim = tmp_path / "keep"
    victim.mkdir()
    root = tmp_path / "wt"
    root.mkdir()
    g = Git(repo)
    g.drop_worktree(root / ".." / "keep", "b")
    g.drop_worktree(repo, "b")
    g.drop_worktree(victim, "b", inside=root)  # X2: a clean path outside the worktree folder is refused too
    assert victim.is_dir() and repo.is_dir()


def test_approve_bad_id_exits_2(tmp_path):
    from autopilot.cli import main
    assert main(["approve", "../x", "-C", str(tmp_path)]) == 2
