"""Hermes plugin entry point. Registers the Homework 4 tools under the toolset agent_services."""
from pathlib import Path

try:
    from . import schemas, tools
except ImportError:
    import schemas, tools

TOOLSET = "agent_services"


def register(ctx):
    for schema in schemas.ALL:
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=tools.HANDLERS[schema["name"]])
    try:
        ctx.register_skill("agent-services", str(Path(__file__).parent / "skills" / "agent-services"))
    except Exception:
        # If skill registration is unavailable, copy skills/agent-services to ~/.hermes/skills/
        pass
