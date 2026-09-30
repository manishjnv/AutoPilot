"""autodev CLI."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

import yaml

from . import AGENT_DIR, __version__
from .config import TEMPLATES, Config, load_yaml
from .plan import Plan, PlanError

AGENT_FILES = ["project.yaml", "plan.yaml", "BRAIN.md", "DECISIONS.md", "HANDOFF.md"]


def setup_logging(root: Path, verbose: bool):
    logdir = root / AGENT_DIR / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(logdir / "autodev.log")]
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def detect_stack(root: Path) -> str:
    order = ["node", "python", "go", "rust", "java", "docker", "static"]
    for name in order:
        preset = load_yaml(TEMPLATES / "presets" / f"{name}.yaml")
        if any((root / f).exists() for f in preset.get("detect", [])):
            return name
    return "generic"


# ---------------------------------------------------------------- commands
def cmd_init(args):
    root = Path(args.path).resolve()
    ad = root / AGENT_DIR
    ad.mkdir(parents=True, exist_ok=True)
    stack = args.stack or detect_stack(root)
    for name in AGENT_FILES:
        dst = ad / name
        if dst.exists() and not args.force:
            print(f"keep     {dst.relative_to(root)}")
            continue
        shutil.copy(TEMPLATES / "agent" / name, dst)
        print(f"create   {dst.relative_to(root)}")
    # apply stack preset to project.yaml (text edit keeps the template's comments)
    proj_path = ad / "project.yaml"
    proj = load_yaml(proj_path)
    if args.force or proj.get("stack") in (None, "generic"):
        import re
        preset = load_yaml(TEMPLATES / "presets" / f"{stack}.yaml")
        name = args.name or (proj.get("name") if proj.get("name") not in (None, "my-project") else root.name)
        commands = {**(proj.get("commands") or {}), **preset.get("commands", {})}
        cmd_block = yaml.safe_dump({"commands": commands}, sort_keys=False, width=200).rstrip() + "\n"
        text = proj_path.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^name:.*$", f"name: {name}", text, count=1)
        text = re.sub(r"(?m)^stack:[^#\n]*", f"stack: {stack}            ", text, count=1)
        text = re.sub(r"(?ms)^commands:\n(?:[ \t]+.*\n)*", cmd_block, text, count=1)
        proj_path.write_text(text, encoding="utf-8")
    # gitignore + CLAUDE.md pointer
    gi = root / ".gitignore"
    snippet = (TEMPLATES / "agent" / "gitignore").read_text(encoding="utf-8")
    if not gi.exists() or ".agent/state.db" not in gi.read_text(encoding="utf-8"):
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(snippet)
    cm = root / "CLAUDE.md"
    cm_snip = (TEMPLATES / "agent" / "CLAUDE.md.snippet").read_text(encoding="utf-8")
    if not cm.exists() or "AutoDev" not in cm.read_text(encoding="utf-8"):
        with open(cm, "a", encoding="utf-8") as fh:
            fh.write(cm_snip)
    print(f"\nstack: {stack}\nnext:  autodev onboard --plan-doc <your plan.md>   (or edit .agent/plan.yaml)\n"
          f"       autodev validate && autodev run")


def cmd_onboard(args):
    from .backends import SessionRequest, get_backend
    from .context import render

    root = Path(args.path).resolve()
    if not (root / AGENT_DIR / "project.yaml").exists():
        cmd_init(argparse.Namespace(path=str(root), stack=None, name=None, force=False))
    cfg = Config.load(root)
    plan_doc = Path(args.plan_doc).read_text(encoding="utf-8") if args.plan_doc else \
        "(no plan document — derive a sensible plan from the repository and README)"
    if len(plan_doc) > 150_000:
        plan_doc = plan_doc[:150_000] + "\n…(truncated)…"
    prompt = render("onboard.md", plan_doc=plan_doc)
    system = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
    system += "\nFor THIS onboarding session you ARE allowed to edit the .agent files listed in the assignment."
    backend = get_backend(cfg)
    print(f"running onboarding session ({cfg.get('models.onboard', 'opus')}) …")
    res = backend.run(SessionRequest(prompt=prompt, model=cfg.get("models.onboard", "opus"), cwd=str(root),
                                     timeout_sec=int(cfg.get("agent.session_timeout_sec", 3600)),
                                     budget_usd=float(args.budget), system_append=system,
                                     log_path=str(root / AGENT_DIR / "logs" / "onboard.log")))
    print(res.report.get("summary") or res.text[-1500:] or res.error)
    return cmd_validate(args)


def cmd_validate(args):
    root = Path(args.path).resolve()
    cfg = Config.load(root)
    ok = True
    for e in cfg.validate():
        print(f"config  WARN  {e}")
    try:
        plan = Plan.load(root / AGENT_DIR / "plan.yaml")
        tasks = plan.all_tasks()
        print(f"plan    OK    {len(plan.phases)} phases, {len(tasks)} tasks")
        weak = [t.id for t in tasks if len(t.acceptance_criteria) < 1]
        if weak:
            print(f"plan    WARN  {len(weak)} tasks without acceptance criteria: {', '.join(weak[:10])}"
                  f"{' …' if len(weak) > 10 else ''}")
    except PlanError as e:
        ok = False
        for err in e.errors:
            print(f"plan    ERROR {err}")
    except FileNotFoundError:
        ok = False
        print("plan    ERROR .agent/plan.yaml not found — run `autodev init`")
    return 0 if ok else 1


def cmd_run(args):
    from .orchestrator import Orchestrator

    root = Path(args.path).resolve()
    setup_logging(root, args.verbose)
    stop = root / AGENT_DIR / "STOP"
    if stop.exists() and args.clear_stop:
        stop.unlink()
    orch = Orchestrator(root, max_sessions=args.max_sessions)
    outcome = orch.run()
    print(f"\nrun finished: {outcome}\nreport: {root / AGENT_DIR / 'REPORT.md'}")
    return 0


def _open_state(root: Path):
    from .state import State
    cfg = Config.load(root)
    plan = Plan.load(root / AGENT_DIR / "plan.yaml")
    state = State(root / AGENT_DIR / "state.db")
    state.sync_plan(plan)
    return cfg, plan, state


def cmd_status(args):
    from .report import build_report
    cfg, plan, state = _open_state(Path(args.path).resolve())
    print(build_report(cfg, plan, state))


def cmd_next(args):
    cfg, plan, state = _open_state(Path(args.path).resolve())
    status = dict(state.status_map())
    policy = cfg.get("scheduling.phase_dependency", "soft")
    for i in range(args.n):
        t = plan.next_ready(status, policy)
        if not t:
            break
        ladder = cfg.get(f"models.ladder.{t.risk}")
        print(f"{i + 1:3d}. {t.id:14s} [{t.risk:8s} → {ladder[0]}] {t.title}")
        status[t.id] = "done"


def cmd_unblock(args):
    _, _, state = _open_state(Path(args.path).resolve())
    for tid in args.task_ids:
        if not state.task(tid):
            print(f"unknown task {tid}")
            continue
        state.set_task(tid, status="pending", attempts=0, last_error=None, note=args.note or "unblocked by user")
        print(f"{tid} -> pending")
    if args.note:
        print("note: add hints for the agent to the task description in plan.yaml or to .agent/BRAIN.md")


def cmd_skip(args):
    _, _, state = _open_state(Path(args.path).resolve())
    for tid in args.task_ids:
        state.set_task(tid, status="skipped", note="skipped by user")
        print(f"{tid} -> skipped")


def cmd_approve(args):
    import logging as _l
    from .orchestrator import Orchestrator
    root = Path(args.path).resolve()
    setup_logging(root, False)
    orch = Orchestrator(root)
    row = orch.state.phase(args.phase)
    if not row or row["prod_status"] != "awaiting_approval":
        print(f"phase {args.phase} is not awaiting approval")
        return 1
    orch.reload_plan()
    print(orch.deploy_prod(args.phase, row["prod_ref"]))
    _l.shutdown()
    return 0


def cmd_stop(args):
    p = Path(args.path).resolve() / AGENT_DIR / "STOP"
    p.write_text("stop requested\n")
    print("the run will stop before its next session (remove with `autodev resume`)")


def cmd_resume(args):
    p = Path(args.path).resolve() / AGENT_DIR / "STOP"
    if p.exists():
        p.unlink()
    print("stop flag cleared — start again with `autodev run`")


def cmd_review(args):
    """Manual trigger for an audit or replan outside the normal cadence."""
    from .orchestrator import Orchestrator
    root = Path(args.path).resolve()
    setup_logging(root, args.verbose)
    orch = Orchestrator(root)
    orch.git.ensure_repo(orch.main)
    orch._prepare_repo()
    orch.reload_plan()
    if args.kind == "replan":
        print("replan accepted" if orch.replan("manual") else "replan rejected or failed")
    else:
        rep = orch.audit(args.kind)
        print(rep and {k: rep.get(k) for k in ("complete", "completion_pct", "summary", "_new_phase")})
    orch.write_report()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autodev", description="Autonomous plan-driven development with Claude Code")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("-C", "--path", default=".", help="project root (default: current dir)")
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, "create .agent/ contract (auto-detects stack)")
    p.add_argument("--stack"); p.add_argument("--name"); p.add_argument("--force", action="store_true")
    p = add("onboard", cmd_onboard, "AI session: write BRAIN.md, commands and plan.yaml from a plan doc")
    p.add_argument("--plan-doc"); p.add_argument("--budget", default="15")
    add("validate", cmd_validate, "validate project.yaml and plan.yaml")
    p = add("run", cmd_run, "run autonomously until the app is complete")
    p.add_argument("--max-sessions", type=int); p.add_argument("--clear-stop", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    add("status", cmd_status, "progress, cost, blocked tasks, approvals")
    p = add("next", cmd_next, "preview the next tasks in execution order"); p.add_argument("-n", type=int, default=15)
    p = add("unblock", cmd_unblock, "reset blocked task(s) to pending")
    p.add_argument("task_ids", nargs="+"); p.add_argument("--note")
    p = add("skip", cmd_skip, "skip task(s)"); p.add_argument("task_ids", nargs="+")
    p = add("approve", cmd_approve, "deploy an approved phase to prod"); p.add_argument("phase")
    add("stop", cmd_stop, "graceful stop before the next session")
    add("resume", cmd_resume, "clear the stop flag")
    p = add("review", cmd_review, "run an audit / completion audit / replan now")
    p.add_argument("--kind", choices=["periodic", "completion", "replan"], default="periodic")
    p.add_argument("-v", "--verbose", action="store_true")

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
