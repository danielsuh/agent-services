import os
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
for cand in (os.environ.get("CANVAS_PLUGIN_DIR"), str(Path.home() / ".hermes" / "plugins" / "agent-services"),
             str(here.parent)):
    if cand and (Path(cand) / "services.py").exists():
        sys.path.insert(0, cand)
        break
