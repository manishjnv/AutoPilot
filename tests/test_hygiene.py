"""Lint tests and package for traps that pass on WSL and fail in CI."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = {"examples/tour/events.jsonl": "scripts/make_tour.py"}


def path_in_platform_line(line):
    return "platform=" in line and "==" in line and "Path(" in line.split("==", 1)[1]


def missing_regenerate_test(generated, test_names):
    return [g for g in generated if not any("regenerate" in n for n in test_names)]


def thin_env(text):
    """Line numbers of Popen/run calls whose env= dict literal lacks a ** spread."""
    bad = []
    for m in re.finditer(r"subprocess\.(?:Popen|run)\(", text):
        call = text[m.start():m.start() + 600]
        e = re.search(r"\benv=\{([^}]*)\}", call)
        if e and "**" not in e.group(1):
            bad.append(text.count("\n", 0, m.start()) + 1)
    return bad


def platform_without_which(text):
    """Names of test functions that fake sys.platform but not shutil.which (py3.13 which calls the Windows API)."""
    bad = []
    for m in re.finditer(r"^def (test_\w+)\(.*?(?=^def |\Z)", text, re.S | re.M):
        body = m.group(0)
        if re.search(r"""setattr\(\s*(?:sys\s*,\s*["']platform["']|["']sys\.platform["'])""", body) and not re.search(
            r"""setattr\(\s*(?:shutil\s*,\s*["']which["']|["']shutil\.which["'])""", body
        ):
            bad.append(m.group(1))
    return bad


def polling_loops(text):
    """Line numbers of while loops that poll a file and sleep: assert at the write instead."""
    lines = text.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("while "):
            continue
        indent = len(line) - len(line.lstrip())
        block = [line]
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            block.append(nxt)
        t = "\n".join(block)
        if "time.sleep(" in t and re.search(r"\.(?:read_text|exists|stat)\(", t):
            bad.append(i + 1)
    return bad


# test file name -> reason the polling loop stays (none yet)
POLL_ALLOWED = {}


def test_rule1_no_path_next_to_platform():
    assert path_in_platform_line('assert f(platform="win32") == Path("a")')
    assert not path_in_platform_line('x = f(platform="win32")')
    for f in (ROOT / "tests").glob("test_*.py"):
        if f.name == "test_hygiene.py":  # holds the rule text itself
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            assert not path_in_platform_line(line), f"{f.name}:{n} expects a Path( on a platform= line"


def test_rule2_generated_files_have_a_regenerate_test():
    assert missing_regenerate_test(["a"], ["test_x"]) == ["a"]
    names = re.findall(r"def (test_\w+)", "\n".join(f.read_text(encoding="utf-8") for f in (ROOT / "tests").glob("test_*.py")))
    for g, script in GENERATED.items():
        assert (ROOT / g).exists() and (ROOT / script).exists(), g
        assert not missing_regenerate_test([g], names), f"{g} has no test named *regenerate*"


def test_rule3_popen_env_keeps_the_host_environment():
    assert thin_env('subprocess.Popen(c, env={"A": "1", "B": "2"})') == [1]
    assert thin_env('subprocess.run(c, env={**os.environ, "A": "1"})') == []
    for f in (ROOT / "autopilot").rglob("*.py"):
        assert not thin_env(f.read_text(encoding="utf-8")), f"{f.name}:{thin_env(f.read_text(encoding='utf-8'))} env= dict without **os.environ"


def test_rule4_sys_platform_fake_also_fakes_shutil_which():
    bad = 'def test_a(monkeypatch):\n    monkeypatch.setattr(sys, "platform", "win32")\n    run()\n'
    bad2 = 'def test_b(monkeypatch):\n    monkeypatch.setattr("sys.platform", "win32")\n'
    ok = bad + '    monkeypatch.setattr(shutil, "which", lambda n: n)\n'
    assert platform_without_which(bad) == ["test_a"]
    assert platform_without_which(bad2) == ["test_b"]
    assert platform_without_which(ok) == []
    for f in (ROOT / "tests").glob("test_*.py"):
        if f.name == "test_hygiene.py":
            continue
        assert not platform_without_which(f.read_text(encoding="utf-8")), f"{f.name} fakes sys.platform without shutil.which"


def test_rule5_no_file_polling_loop_with_sleep():
    bad = "def test_a(p):\n    while not p.exists():\n        time.sleep(0.05)\n"
    bad2 = "while True:\n    if p.read_text() == 'x':\n        break\n    time.sleep(0.05)\n"
    ok = "while n < 3:\n    n += 1\n    time.sleep(0.05)\n"
    assert polling_loops(bad) == [2]
    assert polling_loops(bad2) == [1]
    assert polling_loops(ok) == []
    for f in (ROOT / "tests").glob("test_*.py"):
        if f.name == "test_hygiene.py" or f.name in POLL_ALLOWED:
            continue
        assert not polling_loops(f.read_text(encoding="utf-8")), f"{f.name}: polls a file in a loop with a sleep; assert at the write"
