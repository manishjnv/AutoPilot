import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "examples" / "tour" / "events.jsonl"


def load():
    return [json.loads(ln) for ln in EVENTS.read_text(encoding="utf-8").splitlines()]


def test_events_parse_and_t_rises():
    ev = load()
    assert len(ev) >= 40
    assert EVENTS.stat().st_size < 200_000
    for e in ev:
        assert {"t", "kind", "message", "task_id", "state", "usage"} <= set(e)
    ts = [e["t"] for e in ev]
    assert all(a < b for a, b in zip(ts, ts[1:]))


def test_no_local_data_or_secret_shapes():
    from autopilot.log_scrub import scrub_secrets
    text = EVENTS.read_text(encoding="utf-8")
    for bad in ("C:" + chr(92) + "Users", "C:" + chr(92) * 2 + "Users", "/home/", "@"):
        assert bad not in text
    assert not re.search(r"sk-[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{10,}|AKIA[A-Z0-9]{12,}", text)
    local = {"HOME": str(Path.home())}
    assert scrub_secrets(text, local) == text


def test_make_tour_regenerates_the_same_file(tmp_path):
    out = tmp_path / "events.jsonl"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_tour.py"),
                        str(ROOT / "examples" / "self-build"), str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == EVENTS.read_bytes()


def test_tour_proof_has_outcome_and_not_proven():
    md = (ROOT / "examples" / "tour" / "PROOF.md").read_text(encoding="utf-8")
    assert "Outcome: VERIFIED" in md and "## Not proven" in md


def run_tour(tmp_path, *extra):
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    work = tmp_path / "work"; work.mkdir(exist_ok=True)
    env = {"PATH": str(tmp_path / "empty"), "HOME": str(home), "USERPROFILE": str(home), "AUTOPILOT_HOME": str(home / ".ap"),
           "PYTHONPATH": __import__("os").pathsep.join([str(ROOT), *sys.path]), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    r = subprocess.run([sys.executable, "-m", "autopilot", "tour", "--once", *extra], cwd=work, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    return r, work, home


def test_tour_once_prints_outcome_and_install_line(tmp_path):
    r, work, home = run_tour(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "VERIFIED" in r.stdout
    assert "uv tool install dev-autopilot" in r.stdout
    assert "Start: ap" in r.stdout
    assert "Not proven" in r.stdout


def test_tour_writes_nothing(tmp_path):
    r, work, home = run_tour(tmp_path)
    assert r.returncode == 0, r.stderr
    assert list(work.iterdir()) == [] and list(home.iterdir()) == []


def test_packaged_copy_matches_examples():
    pkg = ROOT / "autopilot" / "templates" / "tour"
    for name in ("events.jsonl", "PROOF.md"):
        assert (pkg / name).read_bytes() == (ROOT / "examples" / "tour" / name).read_bytes()


def test_snapshot_progresses():
    from autopilot.commands.tour import load_events, snapshot
    ev = load_events()
    a, b = snapshot(ev, ev[-1]["t"] / 2), snapshot(ev, ev[-1]["t"])
    assert 0 < a["progress"]["done"] < b["progress"]["done"] == b["progress"]["total"]
