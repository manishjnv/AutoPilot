"""P12-T01 (W13): a local model (Ollama, LM Studio) through an OpenAI-compatible `/chat/completions` endpoint.

The model has no tools: it returns each file as a fenced block and this backend writes the files into the worktree.
One non-streaming POST per session (ADR 0004). Standard library only. The API key is never logged.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import SessionRequest, SessionResult, parse_report

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
FILE_FORMAT = (
    "You cannot run tools. To create or change a file, write the whole file as a fenced block. The info line of the "
    "fence is exactly `path: <relative path>`, for example ```path: src/app.py . Use forward slashes and a path "
    "relative to the project root; never an absolute path and never `..`. When the file itself contains three "
    "backticks, open and close its block with four backticks. Write only the files you create or change. "
    "End the answer with the JSON report in a ```json block."
)
# Opening fence: 3+ backticks and `path: <rel>`; the closing fence has the same backticks, so a file can hold ``` blocks.
FILE_RX = re.compile(r"^(`{3,})[ \t]*path:[ \t]*([^\n`]+?)[ \t]*\n(.*?)\n?^\1[ \t]*$", re.M | re.S)
_LOCAL = ("127.0.0.1", "localhost", "::1")


def url(cfg) -> str:
    return str(cfg.get("agent.base_url") or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"


def model_name(cfg, alias: str) -> str:
    """`agent.model_map` (ladder alias -> model name); an alias not in the map is sent as is."""
    return str((cfg.get("agent.model_map", {}) or {}).get(alias, alias))


def bad_path(p: str, root: Path) -> bool:
    """True for a path that is empty, absolute, has `..` or `.git`, or resolves outside the worktree."""
    if not p or p.startswith(("/", "\\")) or PurePosixPath(p).is_absolute() or PureWindowsPath(p).is_absolute() \
            or PureWindowsPath(p).drive:
        return True
    if any(part.lower() in ("..", ".git") for part in re.split(r"[/\\]", p)):
        return True
    try:
        (root / p).resolve().relative_to(root)
    except (ValueError, OSError):
        return True
    return False


def write_files(blocks: list[tuple[str, str]], cwd: str) -> str:
    """Check every path first, then write all files. Returns the first refused path ('' = all written)."""
    root = Path(cwd).resolve()
    bad = next((p for p, _ in blocks if bad_path(p, root)), None)
    if bad is not None:
        return bad or "(empty)"
    for p, body in blocks:
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body + "\n", encoding="utf-8", newline="")  # the regex drops the newline before the closing fence
    return ""


class OpenAICompatBackend:
    def __init__(self, cfg):
        self.cfg = cfg

    def log(self, req: SessionRequest, lines: list[str]) -> None:
        from ..signals import redact  # lazy: signals imports this package
        if req.log_path:  # URL, model, status and the answer: never headers, never the key
            try:
                Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
                Path(req.log_path).write_text(redact("\n".join(lines) + "\n"), encoding="utf-8")
            except OSError:
                pass

    def run(self, req: SessionRequest) -> SessionResult:
        target, model = url(self.cfg), model_name(self.cfg, req.model)
        if urllib.parse.urlsplit(target).scheme not in ("http", "https"):
            return SessionResult(ok=False, error="agent.base_url must start with http:// or https://")
        system = (req.system_append + "\n\n" if req.system_append else "") + FILE_FORMAT
        body = json.dumps({"model": model, "stream": False, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": req.prompt}]}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        key_env = self.cfg.get("agent.api_key_env")
        key = os.environ.get(str(key_env)) if key_env else ""
        if key and urllib.parse.urlsplit(target).scheme == "http" and (urllib.parse.urlsplit(target).hostname or "") not in _LOCAL:
            return SessionResult(ok=False, error="agent.base_url is http:// and not local: the key would travel in clear text; use https://")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        host = urllib.parse.urlsplit(target).hostname or ""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if host in _LOCAL \
            else urllib.request.build_opener()  # a local runner never goes through an env proxy
        start = time.monotonic()
        try:
            with opener.open(urllib.request.Request(target, data=body, headers=headers, method="POST"),
                             timeout=req.timeout_sec) as resp:
                status, raw = resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace") if e.fp else ""
            self.log(req, [f"POST {target}", f"model: {model}", f"HTTP {e.code}", text])
            err = f"endpoint returned HTTP {e.code}: {text[:500]}"
            return SessionResult(ok=False, text=text, error=err, infra="network" if e.code >= 500 else "")
        except TimeoutError:
            return SessionResult(ok=False, timed_out=True, error=f"session timed out after {req.timeout_sec}s")
        except (urllib.error.URLError, OSError) as e:
            return SessionResult(ok=False, error=f"cannot reach {target}: {getattr(e, 'reason', e)}", infra="network")
        duration = int((time.monotonic() - start) * 1000)
        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError):
            self.log(req, [f"POST {target}", f"model: {model}", f"HTTP {status}", raw])
            return SessionResult(ok=False, text=raw, error="the endpoint answer is not a chat completion")
        self.log(req, [f"POST {target}", f"model: {model}", f"HTTP {status}", content])
        blocks = [(m.group(2).strip(), m.group(3)) for m in FILE_RX.finditer(content)]
        report = parse_report(FILE_RX.sub("", content))  # a ```json block inside a file is never the report
        if not (req.read_only or req.no_tools):
            refused = write_files(blocks, req.cwd)
            if refused:
                return SessionResult(ok=False, text=content, report=report,
                                     error=f"refused file path outside the worktree: {refused}")
        u = data.get("usage") or {}
        usage = {model: {"input": int(u["prompt_tokens"] or 0), "output": int(u["completion_tokens"] or 0), "cache_read": 0,
                         "cache_write": 0, "cost": 0.0}} \
            if isinstance(u, dict) and "prompt_tokens" in u and "completion_tokens" in u else {}
        return SessionResult(ok=True, text=content, report=report, cost=0.0, session_id=str(data.get("id") or ""),
                             num_turns=1, duration_ms=duration, usage=usage)
