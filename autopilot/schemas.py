"""JSON Schemas for session reports. The claude_cli backend passes them as `--json-schema`, so the CLI hands back a
validated `structured_output` instead of a JSON block regex-parsed out of prose. Loose on purpose: typed fields, few
required ones. The prompts still describe the same report, for backends that only return text."""
from __future__ import annotations

S = {"type": "string"}
A = {"type": "array", "items": S}
STATUS = {"type": "string", "enum": ["done", "blocked"]}


def obj(required=(), **props) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}


RCA = obj(symptom=S, root_cause=S, fix=S, prevention=S)
GAP = obj(["title"], title=S, kind=S, risk=S, related_task=S, description=S, acceptance_criteria=A, files_in_scope=A)

REPORTS = {  # session kind -> schema of its final report
    "task": obj(["status", "summary"], status=STATUS, summary=S, files_changed=A, tests_added=A, docs_updated=A,
                decisions=A, followups=A, rca=RCA, blocker=S, learning=S),
    "fixer": obj(["status", "summary"], status=STATUS, summary=S, root_cause=S, rca=RCA, decisions=A, blocker=S),
    "unstick": obj(["class"], **{"class": {"type": "string", "enum": ["technical", "spec", "owner"]}}, diagnosis=S,
                   decision=S, options_considered=A, question=S, checked=S, why=S, suggestion=S),
    "audit": obj(["complete", "gaps"], complete={"type": "boolean"}, completion_pct={"type": "number"}, summary=S,
                 gaps={"type": "array", "items": GAP}),
    "replan": obj(["summary"], summary=S, changed=A, added=A, removed=A, reopened=A),
    "research": obj(["summary", "sources"], topic=S, summary=S, findings=A, pitfalls=A, recommendation=S,
                    sources={"type": "array", "items": obj(["url"], title=S, url=S)}),
    "verify": obj(["features"], summary=S, features={"type": "array", "items": obj(
        ["id", "passes"], id=S, passes={"type": "boolean"}, evidence=S)}),
    "decide": obj(["title", "options", "decision"], title=S, context=S, criteria=A, decision=S, rationale=S,
                  consequences=A, options={"type": "array", "items": obj(["name"], name=S, summary=S, pros=A, cons=A,
                                                                          score={"type": "number"})}),
}
