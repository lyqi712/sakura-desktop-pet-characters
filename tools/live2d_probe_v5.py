from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

BASE = Path("D:/Sakura")
OUT = BASE / "plugins/live2d_renderer/probe_v5_result.json"
HTML = BASE / "plugins/live2d_renderer/probe_v5.html"
VENDOR = BASE / "plugins/live2d_renderer/vendor_v5"
MODEL = BASE / "data/live2d/chun/椿.model3.json"


def file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()

html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}}canvas{{display:block}}</style></head>
<body>
<script>
window.__live2dStatus = {{ steps: [], errors: [] }};
window.onerror = (m,s,l,c,e) => window.__live2dStatus.errors.push(String(m) + ' @' + l + ':' + c);
window.onunhandledrejection = e => window.__live2dStatus.errors.push('unhandledrejection: ' + String(e.reason && (e.reason.stack || e.reason.message || e.reason)));
function step(name, data) {{ window.__live2dStatus.steps.push({{ name, data: data || null }}); }}
</script>
<script src="{file_url(VENDOR / 'pixi8.min.js')}"></script>
<script src="{file_url(VENDOR / 'live2dcubismcore.min.js')}"></script>
<script src="{file_url(VENDOR / 'untitled-cubism.min.js')}"></script>
<script>
(async () => {{
  step('globals', {{
    hasPIXI: !!window.PIXI,
    pixiVersion: window.PIXI && window.PIXI.VERSION,
    hasLive2D: !!(window.PIXI && window.PIXI.live2d),
    keys: window.PIXI && window.PIXI.live2d ? Object.keys(window.PIXI.live2d).slice(0, 30) : [],
    hasModel: !!(window.PIXI && window.PIXI.live2d && window.PIXI.live2d.Live2DModel),
    hasPlugin: !!(window.PIXI && window.PIXI.live2d && window.PIXI.live2d.Live2DPlugin),
    hasCore: !!window.Live2DCubismCore,
  }});
  const {{ Application, extensions }} = PIXI;
  const {{ Live2DModel, Live2DPlugin, configureCubismSDK }} = PIXI.live2d;
  extensions.add(Live2DPlugin);
  if (configureCubismSDK) configureCubismSDK({{ memorySizeMB: 64 }});
  const app = new Application();
  await app.init({{ width: 350, height: 500, backgroundAlpha: 0, preference: 'webgl' }});
  document.body.appendChild(app.canvas);
  step('app-created', {{ w: app.screen.width, h: app.screen.height, renderer: app.renderer.name || app.renderer.type }});
  const model = await Live2DModel.from({json.dumps(file_url(MODEL))}, {{ textureOptions: {{ lod: false }} }});
  step('model-loaded', {{ width: model.width, height: model.height, internalWidth: model.internalModel && model.internalModel.originalWidth, internalHeight: model.internalModel && model.internalModel.originalHeight }});
  model.anchor.set(0.5, 1.0);
  model.position.set(175, 500);
  const mw = model.internalModel && model.internalModel.originalWidth || model.width;
  const mh = model.internalModel && model.internalModel.originalHeight || model.height;
  model.scale.set(Math.min(350 / mw, 500 / mh) * 0.95);
  app.stage.addChild(model);
  await new Promise(resolve => setTimeout(resolve, 1000));
  app.renderer.render(app.stage);
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
</body></html>"""
HTML.write_text(html, encoding="utf-8")

app = QApplication(sys.argv)
view = QWebEngineView()
view.resize(350, 500)
view.load(QUrl.fromLocalFile(str(HTML)))


def finish(result: dict) -> None:
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    app.quit()


def check(attempt: int = 0) -> None:
    def got(value):
        try:
            data = json.loads(value) if isinstance(value, str) and value else {"raw": value}
        except Exception as exc:
            data = {"parse_error": str(exc), "raw": value}
        if data.get("done") or data.get("errors") or attempt >= 60:
            finish({"attempt": attempt, "status": data})
        else:
            QTimer.singleShot(250, lambda: check(attempt + 1))
    view.page().runJavaScript("JSON.stringify(window.__live2dStatus || {missing:true})", got)


def on_load(ok: bool) -> None:
    if not ok:
        finish({"load_ok": False})
    else:
        QTimer.singleShot(500, check)

view.loadFinished.connect(on_load)
QTimer.singleShot(20000, lambda: finish({"timeout": True}))
app.exec()
