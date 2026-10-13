from autopilot.scope_files import HEADING, scoped_files_block


def make(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("class Beta:\n    pass\n", encoding="utf-8")
    return tmp_path


def test_two_scoped_files_in_full_in_list_order(tmp_path):
    out = scoped_files_block(make(tmp_path), ["b.py", "a.py"], 60000)
    assert out.startswith(HEADING)
    assert "class Beta:" in out and "def alpha():" in out
    assert out.index("### b.py") < out.index("### a.py")


def test_large_file_gives_head_and_def_list(tmp_path):
    body = "\n".join(f"x{i} = {i}" for i in range(200)) + "\ndef late_function():\n    pass\n"
    (tmp_path / "big.py").write_text(body, encoding="utf-8")
    out = scoped_files_block(tmp_path, ["big.py"], 1500)
    assert "x0 = 0" in out and "x79 = 79" in out and "x150 = 150" not in out
    assert "201: def late_function():" in out
    assert len(out) <= 1500


def test_glob_not_expanded_and_missing_is_new(tmp_path):
    make(tmp_path)
    out = scoped_files_block(tmp_path, ["*.py", "new.py"], 60000)
    assert "def alpha" not in out
    assert "### new.py\n(new file)" in out


def test_cap_holds_and_skip_docs(tmp_path):
    make(tmp_path)
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    out = scoped_files_block(tmp_path, ["a.py", "b.py", "README.md"], 80, skip=["README.md"])
    assert len(out) <= 80 and "README" not in out
    assert scoped_files_block(tmp_path, ["a.py"], 10) == ""
