from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

BASE = Path("D:/Sakura")
OUT = BASE / "plugins/live2d_renderer/fetch_probe_result.json"
HTML = BASE / "plugins/live2d_renderer/fetch_probe.html"
MODEL = BASE / "data/live2d/chun/椿.model3.json"


def file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()

html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<script>
window.__probe = {{ steps: [], errors: [] }};
function step(name, data) {{ window.__probe.steps.push({{ name, data }}); }}
window.onerror = (m,s,l,c,e) => window.__probe.errors.push(String(m) + ' @' + l + ':' + c);
window.onunhandledrejection = e => window.__probe.errors.push('unhandledrejection: ' + String(e.reason && (e.reason.stack || e.reason.message || e.reason)));
(async () => {{
  const modelUrl = {json.dumps(file_url(MODEL))};
  step('model-url', modelUrl);
  const mr = await fetch(modelUrl);
  step('model-response', {{ ok: mr.ok, status: mr.status, url: mr.url }});
  const model = await mr.json();
  step('model-json', {{ version: model.Version, moc: model.FileReferences && model.FileReferences.Moc, textures: model.FileReferences && model.FileReferences.Textures }});
  const mocUrl = new URL(model.FileReferences.Moc, modelUrl).href;
  step('moc-url', mocUrl);
  const rr = await fetch(mocUrl);
  step('moc-response', {{ ok: rr.ok, status: rr.status, url: rr.url, contentType: rr.headers.get('content-type') }});
  const buf = await rr.arrayBuffer();
  const bytes = new Uint8Array(buf.slice(0, 16));
  step('moc-bytes', {{ byteLength: buf.byteLength, head: Array.from(bytes), ascii: Array.from(bytes).map(x => x>=32&&x<127 ? String.fromCharCode(x) : '.').join('') }});
  window.__probe.done = true;
}})();
</script>
</body></html>
"""
HTML.write_text(html, encoding="utf-8")

app = QApplication(sys.argv)
view = QWebEngineView()
view.resize(100, 100)
view.load(QUrl.fromLocalFile(str(HTML)))


def finish(result: dict) -> None:
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    app.quit()


def check(attempt: int = 0) -> None:
    def got(value):
        data = json.loads(value) if isinstance(value, str) and value else {"raw": value}
        if data.get("done") or data.get("errors") or attempt >= 40:
            finish({"attempt": attempt, "status": data})
        else:
            QTimer.singleShot(250, lambda: check(attempt + 1))
    view.page().runJavaScript("JSON.stringify(window.__probe || {missing:true})", got)


def on_load(ok: bool) -> None:
    if not ok:
        finish({"load_ok": False})
    else:
        QTimer.singleShot(500, check)

view.loadFinished.connect(on_load)
QTimer.singleShot(15000, lambda: finish({"timeout": True}))
app.exec()
