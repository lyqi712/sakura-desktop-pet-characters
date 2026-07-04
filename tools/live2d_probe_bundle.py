from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

BASE = Path("D:/Sakura")
OUT = BASE / "plugins/live2d_renderer/probe_bundle_result.json"
HTML = BASE / "plugins/live2d_renderer/probe_bundle.html"
VENDOR = BASE / "plugins/live2d_renderer/vendor_v5"
MODEL = BASE / "data/live2d/chun/椿.model3.json"


def file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()

html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}}canvas{{display:block}}</style></head>
<body>
<canvas id="c" width="350" height="500"></canvas>
<script>
window.__live2dStatus = {{ steps: [], errors: [] }};
window.onerror = (m,s,l,c,e) => window.__live2dStatus.errors.push(String(m) + ' @' + l + ':' + c);
window.onunhandledrejection = e => window.__live2dStatus.errors.push('unhandledrejection: ' + String(e.reason && (e.reason.stack || e.reason.message || e.reason)));
</script>
<script src="{file_url(VENDOR / 'live2dcubismcore.min.js')}"></script>
<script src="{file_url(VENDOR / 'probe-bundle.js')}"></script>
<script>
window.__runLive2DProbe(document.getElementById('c'), {json.dumps(file_url(MODEL))});
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
        data = json.loads(value) if isinstance(value, str) and value else {"raw": value}
        if data.get("done") or data.get("errors") or attempt >= 80:
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
QTimer.singleShot(25000, lambda: finish({"timeout": True}))
app.exec()
