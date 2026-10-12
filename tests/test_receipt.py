import argparse
import json

from autopilot import receipt
from autopilot.cli import cmd_verify


def phase(tmp_path, monkeypatch, pid="P01"):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path / "home"))
    hist = tmp_path / ".agent" / "history" / pid
    hist.mkdir(parents=True)
    files = []
    for name in ("PROOF.md", "PHASE.md", "P01-T01.md"):
        (hist / name).write_text(f"example {name}\n", encoding="utf-8")
        files.append(hist / name)
    return receipt.write(tmp_path, pid, files, "abc123"), hist


def verify(tmp_path, phase_id=None):
    return cmd_verify(argparse.Namespace(path=str(tmp_path), phase=phase_id))


def test_write_then_check_is_ok(tmp_path, monkeypatch):
    out, _ = phase(tmp_path, monkeypatch)
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["phase"] == "P01" and body["commit"] == "abc123" and len(body["sig"]) == 64
    assert set(body["files"]) == {"PROOF.md", "PHASE.md", "P01-T01.md"}
    assert receipt.check(tmp_path, out) == []


def test_key_is_in_home_not_in_project(tmp_path, monkeypatch):
    phase(tmp_path, monkeypatch)
    assert (tmp_path / "home" / "receipt.key").stat().st_size == 32
    assert not list((tmp_path / ".agent").rglob("receipt.key"))


def test_edit_proof_is_changed(tmp_path, monkeypatch, capsys):
    out, hist = phase(tmp_path, monkeypatch)
    assert verify(tmp_path) == 0 and "P01 ok" in capsys.readouterr().out
    (hist / "PROOF.md").write_text("edited\n", encoding="utf-8")
    assert receipt.check(tmp_path, out) == ["PROOF.md"]
    assert verify(tmp_path) == 1 and "P01 CHANGED: PROOF.md" in capsys.readouterr().out


def test_missing_file_is_reported(tmp_path, monkeypatch):
    out, hist = phase(tmp_path, monkeypatch)
    (hist / "PHASE.md").unlink()
    assert receipt.check(tmp_path, out) == ["PHASE.md missing"]


def test_wrong_key_is_bad_signature(tmp_path, monkeypatch, capsys):
    out, _ = phase(tmp_path, monkeypatch)
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path / "other"))
    assert receipt.check(tmp_path, out) == ["bad signature"]
    assert verify(tmp_path, "P01") == 1 and "bad signature" in capsys.readouterr().out
