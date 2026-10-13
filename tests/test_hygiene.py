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
