"""Command-line interface: python -m todo add|list|done."""

import argparse
import os
import sys
from typing import List, Optional

from todo.store import TodoStore

DEFAULT_FILE = "todo.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="Tiny todo list.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_add = sub.add_parser("add", help="add a todo")
    p_add.add_argument("title", help="title of the todo")
    sub.add_parser("list", help="list todos")
    p_done = sub.add_parser("done", help="mark a todo as done")
    p_done.add_argument("id", type=int, help="id of the todo")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CLI; returns the process exit code."""
    args = build_parser().parse_args(argv)
    store = TodoStore(os.environ.get("TODO_FILE", DEFAULT_FILE))
    if args.command == "add":
        print(f"Added {store.add(args.title)}")
    elif args.command == "list":
        for t in store.list():
            print(f"{t['id']} [{'x' if t['done'] else ' '}] {t['title']}")
    else:
        try:
            store.complete(args.id)
        except KeyError:
            print(f"error: todo {args.id} not found", file=sys.stderr)
            return 1
        print(f"Done {args.id}")
    return 0
