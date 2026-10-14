"""W48a: the input row of the watch window and the You / Reply line."""
from autopilot import inbox
from autopilot.dash_term import frame
from autopilot.dash_web import render
from autopilot.watch_input import Input
from test_dash_term import data as term_data
from test_dash_term import strip


class Keys:
    def __init__(self, *chunks):
        self.chunks = list(chunks)

    def read(self):
        return self.chunks.pop(0) if self.chunks else ""

    def close(self):
        pass


def sent(calls):
    def submit(root, line):
        calls.append(line)
        inbox._append(root, {"id": "a1", "text": line, "kind": "question"})
        inbox._append(root, {"id": "a1", "reply": "T01 runs now (run.json)", "partial": False})
    return submit


def shown(root, inp):
    d = term_data()
    d["input"], d["you"] = inp.row, inbox.recent(root)
    return strip(frame(d, 133, 37))


def test_typing_and_enter_calls_submit_once_and_the_next_frame_shows_you_and_reply(tmp_path):
    calls = []
    inp = Input(tmp_path, Keys("what runs", " now", "\r"), sent(calls))
    assert inp.poll() and inp.row == "what runs"
    assert "> what runs_" in shown(tmp_path, inp)[-2]  # the input row sits above the status bar
    inp.poll()
    inp.poll()
    inp.thread.join()
    assert calls == ["what runs now"] and inp.row == ""
    out = shown(tmp_path, inp)
    assert "You: what runs now  Reply: T01 runs now (run.json)" in out[0] and len(out) == 37


def test_esc_clears_and_backspace_and_arrow_keys_do_not_type(tmp_path):
    inp = Input(tmp_path, Keys("abc", "\x08", "\x1b[A", "\x1b"), lambda r, line: None)
    inp.poll()
    inp.poll()
    assert inp.buf == "ab"
    inp.poll()
    assert inp.buf == "ab"
    inp.poll()
    assert inp.buf == ""


def test_no_tty_no_input_row(tmp_path):
    inp = Input(tmp_path, None, lambda r, line: None)
    assert inp.row is None and not inp.poll()
    out = shown(tmp_path, inp)
    assert len(out) == 37 and not any(x.startswith(" > ") for x in out)


def test_a_partial_reply_grows_across_two_frames_and_the_line_is_cut_to_one_line(tmp_path):
    inbox._append(tmp_path, {"id": "b2", "text": "why slow", "kind": "question"})
    inbox._append(tmp_path, {"id": "b2", "reply": "The tests", "partial": True})
    first = shown(tmp_path, Input(tmp_path, None))[0]
    inbox._append(tmp_path, {"id": "b2", "reply": "The tests take long " * 20, "partial": True})
    second = shown(tmp_path, Input(tmp_path, None))[0]
    assert "Reply: The tests" in first and "take long" not in first
    assert "take long" in second and second.rstrip().endswith("...") and len(second) == 133


def test_the_web_page_holds_the_line_escaped_read_only_and_it_goes_after_60_seconds(tmp_path):
    inbox._append(tmp_path, {"id": "c3", "text": "cost so far", "kind": "question"})
    inbox._append(tmp_path, {"id": "c3", "reply": "$1.20 <b>so far</b>", "partial": False})
    page = render({**term_data(), "you": inbox.recent(tmp_path)})
    assert 'id="you"' in page and "You:" in page and "cost so far" in page and "&lt;b&gt;so far" in page
    assert 'id="you"' not in render(term_data())
    assert "<input" not in page and "<textarea" not in page
    assert inbox.recent(tmp_path, secs=-1) is None
