#!/usr/bin/env python3
"""Human only controls. The agent has no tool that can do any of this.

  python3 services_admin.py status          counters, halt state, offer and requests
  python3 services_admin.py tail [N]        last N log lines (default 20)
  python3 services_admin.py discovery       offers seen, choices and reasons (for the write up)
  python3 services_admin.py reset-halt      clear a halt after fixing the cause
  python3 services_admin.py export DIR      copy logs, reports and final output to DIR for submission
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: E402,F401
import core  # noqa: E402
import services  # noqa: E402


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    home = os.environ.get("CANVAS_AGENT_HOME") or str(Path.home() / ".hermes" / "agent_services")
    state = core.State(home)
    if cmd == "tail":
        n = int(argv[2]) if len(argv) > 2 else 20
        print("\n".join(state.log_path.read_text().splitlines()[-n:] if state.log_path.exists() else []))
        return 0
    cfg = core.Config("x", "1", "1", base_url="http://127.0.0.1", state_dir=home)  # no network used here
    svc = services.Services(core.Forum(cfg, state=state))
    if cmd == "discovery":
        print(json.dumps({"offers_seen": svc.d["offers_seen"], "choices": svc.d["discovery_log"],
                          "skips": [json.loads(l) for l in state.log_path.read_text().splitlines()
                                    if '"no_post"' in l][-20:] if state.log_path.exists() else []}, indent=2))
        return 0
    if cmd == "export":
        dest = Path(argv[2]).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        if state.log_path.exists():
            shutil.copy(state.log_path, dest / "cycles.jsonl")
        if svc.out_dir.exists():
            shutil.copytree(svc.out_dir, dest / "hw4", dirs_exist_ok=True)
        public = {k: v for k, v in state.data.items() if k not in ("intents",)}
        (dest / "state_summary.json").write_text(json.dumps(public, indent=2))
        print("exported to %s (no token is stored in any of these files)" % dest)
        return 0
    if cmd == "reset-halt":
        svc.forum.reset_halt()
        print("halt cleared")
    print(json.dumps(svc.status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
