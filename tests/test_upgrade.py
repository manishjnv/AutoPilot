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
    rc = cmd_install(Namespace(rights=False), run=run, urlopen=fake_open(), which=lambda n: "/bin/" + n)
    assert rc == 0 and run.calls[-1][:3] == ["uv", "tool", "install"]
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
