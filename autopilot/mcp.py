"""N9: `ap mcp`, a stdio MCP server (JSON-RPC 2.0, one JSON object per line). Stdlib only."""
from __future__ import annotations

import contextlib
import io
import json
import sys

from . import __version__

_ARGS = {"type": "object", "properties": {}}
TOOLS = {
    "ap_status": ("Show progress, cost, blocked tasks and approvals.", _ARGS),
    "ap_next": ("Preview the next tasks in execution order.", _ARGS),
    "ap_start": ("Start or continue the build in the background.", _ARGS),
    "ap_stop": ("Stop the run before its next session.", _ARGS),
    "ap_answer": ("Answer an open decision.", {
        "type": "object", "required": ["id", "text"],
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}),
}


def call_tool(name, arguments, root):
    from .cli import main
    cmd = {"ap_status": ["status"], "ap_next": ["next"], "ap_start": ["start"], "ap_stop": ["stop"],
           "ap_answer": ["answer", str(arguments.get("id", "")), str(arguments.get("text", ""))]}[name]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            main(cmd + ["-C", str(root)])  # same code path as the `ap` command
    except SystemExit as e:
        if e.code not in (0, None):
            out.write(f"\n(exit {e.code})")
    return out.getvalue().strip()


def handle(msg, root):
    """One JSON-RPC message in, the response dict out (None for a notification)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": "autopilot", "version": __version__}}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in TOOLS.items()]}
    elif method == "tools/call":
        p = msg.get("params") or {}
        if p.get("name") not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {p.get('name')}"}}
        try:
            text, err = call_tool(p["name"], p.get("arguments") or {}, root), False
        except Exception as e:  # a tool failure is a result, not a protocol error
            text, err = f"error: {e}", True
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def serve(root, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            resp = handle(json.loads(line), root)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()


# (path under the project, key of the server map); a file is used when it exists or its folder exists
MCP_FILES = [(".mcp.json", "mcpServers"), (".cursor/mcp.json", "mcpServers"), (".vscode/mcp.json", "servers"),
             (".kilocode/mcp.json", "mcpServers"), (".junie/mcp/mcp.json", "mcpServers")]
SNIPPET = '"autopilot": {"command": "ap", "args": ["mcp"]}'
GLOBAL_FILES = ["~/.gemini/settings.json", "~/.kiro/settings/mcp.json", "~/.codeium/windsurf/mcp_config.json",
                "claude_desktop_config.json"]


def register(root):
    """Merge the `autopilot` server into each project MCP config that exists; other entries stay."""
    for rel, key in MCP_FILES:
        path = root / rel
        if not (path.is_file() or (rel != ".mcp.json" and path.parent.is_dir())):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except ValueError:
            print(f"skip     {rel} (not valid JSON)")
            continue
        entry = {"command": "ap", "args": ["mcp"]}
        if data.setdefault(key, {}).get("autopilot") == entry:
            print(f"keep     {rel}")
            continue
        data[key]["autopilot"] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"update   {rel}")
    print(f"MCP: add {SNIPPET} under \"mcpServers\" in " + ", ".join(GLOBAL_FILES) + " (Autopilot does not edit them).")
