"""Runs inside an isolated subprocess: python3 -I harness.py <workdir> <marker>

The work directory holds cost_estimator.py (reference or a mutant) and peer_tests.py.
Collects unittest TestCase methods and top level test_* functions, runs each one, and
prints a single JSON result line prefixed with the marker. An audit hook blocks file
writes, network, subprocesses and native code for the whole run (defense in depth on
top of the static check done before this process starts).
"""
import io
import json
import os
import sys
import time
import traceback
import types
import unittest

WORKDIR, MARKER = sys.argv[1], sys.argv[2]
REAL_STDOUT = sys.stdout

BLOCKED_PREFIXES = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
                    "os.fork", "os.kill", "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod",
                    "os.symlink", "os.link", "os.truncate", "shutil.", "ctypes.", "urllib.", "http.",
                    "ftplib.", "smtplib.", "webbrowser.", "pty.", "sys.settrace", "sys.setprofile",
                    "import_pickle", "marshal.", "sqlite3.", "builtins.input", "glob.", "os.chdir", "os.putenv", "os.unsetenv")
_armed = [False]
_ROOTS = tuple(os.path.realpath(r) for r in (WORKDIR, sys.base_prefix, sys.prefix, sys.base_exec_prefix))


def _inside(path):
    p = os.path.realpath(os.fsdecode(path))
    return any(p == r or p.startswith(r + os.sep) for r in _ROOTS)


def _audit(event, args):
    if not _armed[0]:
        return
    if event in ("os.listdir", "os.scandir"):
        path = args[0] if args else "."
        if isinstance(path, (str, bytes)) and not _inside(path):
            raise PermissionError("listing outside the sandbox is blocked")
        return
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            raise PermissionError("file writes are blocked in the test sandbox")
        write_bits = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
        if isinstance(flags, int) and flags & write_bits:
            raise PermissionError("file writes are blocked in the test sandbox")
        if isinstance(path, (str, bytes)) and not _inside(path):
            raise PermissionError("reading outside the sandbox is blocked")
        return
    if event == "import":
        return
    if event.startswith(BLOCKED_PREFIXES):
        raise PermissionError("blocked in the test sandbox: " + event)


def _pytest_shim():
    """Just enough of pytest for plain assert style tests: raises and approx."""
    mod = types.ModuleType("pytest")

    class _Raises:
        def __init__(self, exc, match=None):
            self.exc, self.match, self.value = exc, match, None

        def __enter__(self):
            return self

        def __exit__(self, et, ev, tb):
            if et is None:
                raise AssertionError("DID NOT RAISE %s" % self.exc)
            if not issubclass(et, self.exc):
                return False
            self.value = ev
            if self.match:
                import re
                if not re.search(self.match, str(ev)):
                    raise AssertionError("exception message did not match %r" % self.match)
            return True

    class _Approx:
        def __init__(self, expected, rel=1e-6, abs=1e-12):
            self.expected, self.rel, self.abs = expected, rel, abs

        def __eq__(self, other):
            tol = max(self.rel * abs(self.expected), self.abs)
            return abs(other - self.expected) <= tol

        def __repr__(self):
            return "approx(%r)" % self.expected

    mod.raises = lambda exc, match=None: _Raises(exc, match)
    mod.approx = lambda expected, rel=1e-6, abs=1e-12: _Approx(expected, rel, abs)
    mod.mark = types.SimpleNamespace(parametrize=lambda *a, **k: (lambda f: f))
    return mod


def collect(module):
    tests = []
    loader = unittest.TestLoader()
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
            for case in loader.loadTestsFromTestCase(obj):
                tests.append((case.id().split(".", 1)[-1], case))
        elif name.startswith("test") and isinstance(obj, types.FunctionType):
            tests.append((name, obj))
    return tests


def run_one(test):
    if isinstance(test, unittest.TestCase):
        result = unittest.TestResult()
        test.run(result)
        problems = result.failures + result.errors
        if problems:
            return "fail", problems[0][1].strip().splitlines()[-1][:300]
        if result.skipped:
            return "skip", ""
        return "pass", ""
    try:
        test()
        return "pass", ""
    except AssertionError as e:
        return "fail", ("AssertionError: %s" % e)[:300]
    except Exception as e:
        return "error", ("%s: %s" % (type(e).__name__, e))[:300]


def main():
    sys.path.insert(0, WORKDIR)
    sys.modules["pytest"] = _pytest_shim()
    sys.dont_write_bytecode = True
    out = {"collected": 0, "results": [], "import_error": None}
    captured = io.StringIO()
    sys.stdout = captured
    sys.addaudithook(_audit)
    _armed[0] = True
    start = time.time()
    try:
        import peer_tests  # noqa: F401
        tests = collect(peer_tests)
        out["collected"] = len(tests)
        for name, t in tests[:300]:
            status, detail = run_one(t)
            out["results"].append({"name": name, "status": status, "detail": detail})
    except BaseException as e:  # import failure or anything the tests raise at module level
        out["import_error"] = ("%s: %s" % (type(e).__name__, e))[:300]
        out["trace_tail"] = traceback.format_exc().strip().splitlines()[-1][:300]
    _armed[0] = False
    sys.stdout = REAL_STDOUT
    out["seconds"] = round(time.time() - start, 3)
    REAL_STDOUT.write("\n" + MARKER + json.dumps(out) + "\n")
    REAL_STDOUT.flush()


main()
