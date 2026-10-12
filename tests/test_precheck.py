"""Q6: one fixture per environment pre-check line; each line has a sentence in the Q4 catalogue."""
import re
from datetime import date, timedelta

from autopilot.commands import precheck as pc
from autopilot.install_errors import PRECHECK


def snap(**kw):
    base = dict(platform="linux", home="/home/u", cwd="/home/u/p", path=["/usr/bin", "/home/u/.local/bin"],
                git_user=("U", "u@example.com"))
    base.update(kw)
    return pc.Snapshot(**base)


def ids(s):
    return [i for i, _, _ in pc.check(s)]


def test_a_clean_machine_prints_no_line():
    assert pc.check(snap()) == []


def test_every_line_has_a_catalogue_sentence_and_a_fixture_here():
    """Each PRECHECK id appears in at least one fixture below; the sentences are one sentence each."""
    import inspect
    src = inspect.getsource(__import__(__name__))
    for key, (sentence, _) in PRECHECK.items():
        assert f'"{key}"' in src, key
        assert sentence.endswith(".") and len(sentence) < 170, key


def test_local_bin_missing_from_path_is_fixed_in_the_profile(tmp_path):
    s = snap(home=str(tmp_path), path=["/usr/bin"])
    lines = pc.check(s)
    assert [i for i, _, _ in lines] == ["local-bin"] and lines[0][1] == "skipped" and str(tmp_path / ".local" / "bin") in lines[0][2]
    fixed = pc.apply(lines, s)
    assert fixed[0][1] == "fixed" and 'export PATH="$PATH:' in (tmp_path / ".profile").read_text(encoding="utf-8")
    assert pc.apply(lines, s, dry_run=True)[0][1] == "skipped"  # a dry run fixes nothing
    assert "Command:" in pc.check(snap(home=r"C:\Users\u", platform="win32", path=[r"C:\W"]))[0][2]


def test_proxy_and_corporate_ca_and_offline():
    assert ids(snap(env={"HTTPS_PROXY": "http://p:1"})) == ["proxy"]
    line = pc.check(snap(env={"HTTPS_PROXY": "http://user:secret@p:1"}))[0][2]
    assert "HTTPS_PROXY" in line and "secret" not in line  # the name, never the value
    assert ids(snap(tls_failed=True)) == ["corporate-ca"] and "SSL_CERT_FILE" in pc.check(snap(tls_failed=True))[0][2]
    assert ids(snap(tls_failed=True, env={"SSL_CERT_FILE": "/ca.pem"})) == []
    assert ids(snap(net_ok=False)) == ["offline"] and ids(snap(net_ok=True)) == []


def test_arm_and_32_bit_windows():
    assert ids(snap(machine="arm64")) == ["arm"] and ids(snap(machine="aarch64")) == ["arm"]
    assert ids(snap(platform="win32", win_32bit=True, machine="x86")) == ["win32-bit"]


def test_home_path_space_non_ascii_cloud_and_readonly():
    assert ids(snap(home="/home/Jane Doe", path=["/home/Jane Doe/.local/bin"])) == ["home-path"]
    assert ids(snap(home="/home/jürgen", path=["/home/jürgen/.local/bin"])) == ["home-path"]
    assert ids(snap(platform="win32", home=r"C:\Users\u\OneDrive", path=[r"c:\users\u\onedrive\.local\bin"])) == ["home-cloud"]
    assert ids(snap(platform="win32", home=r"\\server\u", path=[r"\\server\u\.local\bin"])) == ["home-cloud"]
    assert ids(snap(home_writable=False)) == ["home-readonly"]


def test_root_and_sudo_are_a_warning():
    assert ids(snap(uid=0)) == ["root"] and ids(snap(sudo_user="jane")) == ["root"]
    assert "jane through sudo" in pc.check(snap(sudo_user="jane"))[0][2]


def test_python_shim_uv_age_and_two_autopilots():
    assert ids(snap(python_exe="/home/u/miniconda3/bin/python")) == ["python-shim"]
    assert ids(snap(python_exe="/home/u/.pyenv/shims/python")) == ["python-shim"]
    old = (date.today() - timedelta(days=400)).isoformat()
    assert ids(snap(uv_version=f"uv 0.4.0 (abc {old})")) == ["uv-old"]
    assert ids(snap(uv_version=f"uv 0.9.0 (abc {date.today().isoformat()})")) == []
    assert ids(snap(pip_autopilot=True, uv_autopilot=True)) == ["two-autopilots"]
    assert ids(snap(pip_autopilot=True)) == []


def test_wsl_lines_and_a_windows_binary_seen_from_wsl():
    assert ids(snap(wsl=1)) == ["wsl1"]
    assert ids(snap(wsl=2, cwd="/mnt/c/code/app")) == ["wsl-mnt"]
    s = snap(wsl=2, runner_paths={"claude": ["/mnt/c/Users/u/AppData/Roaming/npm/claude"]})
    assert ids(s) == ["windows-binary-in-wsl"] and "skipped" in [st for _, st, _ in pc.check(s)]
    assert ids(snap(wsl=0, runner_paths={"claude": ["/mnt/c/x/claude"]})) == []


def test_two_copies_and_a_token_over_a_stored_login():
    s = snap(runner_paths={"codex": ["/usr/local/bin/codex", "/home/u/.npm-global/bin/codex"]})
    assert ids(s) == ["two-copies"] and "/usr/local/bin/codex and /home/u/.npm-global/bin/codex" in pc.check(s)[0][2]
    assert ids(snap(runner_paths={"codex": ["/usr/local/bin/codex", "/usr/local/bin/codex"]})) == []
    s = snap(tokens=["GH_TOKEN"], logged_in=["copilot"])
    assert ids(s) == ["token-overrides-login"] and "GH_TOKEN is set; copilot also has a stored login" in pc.check(s)[0][2]
    assert ids(snap(tokens=["GH_TOKEN"], logged_in=["codex"])) == []


def test_git_identity_from_gh_or_the_two_commands():
    s = snap(git_user=("", ""), gh_user=("Jane", "1+jane@users.noreply.github.com"))
    lines = pc.check(s)
    assert [(i, st) for i, st, _ in lines] == [("git-identity", "fixed")]
    ran = []
    pc.apply(lines, s, run=lambda cmd, **kw: ran.append(cmd) or type("P", (), {"rc": 0, "stdout": "", "stderr": ""})())
    assert ran == [["git", "config", "--global", "user.name", "Jane"],
                   ["git", "config", "--global", "user.email", "1+jane@users.noreply.github.com"]]
    lines = pc.check(snap(git_user=("U", "")))
    assert lines[0][1] == "skipped" and "git config --global user.name" in lines[0][2] and "user.email" in lines[0][2]


def test_windows_long_paths_and_leftovers():
    assert ids(snap(platform="win32", home=r"C:\Users\u", path=[r"C:\Users\u\.local\bin"], long_paths=False)) == ["long-paths"]
    assert ids(snap(platform="linux", long_paths=False)) == []
    s = snap(leftovers=["/home/u/.claude"])
    assert ids(s) == ["leftover"] and "nothing installs because of it" in pc.check(s)[0][2]


def test_gather_runs_on_this_machine_without_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    s = pc.gather(home=tmp_path, cwd=str(tmp_path))
    assert s.home == str(tmp_path) and isinstance(pc.check(s), list)
    assert all(re.match(r"^(found|fixed|skipped)$", st) for _, st, _ in pc.check(s))
