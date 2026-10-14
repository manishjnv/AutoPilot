"""W48a: the input row of `ap watch`. Keys are read without blocking the draw loop; Enter sends the line to
inbox.submit in its own thread (a command or a local answer runs synchronously there). No tty: no input row."""
from __future__ import annotations

import sys
import threading


class TtyKeys:
    """Non-blocking key source for a terminal: msvcrt on Windows, cbreak + select on POSIX. close() restores the tty."""

    def __init__(self):
        self._old = None
        if sys.platform == "win32":
            return
        import termios
        import tty
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)  # ISIG stays on: Ctrl+C still raises KeyboardInterrupt

    def read(self) -> str:
        out = ""
        if sys.platform == "win32":
            import msvcrt
            while msvcrt.kbhit():
                c = msvcrt.getwch()
                if c in ("\x00", "\xe0"):  # a function or arrow key: drop its second code
                    msvcrt.getwch()
                    continue
                out += c
            return out
        import os
        import select
        while select.select([self._fd], [], [], 0)[0]:
            chunk = os.read(self._fd, 64).decode("utf-8", "replace")
            if not chunk:
                break
            out += chunk
        return out

    def close(self):
        if self._old is not None:
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            self._old = None


def open_keys():
    """A key source, or None when stdin is not a terminal (then the screen has no input row)."""
    try:
        return TtyKeys() if sys.stdin and sys.stdin.isatty() else None
    except Exception:  # noqa: BLE001 — no termios, odd console
        return None


class Input:
    """The typed text. poll() reads the keys and returns True when the text changed or a line was sent."""

    def __init__(self, root, keys, submit=None):
        from . import inbox
        self.root, self.keys, self.buf, self.thread = root, keys, "", None
        self.submit = submit or inbox.submit

    @property
    def row(self) -> str | None:
        return None if self.keys is None else self.buf

    def feed(self, text: str) -> bool:
        before, i = self.buf, 0
        while i < len(text):
            c = text[i]
            i += 1
            if c == "\x03":
                raise KeyboardInterrupt
            if c == "\x1b":
                if text[i:i + 1] in ("[", "O"):  # an arrow key: skip the sequence
                    j = i + 1
                    while j < len(text) and not text[j].isalpha() and text[j] != "~":
                        j += 1
                    i = j + 1
                else:
                    self.buf = ""
            elif c in ("\r", "\n"):
                line, self.buf = self.buf.strip(), ""
                if line:
                    self.thread = threading.Thread(target=self.submit, args=(self.root, line), daemon=True)
                    self.thread.start()
                    before = None  # a sent line always counts as a change
            elif c in ("\x08", "\x7f"):
                self.buf = self.buf[:-1]
            elif c.isprintable():
                self.buf = (self.buf + c)[:300]
        return before is None or self.buf != before

    def poll(self) -> bool:
        return self.keys is not None and self.feed(self.keys.read())

    def close(self):
        if self.keys is not None:
            self.keys.close()
