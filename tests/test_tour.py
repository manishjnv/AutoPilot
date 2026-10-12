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
