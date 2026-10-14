"""`ap upgrade` and `ap install`: all fakes, no network, no subprocess."""
import hashlib
import json
from argparse import Namespace
from pathlib import Path

from autopilot.proc import Proc
from autopilot.upgrade import (cmd_install, cmd_upgrade, check_once_per_day, detect_install, fetch_wheel,
                               latest_release)

WHEEL = b"fake wheel bytes"
SHA = hashlib.sha256(WHEEL).hexdigest()
WHEEL_URL = "https://example.test/dev_autopilot-0.4.0-py3-none-any.whl"
SUMS_URL = "https://example.test/SHA256SUMS"
GH_JSON = json.dumps({"tagName": "v0.4.0", "assets": [{"name": "dev_autopilot-0.4.0-py3-none-any.whl", "url": WHEEL_URL},
                                                       {"name": "SHA256SUMS", "url": SUMS_URL}]})
API_JSON = json.dumps({"tag_name": "v0.4.0", "assets": [
    {"name": "dev_autopilot-0.4.0-py3-none-any.whl", "browser_download_url": WHEEL_URL},
    {"name": "SHA256SUMS", "browser_download_url": SUMS_URL}]})


def sums(h=SHA):
    return f"{'0' * 64}  install.sh\n{h}  dev_autopilot-0.4.0-py3-none-any.whl\n"


class Resp:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


def fake_open(api=API_JSON, wheel=WHEEL, checksums=None):
    table = {WHEEL_URL: wheel, SUMS_URL: (checksums or sums()).encode()}

    def urlopen(url):
        if url.endswith("/releases/latest") or "/releases/tags/" in url:
            return Resp(api.encode())
        return Resp(table[url])
    return urlopen


class FakeRun:
    """Records every command; `out` maps a command prefix word list to stdout."""
    def __init__(self, out=None):
        self.calls, self.out = [], out or {}

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        return Proc(0, self.out.get(" ".join(cmd[:3]), ""), "")


def no_gh(_):
    return None


def test_gh_json_and_sums_fixture_are_parsed(monkeypatch):
    run = FakeRun({"gh release view": GH_JSON})
    rel = latest_release(run=run, urlopen=fake_open(), which=lambda n: "/bin/gh")
    assert rel == {"tag": "v0.4.0", "wheel_url": WHEEL_URL, "sha256": SHA}
    assert run.calls[0][:3] == ["gh", "release", "view"]


def test_the_public_api_is_used_without_gh():
    rel = latest_release("v0.4.0", run=FakeRun(), urlopen=fake_open(), which=no_gh)
    assert rel["tag"] == "v0.4.0" and rel["sha256"] == SHA


def test_detect_editable_and_pip_and_uv(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "autopilot").mkdir()
    assert detect_install(file=str(tmp_path / "autopilot" / "__init__.py")) == "editable"
    site = tmp_path / "site" / "autopilot"
    site.mkdir(parents=True)
    f = str(site / "__init__.py")
    assert detect_install(file=f, which=lambda n: None) == "pip"
    assert detect_install(file=f, which=lambda n: "/bin/uv", run=FakeRun({"uv tool list": "dev-autopilot v0.3.0"})) == "uv"


def test_a_dirty_checkout_is_not_pulled(capsys, tmp_path):
    run = FakeRun({"git -C " + str(tmp_path): " M file.py\n"})
    rc = cmd_upgrade(Namespace(check=False, ref=None), run=run, detect=lambda: "editable", root=tmp_path)
    assert rc == 1 and not any("pull" in c for c in run.calls)
    assert capsys.readouterr().out.count("git -C") == 1


def test_a_clean_checkout_is_pulled(tmp_path):
    run = FakeRun()
    assert cmd_upgrade(Namespace(check=False, ref=None), run=run, detect=lambda: "editable", root=tmp_path) == 0
    assert ["git", "-C", str(tmp_path), "pull", "--ff-only"] in run.calls


def test_a_current_checkout_says_latest(capsys, tmp_path):
    def run(cmd, **kw):
        return Proc(0, "Already up to date.\n" if "pull" in cmd else "", "")
    assert cmd_upgrade(Namespace(check=False, ref=None), run=run, detect=lambda: "editable", root=tmp_path) == 0
    assert "is the latest" in capsys.readouterr().out


def test_uv_install_passes_the_checked_local_wheel(capsys, monkeypatch):
    monkeypatch.setattr("autopilot.upgrade.__version__", "0.3.0")  # the fake release is v0.4.0, whatever the package says
    run = FakeRun({"gh release view": GH_JSON})
    rc = cmd_upgrade(Namespace(check=False, ref=None), run=run, urlopen=fake_open(), detect=lambda: "uv")
    install = run.calls[-1]
    assert rc == 0 and install[:4] == ["uv", "tool", "install", "--reinstall"]
    path = Path(install[4])
    assert path.read_bytes() == WHEEL and path.name.endswith(".whl")  # the local, hash-checked file, not the URL
    assert "v0.4.0" in capsys.readouterr().out


