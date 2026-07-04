from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, "D:/Sakura")

from app.plugins.models import RendererCreateContext
from plugins.live2d_renderer.plugin import Live2DRenderer

BASE = Path("D:/Sakura")
OUT = BASE / "plugins/live2d_renderer/plugin_init_probe_result.json"

app = QApplication(sys.argv)
character_data = json.loads((BASE / "characters/chun/character.json").read_text(encoding="utf-8"))
ctx = RendererCreateContext(
    character_id="chun",
    character_name="椿",
    package_dir=BASE / "characters/chun",
    renderer_config=character_data.get("renderer", {}),
    owner_window=None,
    event_bus=None,
)
renderer = Live2DRenderer(ctx)
result = {"is_available": renderer.is_available()}
try:
    renderer.initialize({"character_id": "chun"})
    result["initialized"] = bool(getattr(renderer, "_initialized", False))
    result["replaces_default_portrait"] = bool(renderer.replaces_default_portrait)
except Exception as exc:
    result["error"] = str(exc)
    result["error_type"] = type(exc).__name__
finally:
    renderer.close()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    app.quit()
