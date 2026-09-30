"""Tests for TodoStore."""

import json
import tempfile
from pathlib import Path

import pytest

from todo import TodoStore


class TestTodoStoreBasics:
    """Test core TodoStore functionality."""

    def test_add_returns_incrementing_ids_starting_at_1(self):
        """Verify add() returns incrementing IDs starting at 1."""
        store = TodoStore()
        assert store.add("First task") == 1
        assert store.add("Second task") == 2
        assert store.add("Third task") == 3

    def test_list_returns_todos_with_correct_structure(self):
        """Verify list() returns todos with id, title, done keys."""
        store = TodoStore()
        store.add("Task 1")
        store.add("Task 2")

        todos = store.list()
        assert len(todos) == 2

        assert todos[0] == {"id": 1, "title": "Task 1", "done": False}
        assert todos[1] == {"id": 2, "title": "Task 2", "done": False}

    def test_list_returns_empty_list_initially(self):
        """Verify list() returns empty list for new store."""
        store = TodoStore()
        assert store.list() == []

    def test_complete_marks_todo_done(self):
        """Verify complete() marks a todo as done."""
        store = TodoStore()
        store.add("Task to complete")

        store.complete(1)
        todos = store.list()

        assert len(todos) == 1
        assert todos[0]["done"] is True

    def test_complete_raises_keyerror_for_unknown_id(self):
        """Verify complete() raises KeyError for unknown IDs."""
        store = TodoStore()
        store.add("Task 1")

        with pytest.raises(KeyError):
            store.complete(999)

    def test_complete_preserves_title_and_id(self):
        """Verify complete() preserves title and ID."""
        store = TodoStore()
        store.add("Important task")
        store.complete(1)

        todos = store.list()
        assert todos[0]["title"] == "Important task"
        assert todos[0]["id"] == 1


class TestTodoStorePersistence:
    """Test JSON persistence functionality."""

    def test_persistence_saves_todos_to_file(self):
        """Verify todos are saved to JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "todos.json"

            store = TodoStore(str(filepath))
            store.add("Task 1")
            store.add("Task 2")
            store.complete(1)

            assert filepath.exists()

            with open(filepath) as f:
                data = json.load(f)

            assert data["next_id"] == 3
            assert len(data["todos"]) == 2
            assert data["todos"]["1"]["done"] is True
            assert data["todos"]["2"]["done"] is False

    def test_persistence_loads_todos_from_file(self):
        """Verify todos are loaded from JSON file on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "todos.json"

            store1 = TodoStore(str(filepath))
            store1.add("Persisted task 1")
            store1.add("Persisted task 2")
            store1.complete(1)

            store2 = TodoStore(str(filepath))
            todos = store2.list()

            assert len(todos) == 2
            assert todos[0]["done"] is True
            assert todos[1]["done"] is False

    def test_persistence_continues_incrementing_ids(self):
        """Verify ID counter continues after loading from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "todos.json"

            store1 = TodoStore(str(filepath))
            store1.add("Task 1")
            store1.add("Task 2")

            store2 = TodoStore(str(filepath))
            new_id = store2.add("Task 3")

            assert new_id == 3
            assert len(store2.list()) == 3

    def test_persistence_without_filepath_still_works(self):
        """Verify store works without persistence filepath."""
        store = TodoStore()
        store.add("In-memory task")

        todos = store.list()
        assert len(todos) == 1
        assert todos[0]["title"] == "In-memory task"

    def test_persistence_creates_parent_directories(self):
        """Verify store creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "subdir" / "nested" / "todos.json"

            store = TodoStore(str(filepath))
            store.add("Task 1")

            assert filepath.exists()
            assert filepath.parent.exists()


class TestSaveAndLoadMethods:
    """Test public save() and load() methods."""

    def test_save_method_persists_todos_to_file(self):
        """Verify save() method persists todos to a specified file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "todos.json"

            store = TodoStore()
            store.add("Task 1")
            store.add("Task 2")
            store.complete(1)
            store.save(str(filepath))

            assert filepath.exists()
            with open(filepath) as f:
                data = json.load(f)

            assert data["next_id"] == 3
            assert data["todos"]["1"]["done"] is True
            assert data["todos"]["2"]["done"] is False

    def test_load_method_returns_empty_store_for_missing_file(self):
        """Verify load() returns empty store if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "nonexistent.json"

            store = TodoStore.load(str(filepath))
            assert store.list() == []

    def test_roundtrip_save_load_preserves_items_and_next_id(self):
        """Verify round-trip save/load preserves items and next ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "todos.json"

            # Create and populate store
            store1 = TodoStore()
            id1 = store1.add("First task")
            id2 = store1.add("Second task")
            id3 = store1.add("Third task")
            store1.complete(id1)
            store1.complete(id3)
            store1.save(str(filepath))

            # Load from file
            store2 = TodoStore.load(str(filepath))

            # Verify items are preserved
            todos = store2.list()
            assert len(todos) == 3
            assert todos[0]["id"] == 1
            assert todos[0]["title"] == "First task"
            assert todos[0]["done"] is True
            assert todos[1]["id"] == 2
            assert todos[1]["title"] == "Second task"
            assert todos[1]["done"] is False
            assert todos[2]["id"] == 3
            assert todos[2]["title"] == "Third task"
            assert todos[2]["done"] is True

            # Verify next ID continues correctly
            new_id = store2.add("Fourth task")
            assert new_id == 4
            assert len(store2.list()) == 4

    def test_save_creates_parent_directories(self):
        """Verify save() creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "deep" / "nested" / "path" / "todos.json"

            store = TodoStore()
            store.add("Task 1")
            store.save(str(filepath))

            assert filepath.exists()
            assert filepath.parent.exists()

    def test_load_method_with_in_memory_store_roundtrip(self):
        """Verify load() classmethod correctly restores all data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "todos.json"

            # Create an in-memory store and save it
            store1 = TodoStore()
            store1.add("Task A")
            store1.add("Task B")
            store1.add("Task C")
            store1.complete(2)
            store1.save(str(filepath))

            # Load using classmethod
            store2 = TodoStore.load(str(filepath))

            # Verify completeness
            todos = store2.list()
            assert len(todos) == 3
            assert todos[1]["done"] is True
            assert store2.list()[0] == {"id": 1, "title": "Task A", "done": False}
