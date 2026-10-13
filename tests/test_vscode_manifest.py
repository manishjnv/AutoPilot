import json
from pathlib import Path

VS = Path(__file__).resolve().parent.parent / "vscode"


def manifest():
    return json.loads((VS / "package.json").read_text(encoding="utf-8"))


def test_commands_and_view():
    m = manifest()
    ids = {c["command"] for c in m["contributes"]["commands"]}
    assert ids == {"autopilot.start", "autopilot.answer", "autopilot.stop"}
    views = [v["id"] for vs in m["contributes"]["views"].values() for v in vs]
    assert views == ["autopilotStatus"]
    assert m["publisher"] == "manishjnv" and m["name"] == "autopilot-vscode"


def test_no_runtime_dependencies():
    m = manifest()
    assert "dependencies" not in m
    assert set(m["devDependencies"]) == {"@types/vscode", "typescript"}


def test_extension_reads_the_port_file():
    src = (VS / "src" / "extension.ts").read_text(encoding="utf-8")
    assert ".agent" in src and "status.port" in src
    for cmd in ("ap start", "ap answer", "ap stop"):
        assert cmd in src
