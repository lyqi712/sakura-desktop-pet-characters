from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

BASE = Path("D:/Sakura")
OUT = BASE / "plugins/live2d_renderer/probe_result.json"
HTML = BASE / "plugins/live2d_renderer/probe_live2d.html"
VENDOR = BASE / "plugins/live2d_renderer/vendor"
MODEL = BASE / "data/live2d/chun/椿.model3.json"


def file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{ margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }}
canvas {{ display: block; width: 100%; height: 100%; }}
</style>
</head>
<body>
<canvas id="c"></canvas>
<script>
window.__live2dStatus = {{ steps: [], errors: [] }};
window.onerror = function(message, source, lineno, colno, error) {{
  window.__live2dStatus.errors.push(String(message) + ' @' + lineno + ':' + colno);
}};
window.onunhandledrejection = function(event) {{
  window.__live2dStatus.errors.push('unhandledrejection: ' + String(event.reason && (event.reason.stack || event.reason.message || event.reason)));
}};
function step(name, data) {{ window.__live2dStatus.steps.push({{ name, data: data || null }}); }}
</script>
<script src="{file_url(VENDOR / 'pixi.min.js')}"></script>
<script src="{file_url(VENDOR / 'pixi-unsafe-eval.min.js')}"></script>
<script src="{file_url(VENDOR / 'live2dcubismcore.min.js')}"></script>
<script src="{file_url(VENDOR / 'pixi-live2d-display.min.js')}"></script>
<script>
(async () => {{
  step('globals', {{
    hasPIXI: !!window.PIXI,
    pixiVersion: window.PIXI && window.PIXI.VERSION,
    hasPixiLive2D: !!(window.PIXI && window.PIXI.live2d),
    hasLive2DModel: !!(window.PIXI && window.PIXI.live2d && window.PIXI.live2d.Live2DModel),
    hasCore: !!window.Live2DCubismCore,
  }});
  const app = new PIXI.Application({{
    view: document.getElementById('c'),
    width: 350,
    height: 500,
    transparent: true,
    backgroundAlpha: 0,
  }});
  step('app-created', {{ renderer: app.renderer && app.renderer.type }});
  const model = await PIXI.live2d.Live2DModel.from({json.dumps(file_url(MODEL))});
  step('model-loaded', {{
    width: model.internalModel && model.internalModel.originalWidth,
    height: model.internalModel && model.internalModel.originalHeight,
  }});
  app.stage.addChild(model);
  model.anchor.set(0.5, 1.0);
  model.x = 175;
  model.y = 500;
  const s = Math.min(350 / model.internalModel.originalWidth, 500 / model.internalModel.originalHeight) * 0.95;
  model.scale.set(s);
  await new Promise(resolve => setTimeout(resolve, 800));
  const gl = app.renderer.gl;
  const pixels = new Uint8Array(350 * 500 * 4);
  gl.readPixels(0, 0, 350, 500, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  let nonZeroAlpha = 0;
  for (let i = 3; i < pixels.length; i += 4) {{ if (pixels[i] !== 0) nonZeroAlpha++; }}
  window.__live2dStatus.nonZeroAlpha = nonZeroAlpha;
  window.__live2dStatus.done = true;
  step('pixel-check', {{ nonZeroAlpha }});
}})();
</script>
</body>
</html>
"""
HTML.write_text(html, encoding="utf-8")

app = QApplication(sys.argv)
view = QWebEngineView()
view.resize(350, 500)
view.load(QUrl.fromLocalFile(str(HTML)))


def finish(result: dict) -> None:
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    app.quit()


def check_status(attempt: int = 0) -> None:
    js = "JSON.stringify(window.__live2dStatus || {missing:true})"

    def got(value):
        try:
            data = json.loads(value) if isinstance(value, str) and value else {"raw": value}
        except Exception as exc:
            data = {"parse_error": str(exc), "raw": value}
        if data.get("done") or attempt >= 40:
            finish({"attempt": attempt, "status": data})
        else:
            QTimer.singleShot(250, lambda: check_status(attempt + 1))

    view.page().runJavaScript(js, got)


def on_load(ok: bool) -> None:
    if not ok:
        finish({"load_ok": False})
        return
    QTimer.singleShot(500, check_status)


view.loadFinished.connect(on_load)
QTimer.singleShot(15000, lambda: finish({"timeout": True}))
app.exec()
