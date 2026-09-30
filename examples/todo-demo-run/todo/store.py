"""TodoStore: in-memory todo store with JSON persistence."""

import json
from pathlib import Path
from typing import Dict, List


class TodoStore:
    """A simple in-memory todo store with JSON persistence.

    Manages todos with incrementing IDs starting at 1, tracks completion status,
    and optionally persists to JSON.
    """

    def __init__(self, filepath: str = None):
        """Initialize the store.

        Args:
            filepath: Optional path to persist todos to JSON. If provided and the
                     file exists, todos are loaded from it.
        """
        self._todos: Dict[int, Dict] = {}
        self._next_id: int = 1
        self._filepath = Path(filepath) if filepath else None

        if self._filepath and self._filepath.exists():
            self._load()

    def add(self, title: str) -> int:
        """Add a new todo and return its ID.

        Args:
            title: The title of the todo.

        Returns:
            The incrementing ID assigned to the todo (starting at 1).
        """
        todo_id = self._next_id
        self._todos[todo_id] = {"id": todo_id, "title": title, "done": False}
        self._next_id += 1
        self._save()
        return todo_id

    def list(self) -> List[Dict]:
        """Return all todos.

        Returns:
            List of dicts with keys: id, title, done.
        """
        return list(self._todos.values())

    def complete(self, todo_id: int) -> None:
        """Mark a todo as complete.

        Args:
            todo_id: The ID of the todo to complete.

        Raises:
            KeyError: If the todo ID does not exist.
        """
        if todo_id not in self._todos:
            raise KeyError(f"Todo ID {todo_id} not found")
        self._todos[todo_id]["done"] = True
        self._save()

    def save(self, path: str) -> None:
        """Save todos to JSON file at the given path.

        Args:
            path: The file path to save todos to.
        """
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "todos": self._todos,
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "TodoStore":
        """Load todos from JSON file, returning empty store if file doesn't exist.

        Args:
            path: The file path to load todos from.

        Returns:
            A TodoStore instance with todos loaded from the file, or an empty
            TodoStore if the file does not exist.
        """
        filepath = Path(path)
        store = cls()
        if not filepath.exists():
            return store
        with open(filepath, "r") as f:
            data = json.load(f)
        store._next_id = data.get("next_id", 1)
        todos_data = data.get("todos", {})
        store._todos = {int(k): v for k, v in todos_data.items()}
        return store

    def _save(self) -> None:
        """Persist todos to JSON file if filepath is set."""
        if not self._filepath:
            return
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "todos": self._todos,
        }
        with open(self._filepath, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        """Load todos from JSON file."""
        if not self._filepath or not self._filepath.exists():
            return
        with open(self._filepath, "r") as f:
            data = json.load(f)
        self._next_id = data.get("next_id", 1)
        todos_data = data.get("todos", {})
        self._todos = {int(k): v for k, v in todos_data.items()}
