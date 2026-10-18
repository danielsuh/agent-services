"""Grade a test file written by another agent.

Agreed checks (these are stated in the request post, word for word in REQUEST_CHECKS):
  1. Safe to run: standard library only, no file, network, process or introspection tricks.
  2. At least MIN_TESTS test cases.
  3. Every test passes on the reference implementation (run twice to catch flaky tests).
  4. The suite catches at least MIN_KILLS of the private broken versions
     (a broken version is caught when at least one test fails or errors on it).
  5. Each run finishes within RUN_TIMEOUT seconds.

The peer code is untrusted. It is parsed with ast and rejected before execution if it uses
anything outside a small allow list, then run in a fresh temporary directory with python -I,
an empty environment, resource limits and a timeout, under an audit hook that blocks writes,
network and subprocesses.
"""
from __future__ import annotations

import ast
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from cost import mutants as M  # noqa: E402

MIN_TESTS = 8
MIN_KILLS = 7
RUN_TIMEOUT = 20
MAX_SOURCE_CHARS = 40_000

ALLOWED_IMPORTS = {"unittest", "math", "pytest", "cost_estimator", "decimal", "fractions",
                   "copy", "itertools", "functools", "typing", "dataclasses", "collections"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
                "getattr", "setattr", "delattr", "breakpoint", "input", "help", "exit", "quit",
                "memoryview", "__builtins__", "__loader__", "__spec__", "importlib"}
ALLOWED_DUNDER_ATTRS = {"__init__", "__name__"}

REQUEST_CHECKS = (
    "1) the file uses only the Python standard library (unittest, or plain assert functions) and "
    "does not touch files, the network, subprocesses or introspection; "
    "2) it has at least %d test cases; "
    "3) every test passes on my reference implementation, run twice; "
    "4) the suite catches at least %d of %d deliberately broken versions I keep privately "
    "(a version is caught when at least one test fails on it); "
    "5) each run finishes in under %d seconds."
) % (MIN_TESTS, MIN_KILLS, len(M.MUTANTS), RUN_TIMEOUT)


# ----------------------------------------------------------------------------
# Extracting code from a forum entry
# ----------------------------------------------------------------------------
def extract_code(raw_html: str) -> str | None:
    """Pull a Python test file out of a Canvas entry body, keeping indentation."""
    text = raw_html or ""
    # 1. explicit markers, in plain text or html
    plain = _html_to_text_keep_spaces(text)
    m = re.search(r"BEGIN TESTS\s*\n(.*?)\n\s*END TESTS", plain, re.S)
    if m:
        return _dedent_block(m.group(1))
    # 2. <pre> blocks (Canvas rich content editor)
    pres = re.findall(r"<pre[^>]*>(.*?)</pre>", text, re.S | re.I)
    if pres:
        best = max(pres, key=len)
        return _dedent_block(html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"(?i)<br\s*/?>", "\n", best))))
    # 3. markdown fences
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", plain, re.S)
    if m:
        return _dedent_block(m.group(1))
    return None


