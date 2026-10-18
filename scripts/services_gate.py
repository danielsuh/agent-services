#!/usr/bin/env python3
"""Pre run gate for the Hermes cron job. No model, zero tokens.

Prints {"wakeAgent": false} or {"wakeAgent": true, "context": {...}}. Wakes the agent only when the
HW4 forum is RUNNING, the agent is not halted, write attempts are left this hour, and there is work:
the offer is not posted yet, someone sent a request, the hired provider replied, a verdict needs to
be posted, or there are service offers to consider. Exit code 1 means an error worth an alert.
"""
import json
import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))
import _path  # noqa: E402,F401
import core  # noqa: E402
import services  # noqa: E402


def main():
    try:
        result = services.Services(core.Forum(core.Config.from_env())).gate()
    except core.ConfigError as e:
        print("config error: %s" % e)
        return 1
    except core.CanvasError as e:
        print("canvas error (%s): %s" % (e.kind, e))
        return 1
    out = {"wakeAgent": bool(result["wake"])}
    if result["wake"]:
        out["context"] = {"reason": result["reason"]}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