def test_a_hash_mismatch_refuses(capsys, monkeypatch):
    monkeypatch.setattr("autopilot.upgrade.__version__", "0.3.0")
    run = FakeRun({"gh release view": GH_JSON})
    bad = fake_open(wheel=b"tampered")
    rc = cmd_upgrade(Namespace(check=False, ref=None), run=run, urlopen=bad, detect=lambda: "pip")
    assert rc == 1 and not any(c[0] in ("uv",) or "pip" in c for c in run.calls[1:])
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("refused")


def test_check_never_installs(capsys):
    run = FakeRun({"gh release view": GH_JSON})
    assert cmd_upgrade(Namespace(check=True, ref=None), run=run, urlopen=fake_open(), detect=lambda: "uv") == 0
    assert all(c[0] == "gh" for c in run.calls)


def test_equal_version_is_the_latest(capsys, monkeypatch):
    monkeypatch.setattr("autopilot.upgrade.__version__", "0.4.0")
    run = FakeRun({"gh release view": GH_JSON})
    assert cmd_upgrade(Namespace(check=False, ref=None), run=run, urlopen=fake_open(), detect=lambda: "uv") == 0
    assert "ap 0.4.0 is the latest" in capsys.readouterr().out and len(run.calls) <= 1


def test_fetch_wheel_accepts_a_matching_hash():
    p = fetch_wheel({"wheel_url": WHEEL_URL, "sha256": SHA}, fake_open())
    assert p is not None and p.read_bytes() == WHEEL


def test_install_uses_uv_and_the_checked_wheel(capsys):
    run = FakeRun({"gh release view": GH_JSON})
    done = []
    rc = cmd_install(Namespace(rights=False), run=run, urlopen=fake_open(), which=lambda n: "/bin/" + n,
                     setup=lambda a: done.append(a) or 0)
    assert rc == 0 and run.calls[-1][:3] == ["uv", "tool", "install"] and done  # Q3: `ap setup` runs last
    assert "Open a project folder and type ap" in capsys.readouterr().out


def test_install_rights_runs_the_rights_step(capsys, monkeypatch):
    monkeypatch.setattr("autopilot.rights.have_rights", lambda platform=None: "")
    monkeypatch.setattr("autopilot.rights.setup_rights", lambda *a, **k: ["one line"])
    assert cmd_install(Namespace(rights=True)) == 1  # N5.4: the step ran; no rights afterwards = rc 1
    assert "one line" in capsys.readouterr().out


def test_daily_check_asks_once(tmp_path, monkeypatch):
    monkeypatch.setattr("autopilot.upgrade.__version__", "0.3.0")
    stamp, run, n = tmp_path / "stamp", FakeRun({"gh release view": GH_JSON}), [0]

    def counting(url):
        n[0] += 1
        return fake_open()(url)
    first = check_once_per_day(run=run, urlopen=counting, stamp=stamp, now=lambda: stamp.stat().st_mtime if stamp.exists() else 0)
    again = check_once_per_day(run=run, urlopen=counting, stamp=stamp)
    assert first == again and "0.4.0" in first and n[0] == 1


# ---- T2: ap updates itself, after the command, in a process that starts after this one exits
def _auto(tmp_path, monkeypatch, cmd="status", kind="uv", version="0.3.0", env=None, active=False, **kw):
    from autopilot import upgrade
    monkeypatch.setattr("autopilot.upgrade.__version__", version)
    spawned = []
    line = upgrade.auto_update(cmd, tmp_path, env=env or {}, run=FakeRun({"gh release view": GH_JSON}), urlopen=fake_open(),
                               detect=lambda: kind, spawn=lambda c: spawned.append(c), active=lambda r: active,
                               stamp=tmp_path / "stamp", **kw)
    return line, spawned


def test_auto_update_starts_the_reinstall_once_and_says_so(tmp_path, monkeypatch):
    line, spawned = _auto(tmp_path, monkeypatch)
    assert "updating ap 0.3.0 -> v0.4.0 in the background" in line
    assert spawned and spawned[0][:4] == ["uv", "tool", "install", "--reinstall"] and spawned[0][4].endswith(".whl")
    line, spawned = _auto(tmp_path, monkeypatch)  # the same day: the hint is spent, nothing starts again
    assert line == "" and spawned == []