def _html_to_text_keep_spaces(text: str) -> str:
    t = re.sub(r"(?i)<br\s*/?>", "\n", text)
    t = re.sub(r"(?i)</p>\s*<p[^>]*>", "\n", t)
    t = re.sub(r"(?i)</?(p|div|li|ul|ol|h[1-6])[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace(" ", " ").replace("\r\n", "\n")
    return t


def _dedent_block(code: str) -> str:
    import textwrap
    code = code.replace(" ", " ").replace("\t", "    ").strip("\n")
    return textwrap.dedent(code).strip() + "\n"


# ----------------------------------------------------------------------------
# Static safety check
# ----------------------------------------------------------------------------
def static_check(source: str) -> list[str]:
    problems = []
    if len(source) > MAX_SOURCE_CHARS:
        return ["file is longer than %d characters" % MAX_SOURCE_CHARS]
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ["syntax error on line %s: %s" % (e.lineno, e.msg)]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append("import of %s is not allowed" % a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                problems.append("import from %s is not allowed" % (node.module or "relative module"))
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            problems.append("use of %s is not allowed" % node.id)
        elif isinstance(node, ast.Attribute):
            a = node.attr
            if a.startswith("__") and a.endswith("__") and a not in ALLOWED_DUNDER_ATTRS:
                problems.append("access to %s is not allowed" % a)
            if a in BANNED_NAMES:
                problems.append("use of .%s is not allowed" % a)
    seen, unique = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[:10]


# ----------------------------------------------------------------------------
# Sandboxed execution
# ----------------------------------------------------------------------------
def _limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (RUN_TIMEOUT, RUN_TIMEOUT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
        except (ValueError, OSError):
            pass  # macOS does not support RLIMIT_AS
    except Exception:
        pass
    os.setsid() if hasattr(os, "setsid") else None


def run_suite(test_source: str, impl_source: str) -> dict:
    work = Path(tempfile.mkdtemp(prefix="peer_tests_"))
    try:
        (work / "cost_estimator.py").write_text(impl_source)
        (work / "peer_tests.py").write_text(test_source)
        marker = "RESULT-" + secrets.token_hex(8) + ":"
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-B", str(HERE / "harness.py"), str(work), marker],
                cwd=str(work), env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"},
                capture_output=True, text=True, timeout=RUN_TIMEOUT, preexec_fn=_limits,
                stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout", "collected": 0, "results": []}
        line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith(marker)), None)
        if line is None:
            return {"ok": False, "error": "no_result (exit %s): %s" % (proc.returncode, proc.stderr[-300:]),
                    "collected": 0, "results": []}
        data = json.loads(line[len(marker):])
        data["ok"] = data.get("import_error") is None
        if not data["ok"]:
            data["error"] = data["import_error"]
        return data
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _all_pass(run: dict) -> bool:
    return run["ok"] and run["collected"] > 0 and all(r["status"] in ("pass", "skip") for r in run["results"])


def _caught(run: dict) -> bool:
    return (not run["ok"]) or any(r["status"] in ("fail", "error") for r in run["results"])


def grade(test_source: str) -> dict:
    """Run every agreed check. Returns a report dict; report['verdict'] is accept or needs_correction."""
    report = {"sha256": hashlib.sha256(test_source.encode()).hexdigest()[:16],
              "checks": {}, "mutants": [], "verdict": None, "reasons": []}
    problems = static_check(test_source)
    report["checks"]["safe_to_run"] = {"pass": not problems, "problems": problems}
    if problems:
        report["verdict"] = "needs_correction"
        report["reasons"].append("not run because the static safety check failed: " + "; ".join(problems))
        return report

    ref = M.reference_source()
    first, second = run_suite(test_source, ref), run_suite(test_source, ref)
    n = first.get("collected", 0)
    report["checks"]["enough_tests"] = {"pass": n >= MIN_TESTS, "collected": n, "required": MIN_TESTS}
    failing = [r for r in first.get("results", []) if r["status"] not in ("pass", "skip")]
    ref_ok = _all_pass(first) and _all_pass(second)
    report["checks"]["passes_on_reference"] = {
        "pass": ref_ok, "error": first.get("error"), "failing": failing[:5],
        "stable_across_two_runs": [r["status"] for r in first.get("results", [])]
                                  == [r["status"] for r in second.get("results", [])]}
    report["checks"]["within_time"] = {"pass": first.get("error") != "timeout",
                                       "seconds": first.get("seconds")}

    if ref_ok:
        kills = 0
        for name, desc, src in M.mutant_sources():
            run = run_suite(test_source, src)
            caught = _caught(run)
            kills += caught
            failed_by = [r["name"] for r in run.get("results", []) if r["status"] in ("fail", "error")][:3]
            report["mutants"].append({"name": name, "description": desc, "caught": caught,
                                      "caught_by": failed_by, "timeout": run.get("error") == "timeout"})
        report["checks"]["catches_broken_versions"] = {"pass": kills >= MIN_KILLS, "caught": kills,
                                                       "total": len(M.MUTANTS), "required": MIN_KILLS}
        if any(m["timeout"] for m in report["mutants"]):
            report["checks"]["within_time"]["pass"] = False
    else:
        report["checks"]["catches_broken_versions"] = {"pass": False, "caught": 0, "total": len(M.MUTANTS),
                                                       "required": MIN_KILLS,
                                                       "note": "not measured: suite must pass on the reference first"}

    for key, c in report["checks"].items():
        if not c["pass"]:
            report["reasons"].append(_reason(key, c, report))
    report["verdict"] = "accept" if not report["reasons"] else "needs_correction"
    return report


def _reason(key, c, report):
    if key == "enough_tests":
        return "found %d test cases, at least %d are required" % (c["collected"], c["required"])
    if key == "passes_on_reference":
        if c.get("error"):
            return "the file did not load: %s" % c["error"]
        names = ", ".join(f["name"] for f in c["failing"]) or "a test was unstable between two runs"
        return "these tests fail on the correct implementation, so their expected values disagree with the spec: " + names
    if key == "catches_broken_versions":
        if "note" in c:
            return "broken version check " + c["note"]
        missed = [m["description"] for m in report["mutants"] if not m["caught"]]
        return "caught %d of %d broken versions (need %d); bugs that got through: %s" % (
            c["caught"], c["total"], c["required"], "; ".join(missed))
    if key == "within_time":
        return "a run took longer than %d seconds" % RUN_TIMEOUT
    return key


def summary_text(report: dict) -> str:
    """A short plain text summary for the forum reply."""
    c = report["checks"]
    parts = []
    if not c["safe_to_run"]["pass"]:
        return "I did not run the file because it failed the safety check: " + "; ".join(c["safe_to_run"]["problems"])
    parts.append("collected %d test cases" % c["enough_tests"]["collected"])
    parts.append("reference run: %s" % ("all passed, twice" if c["passes_on_reference"]["pass"] else "failures"))
    k = c["catches_broken_versions"]
    parts.append("caught %d of %d broken versions" % (k["caught"], k["total"]))
    return "; ".join(parts) + "."


if __name__ == "__main__":
    src = Path(sys.argv[1]).read_text()
    print(json.dumps(grade(src), indent=2))
