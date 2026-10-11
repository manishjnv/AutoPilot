"""N9: `ap mcp` server and its registration in IDE configs."""
import argparse
import contextlib
import io
import json

from autopilot.cli import cmd_init, cmd_status
from autopilot.mcp import serve


def init(root):
    cmd_init(argparse.Namespace(path=str(root), stack="generic", name=None, force=False, quiet=True))


def test_client_initialize_list_status(tmp_path):
    init(tmp_path)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ap_status", "arguments": {}}}]
    out = io.StringIO()
    serve(tmp_path, io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out)
    r = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [x["id"] for x in r] == [1, 2, 3]  # the notification gets no reply
    assert r[0]["result"]["serverInfo"]["name"] == "autopilot"
    assert {t["name"] for t in r[1]["result"]["tools"]} == {"ap_status", "ap_next", "ap_start", "ap_stop", "ap_answer"}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_status(argparse.Namespace(path=str(tmp_path)))
    assert r[2]["result"]["content"][0]["text"] == buf.getvalue().strip() != ""


def test_init_registers_mcp_once_and_keeps_others(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}', encoding="utf-8")
    init(tmp_path)
    init(tmp_path)
    data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"] == {"other": {"command": "x"}, "autopilot": {"command": "ap", "args": ["mcp"]}}
    assert not (tmp_path / ".vscode").exists()
