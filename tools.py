"""Tool handlers. Each returns a JSON string, never raises, and never returns the token."""
import json

try:
    from . import core, services
except ImportError:  # running from the repository root in tests
    import core
    import services


def _svc():
    return services.Services(core.Forum(core.Config.from_env()))


def _safe(fn):
    def wrapper(params, **kwargs):
        try:
            return json.dumps(fn(params or {}))
        except core.ConfigError as e:
            return json.dumps({"ok": False, "error": "config", "message": str(e)})
        except core.CanvasError as e:
            return json.dumps({"ok": False, "error": e.kind, "message": str(e)})
        except Exception as e:  # last resort, type only, no traceback that could carry the environment
            return json.dumps({"ok": False, "error": "internal", "message": type(e).__name__})
    return wrapper


@_safe
def check(p):
    return _svc().snapshot()


@_safe
def post_offer(p):
    return _svc().post_offer(p.get("body", ""))


@_safe
def send_request(p):
    return _svc().send_request(p.get("offer_entry_id", ""), p.get("reason", ""), p.get("intro", ""))


@_safe
def verify(p):
    return _svc().verify_delivery(p.get("entry_id", ""))


@_safe
def reply(p):
    return _svc().reply(p.get("parent_entry_id", ""), p.get("body", ""), p.get("purpose", ""), p.get("tip_amount"))


@_safe
def close(p):
    return _svc().close_request(p.get("status", ""), p.get("reason", ""))


@_safe
def no_reply(p):
    return _svc().mark_incoming_ignored(p.get("entry_id", ""), p.get("reason", ""))


@_safe
def cost(p):
    return _svc().cost_estimate(p.get("workload") or {})


@_safe
def skip(p):
    return _svc().forum.skip(p.get("reason", ""))


@_safe
def status(p):
    return _svc().status()


HANDLERS = {
    "services_check": check, "services_post_offer": post_offer, "services_send_request": send_request,
    "services_verify_delivery": verify, "services_reply": reply, "services_close_request": close,
    "services_mark_no_reply": no_reply, "cost_estimate": cost, "services_skip": skip, "services_status": status,
}
