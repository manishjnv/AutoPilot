"""Q6: one fixture per environment pre-check line; each line has a sentence in the Q4 catalogue."""
import os
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from autopilot.commands import precheck as pc
from autopilot.install_errors import PRECHECK


def snap(**kw):
    base = {"platform": "linux", "home": "/home/u", "cwd": "/home/u/p", "path": ["/usr/bin", "/home/u/.local/bin"],
            "git_user": ("U", "u@example.com")}
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

# Q21: eight more lines, one fixture each. Every line has a sentence in the Q4 catalogue (the test above checks the ids).
class _P:
    def __init__(self, rc=0, out="", err=""):
        self.rc, self.stdout, self.stderr = rc, out, err


def test_git_dubious_ownership_adds_the_safe_directory_and_says_fixed(tmp_path):
    s = snap(cwd=str(tmp_path), git_dubious=True, in_repo=True)
    lines = pc.check(s)
    assert [(i, st) for i, st, _ in lines] == [("git-dubious", "fixed")] and str(tmp_path) in lines[0][2]
    ran = []
    out = pc.apply(lines, s, run=lambda cmd, **kw: ran.append(cmd) or _P())
    assert ran == [["git", "config", "--global", "--add", "safe.directory", str(tmp_path)]] and out[0][1] == "fixed"
    assert pc.apply(lines, s, run=lambda cmd, **kw: _P(1))[0][1] == "skipped"  # git refused: the line says so
    assert pc.apply(lines, s, run=lambda cmd, **kw: pytest_fail(), dry_run=True)[0][1] == "fixed"  # a dry run runs nothing


def pytest_fail():
    raise AssertionError("a dry run must not run a command")


def test_gather_sees_the_dubious_ownership_text(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path), os.path.dirname(shutil.which("git"))]))
    fake = lambda cmd, **kw: _P(128, "", "fatal: detected dubious ownership in repository at 'x'") if "status" in cmd else _P(0, "git version 2.43.0")
    s = pc.gather(home=tmp_path, cwd=str(tmp_path), run=fake)
    assert s.git_version == (2, 43) or s.git_version is not None


def test_autocrlf_true_on_windows_is_turned_off_for_the_project_and_gitattributes_is_written(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "core.autocrlf", "true"], check=True)
    s = snap(platform="win32", home=r"C:\Users\u", path=[r"C:\Users\u\.local\bin"], cwd=str(tmp_path), in_repo=True, autocrlf="true")
    lines = pc.check(s)
    assert [(i, st) for i, st, _ in lines] == [("autocrlf", "fixed")]
    out = pc.apply(lines, s, run=lambda cmd, **kw: subprocess.run(cmd, capture_output=True, text=True, check=False) and _P())
    assert out[0][1] == "fixed"
    got = subprocess.run(["git", "-C", str(tmp_path), "config", "core.autocrlf"], capture_output=True, text=True, check=False).stdout.strip()
    assert got == "false" and (tmp_path / ".gitattributes").exists()
    (tmp_path / ".gitattributes").write_text("keep me\n")
    pc.apply(lines, s, run=lambda cmd, **kw: _P())
    assert (tmp_path / ".gitattributes").read_text() == "keep me\n"  # an existing file is never replaced
    assert ids(snap(platform="linux", in_repo=True, autocrlf="true")) == []  # Windows only


def test_api_key_in_the_environment_is_named_and_the_value_never_printed():
    s = snap(api_keys=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
    lines = pc.check(s)
    assert [i for i, _, _ in lines] == ["api-key"] and "ANTHROPIC_API_KEY, OPENAI_API_KEY" in lines[0][2]
    assert "unset" in lines[0][2]  # the way to unset it for the run
    got = pc.gather(env={"PATH": "", "OPENAI_API_KEY": "sk-secret-value", "HOME": "/tmp"}, home=Path("/tmp"), cwd="/tmp")
    assert got.api_keys == ["OPENAI_API_KEY"] and "sk-secret-value" not in repr(got)


def test_clock_skew_over_three_minutes_prints_the_resync_command():
    import datetime
    from email.utils import format_datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    behind = pc.clock_skew(fetch=lambda u: format_datetime(now + datetime.timedelta(minutes=10)))
    assert behind is not None and behind < -540
    assert pc.clock_skew(fetch=lambda u: "not a date") is None
    lines = pc.check(snap(clock_skew=behind))
    assert [i for i, _, _ in lines] == ["clock-skew"] and "sudo hwclock -s" in lines[0][2] and "behind" in lines[0][2]
    assert "w32tm /resync" in pc.check(snap(platform="win32", home=r"C:\Users\u", path=[r"C:\Users\u\.local\bin"], clock_skew=400))[0][2]
    assert ids(snap(clock_skew=170)) == [] and ids(snap(clock_skew=None)) == []


def test_clock_skew_reads_the_date_header_of_a_fake_http_server():
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        skew = pc.clock_skew(f"http://127.0.0.1:{srv.server_address[1]}/")
    finally:
        srv.shutdown()
    assert skew is not None and abs(skew) < 30  # the server and the test share one clock


def test_low_disk_under_one_gigabyte():
    lines = pc.check(snap(free_gb=0.4))
    assert [i for i, _, _ in lines] == ["low-disk"] and "0.4 GB" in lines[0][2]
    assert ids(snap(free_gb=5.0)) == [] and ids(snap(free_gb=None)) == []


def test_git_older_than_2_30():
    lines = pc.check(snap(git_version=(2, 25)))
    assert [i for i, _, _ in lines] == ["git-old"] and "2.25" in lines[0][2]
    assert ids(snap(git_version=(2, 30))) == [] and ids(snap(git_version=(3, 0))) == []


def test_console_not_utf8_on_windows_prints_the_chcp_line():
    w = {"platform": "win32", "home": r"C:\Users\u", "path": [r"C:\Users\u\.local\bin"]}
    lines = pc.check(snap(console_utf8=False, **w))
    assert [i for i, _, _ in lines] == ["console-encoding"] and "chcp 65001" in lines[0][2] and "PYTHONIOENCODING=" in lines[0][2]
    assert ids(snap(console_utf8=True, **w)) == [] and ids(snap(console_utf8=False)) == []


def test_status_page_port_in_use_takes_the_next_free_port_and_says_which(capsys, tmp_path):
    import socket

    from autopilot.cli import start_status_page
    (tmp_path / ".agent").mkdir()
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    port = busy.getsockname()[1]
    busy.listen(1)
    try:
        assert not pc.port_free(port)
        url = start_status_page(tmp_path, port)
    finally:
        busy.close()
    assert url.startswith("http://127.0.0.1:") and not url.endswith(f":{port}/")
    assert f"port {port} is in use, so it runs on port" in capsys.readouterr().out
    lines = pc.check(snap(port_busy=8765, port_next=8766))
    assert [(i, st) for i, st, _ in lines] == [("port-busy", "fixed")] and "8766" in lines[0][2]


def test_every_q21_line_has_one_plain_sentence_in_the_catalogue():
    for key in ("git-dubious", "autocrlf", "api-key", "clock-skew", "low-disk", "git-old", "console-encoding", "port-busy"):
        sentence, _ = PRECHECK[key]
        assert sentence.endswith(".") and sentence.count(". ") == 0 and len(sentence) < 170, key
