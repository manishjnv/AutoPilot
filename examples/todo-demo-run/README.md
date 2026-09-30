# todo

A tiny todo-list Python package with JSON persistence and a CLI.

## Installation

```
pip install .
```

## Usage

After installation, run the `todo` command directly:

```
todo add "buy milk"   # prints: Added 1
todo list             # 1 [ ] buy milk
todo done 1           # prints: Done 1
```

Alternatively, use `python -m todo` in the repo directory.

`done` exits with status 1 if the id does not exist.

The data file is read from the `TODO_FILE` environment variable
(default `./todo.json`).

## Tests

`python -m pytest -q`