def test_auto_update_never_runs_during_a_run_in_ci_for_long_commands_or_when_off(tmp_path, monkeypatch):
    assert _auto(tmp_path, monkeypatch, active=True) == ("", [])
    assert _auto(tmp_path, monkeypatch, env={"CI": "1"}) == ("", [])
    assert _auto(tmp_path, monkeypatch, env={"AUTOPILOT_NO_AUTO_UPGRADE": "1"}) == ("", [])
    for cmd in ("run", "start", "watch", "upgrade", "setup", "mcp"):
        assert _auto(tmp_path, monkeypatch, cmd=cmd) == ("", []), cmd
    assert _auto(tmp_path, monkeypatch, version="0.4.0") == ("", [])  # current: nothing
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "project.yaml").write_text("upgrade:\n  auto: false\n", encoding="utf-8")
    assert _auto(tmp_path, monkeypatch) == ("", [])


def test_auto_update_only_hints_for_an_editable_checkout_and_uses_pip_for_pip(tmp_path, monkeypatch):
    line, spawned = _auto(tmp_path, monkeypatch, kind="editable")
    assert "run `ap upgrade`" in line and spawned == []
    line, spawned = _auto(tmp_path / "p", monkeypatch, kind="pip")
    assert spawned[0][1:4] == ["-m", "pip", "install"]


def test_auto_update_never_raises(tmp_path, monkeypatch):
    from autopilot import upgrade

    def boom(*a, **k):
        raise RuntimeError("network on fire")
    assert upgrade.auto_update("status", tmp_path, env={}, run=boom, urlopen=boom, stamp=tmp_path / "s") == ""


# ---- T3: ap uninstall --all
def test_uninstall_all_dry_run_lists_the_steps_and_the_real_run_spawns_the_package_removal(tmp_path, monkeypatch, capsys):
    from autopilot.cli import cmd_uninstall
    home = Path(__import__("os").environ["AUTOPILOT_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "runner").write_text("codex")
    monkeypatch.setattr("autopilot.rights.have_rights", lambda platform=None: "")
    monkeypatch.setattr("autopilot.upgrade.detect_install", lambda *a, **k: "uv")
    assert cmd_uninstall(Namespace(all=True, dry_run=True, rights=False)) == 0
    out = capsys.readouterr().out
    assert f"would delete {home}" in out and "would remove the package (uv)" in out and (home / "runner").exists()
    spawned = []
    assert cmd_uninstall(Namespace(all=True, dry_run=False, rights=False), spawn=spawned.append) == 0
    out = capsys.readouterr().out
    assert not home.exists() and spawned == [["uv", "tool", "uninstall", "dev-autopilot"]] and "Kept:" in out

# ---- W56: before `ap run` / `ap start`, a release install updates first and the same command starts on the new version
def _before(tmp_path, monkeypatch, cmd="run", argv=("run", "--budget", "5"), kind="uv", version="0.3.0", env=None, active=False):
    from autopilot import upgrade
    monkeypatch.setattr("autopilot.upgrade.__version__", version)
    spawned = []
    line = upgrade.update_before_run(cmd, tmp_path, list(argv), env=env or {}, run=FakeRun({"gh release view": GH_JSON}),
                                     urlopen=fake_open(), detect=lambda: kind, active=lambda r: active,
                                     spawn=lambda c, then=None: spawned.append((c, then)), stamp=tmp_path / "stamp")
    return line, spawned


def test_update_before_run_installs_then_relaunches_the_same_command(tmp_path, monkeypatch):
    line, spawned = _before(tmp_path, monkeypatch)
    assert "0.3.0 -> v0.4.0" in line and "`ap run --budget 5` starts by itself" in line and "--ref v0.3.0" in line
    (install, then) = spawned[0]
    assert install[:4] == ["uv", "tool", "install", "--reinstall"] and then == ["ap", "run", "--budget", "5"]
    assert _before(tmp_path, monkeypatch) == ("", [])  # the same day: nothing again


def test_update_before_run_stays_out_of_the_way(tmp_path, monkeypatch):
    assert _before(tmp_path, monkeypatch, cmd="status") == ("", [])
    assert _before(tmp_path, monkeypatch, kind="editable") == ("", [])
    assert _before(tmp_path, monkeypatch, active=True) == ("", [])
    assert _before(tmp_path, monkeypatch, env={"CI": "1"}) == ("", [])
    assert _before(tmp_path, monkeypatch, env={"AUTOPILOT_DETACHED": "1"}) == ("", [])
    assert _before(tmp_path, monkeypatch, version="0.4.0") == ("", [])
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "project.yaml").write_text("upgrade:\n  auto: false\n", encoding="utf-8")
    assert _before(tmp_path, monkeypatch) == ("", [])


def test_update_before_run_never_raises(tmp_path, monkeypatch):
    from autopilot import upgrade
    monkeypatch.setattr("autopilot.upgrade.__version__", "0.3.0")

    def boom(*a, **k):
        raise RuntimeError("no network")
    assert upgrade.update_before_run("run", tmp_path, ["run"], env={}, run=boom, urlopen=boom, stamp=tmp_path / "s") == ""

