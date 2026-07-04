from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QEvent, QPoint, QTimer, Qt, QUrl, Signal, Slot

from app.core.debug_log import debug_log
from app.plugins.base import PluginBase, PluginContext
from app.plugins.capabilities import PluginCapabilityRegistry
from app.plugins.models import RendererContribution, RendererCreateContext
from app.renderers.base import CharacterRenderer


_PLUGIN_DIR = Path(__file__).resolve().parent


class _JavaScriptRunner(QObject):
    """线程安全的 JS 投递器。

    事件来自 ChatWorker / TTS 等后台线程，必须经 QueuedConnection 回到
    QWebEngineView 所在线程执行 runJavaScript，否则会触发 Chromium native assert。
    页面加载完成（loadFinished）前积压脚本，就绪后批量执行。
    """

    _run_requested = Signal(str, object)

    def __init__(self, view: Any) -> None:
        super().__init__(view)
        self._view = view
        self._page_ready = False
        self._pending: list[tuple[str, Any | None]] = []
        self._run_requested.connect(self._do_run, Qt.ConnectionType.QueuedConnection)

    def set_page_ready(self) -> None:
        """loadFinished 触发后调用，刷新积压队列。"""
        self._page_ready = True
        pending = self._pending[:]
        self._pending.clear()
        for script, callback in pending:
            self._run_requested.emit(script, callback)

    def submit(self, script: str) -> None:
        if not self._page_ready:
            self._pending.append((script, None))
            return
        self._run_requested.emit(script, None)

    def submit_with_callback(self, script: str, callback: Any) -> None:
        if not self._page_ready:
            self._pending.append((script, callback))
            return
        self._run_requested.emit(script, callback)

    @Slot(str, object)
    def _do_run(self, script: str, callback: Any) -> None:
        view = self._view
        if view is None:
            return
        try:
            if callback is None:
                view.page().runJavaScript(script)
            else:
                view.page().runJavaScript(script, callback)
        except RuntimeError:
            pass


class MMDRenderer(CharacterRenderer):
    renderer_name = "mmd"
    uses_owner_coordinates = False
    supports_drag_snapshot = True

    def __init__(self, ctx: RendererCreateContext) -> None:
        self._ctx = ctx
        self._view: Any | None = None
        self._js_runner: _JavaScriptRunner | None = None
        self._initialized = False
        self._last_geometry: tuple[int, int, int, int, int] | None = None
        self._last_stack_state: tuple[int | None, bool | None] | None = None
        self._last_clip_keep: int | None | str = "__unset__"
        self._config: dict[str, Any] = {}

    @property
    def replaces_default_portrait(self) -> bool:
        return self._initialized and self._view is not None

    def is_available(self) -> bool:
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            return True
        except ImportError:
            return False

    def initialize(self, app_context: dict[str, Any] | None = None) -> None:
        _ = app_context
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView

            parent = self._ctx.owner_window

            class DraggableMMDView(QWebEngineView):
                def __init__(self, parent_widget: Any, owner_window: Any) -> None:
                    super().__init__(parent_widget)
                    self._owner_window = owner_window
                    self._event_filters_installed = False
                    self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
                    self.setMouseTracking(True)

                def install_mouse_forwarders(self) -> None:
                    if self._event_filters_installed:
                        return
                    self.installEventFilter(self)
                    for child in self.findChildren(object):
                        install = getattr(child, "installEventFilter", None)
                        if callable(install):
                            install(self)
                    self._event_filters_installed = True

                def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802
                    event_type = event.type()
                    if event_type == QEvent.Type.ContextMenu:
                        return self._open_owner_menu(event)
                    if event_type == QEvent.Type.MouseButtonPress:
                        return self._forward_mouse_press(event, watched)
                    if event_type == QEvent.Type.MouseMove:
                        return self._forward_mouse_move(event)
                    if event_type == QEvent.Type.MouseButtonRelease:
                        return self._forward_mouse_release(event)
                    return super().eventFilter(watched, event)

                def contextMenuEvent(self, event: Any) -> None:  # noqa: N802
                    if self._open_owner_menu(event):
                        return
                    super().contextMenuEvent(event)

                def mousePressEvent(self, event: Any) -> None:  # noqa: N802
                    if self._forward_mouse_press(event, self):
                        return
                    super().mousePressEvent(event)

                def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
                    if self._forward_mouse_move(event):
                        return
                    super().mouseMoveEvent(event)

                def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
                    if self._forward_mouse_release(event):
                        return
                    super().mouseReleaseEvent(event)

                def _open_owner_menu(self, event: Any) -> bool:
                    menu_handler = getattr(self._owner_window, "_show_context_menu", None)
                    if not callable(menu_handler):
                        return False
                    menu_handler(QPoint(0, 0))
                    event.accept()
                    return True

                def _forward_mouse_press(self, event: Any, source_widget: Any) -> bool:
                    if event.button() == Qt.MouseButton.RightButton:
                        return self._open_owner_menu(event)
                    handler = getattr(self._owner_window, "_handle_mouse_press", None)
                    return bool(callable(handler) and handler(event, source_widget))

                def _forward_mouse_move(self, event: Any) -> bool:
                    handler = getattr(self._owner_window, "_handle_mouse_move", None)
                    return bool(callable(handler) and handler(event))

                def _forward_mouse_release(self, event: Any) -> bool:
                    handler = getattr(self._owner_window, "_handle_mouse_release", None)
                    return bool(callable(handler) and handler(event))

            self._view = DraggableMMDView(parent, parent)
            self._js_runner = _JavaScriptRunner(self._view)
            self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._view.page().setBackgroundColor(Qt.GlobalColor.transparent)
            self._view.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
            )
            html_path = _PLUGIN_DIR / "mmd_view.html"
            html_path.write_text(
                _build_html(_normalize_renderer_config(self._ctx.renderer_config, package_dir=self._ctx.package_dir)),
                encoding="utf-8",
            )
            # 页面加载完成后才允许执行 JS，防止 Chromium 尚未就绪时调用
            # runJavaScript 触发 native assert（0x80000003 fatal exception）。
            # 信号必须先于 load() 连接，避免本地 file:// 页面过快完成导致错过 loadFinished。
            js_runner = self._js_runner
            self._view.loadFinished.connect(lambda ok: js_runner.set_page_ready() if ok else None)
            self._view.load(QUrl.fromLocalFile(str(html_path)))
            self._view.resize(420, 570)
            self._view.show()
            self._view.install_mouse_forwarders()
            self._config = _normalize_renderer_config(self._ctx.renderer_config, package_dir=self._ctx.package_dir)
            self._initialized = True
            QTimer.singleShot(500, lambda: self.load_character(self._ctx.renderer_config))
        except Exception:
            debug_log("MMDRenderer", "初始化失败", {"error": traceback.format_exc()})
            self.close()
            raise

    def load_character(self, character_config: dict[str, Any]) -> None:
        package_dir = getattr(self._ctx, "package_dir", Path("."))
        self._config = _normalize_renderer_config(character_config or self._ctx.renderer_config, package_dir=package_dir)
        self._run_js(f"loadCharacter({json.dumps(self._config, ensure_ascii=False)})")

    def close(self) -> None:
        self._js_runner = None
        if self._view is not None:
            self._view.close()
            self._view = None
        self._initialized = False

    def capture_snapshot(self) -> Any | None:
        if self._view is None:
            return None
        try:
            pixmap = self._view.grab()
            is_null = getattr(pixmap, "isNull", None)
            if callable(is_null) and is_null():
                return None
            return pixmap
        except Exception:
            debug_log("MMDRenderer", "快照抓取失败", {"error": traceback.format_exc()})
            return None

    def show(self) -> None:
        if self._view is not None:
            self._view.show()
            self._raise_owner_foreground_controls()

    def hide(self) -> None:
        if self._view is not None:
            self._view.hide()

    def set_geometry(self, x: int, y: int, width: int, height: int, layout_height: int | None = None) -> None:
        if self._view is None:
            return
        w = max(1, int(width))
        h = max(1, int(height))
        lh = int(layout_height) if layout_height and int(layout_height) > 0 else h
        geometry = (int(x), int(y), w, h, lh)
        if _geometry_close(getattr(self, "_last_geometry", None), geometry):
            return
        self._last_geometry = geometry
        set_geometry = getattr(self._view, "setGeometry", None)
        if callable(set_geometry):
            set_geometry(int(x), int(y), w, h)
        self._run_js(f"resizeMmd({w}, {h}, {lh})")

    def set_position(self, x: int, y: int) -> None:
        if self._view is not None:
            self._view.move(int(x), int(y))

    def stack_below(self, owner_window: Any, *, topmost: bool | None = None) -> None:
        if self._view is None:
            return
        state = (id(owner_window) if owner_window is not None else None, topmost)
        if getattr(self, "_last_stack_state", None) == state:
            return
        self._last_stack_state = state
        try:
            lower_overlay = getattr(self._view, "lower", None)
            if callable(lower_overlay):
                lower_overlay()
            if owner_window is not None:
                raise_owner = getattr(owner_window, "raise_", None)
                if callable(raise_owner):
                    raise_owner()
        except Exception:
            debug_log("MMDRenderer", "层级调整失败", {"error": traceback.format_exc()})

    def set_clip_mask(self, keep_top_height: int | None) -> None:
        if self._view is None:
            return
        try:
            from PySide6.QtGui import QRegion

            last = getattr(self, "_last_clip_keep", "__unset__")
            if keep_top_height is None or int(keep_top_height) <= 0:
                if last is not None:
                    self._view.clearMask()
                    self._last_clip_keep = None
                return
            keep = int(keep_top_height)
            width = max(1, self._view.width())
            keep = min(keep, max(1, self._view.height()))
            if last == keep:
                return
            self._view.setMask(QRegion(0, 0, width, keep))
            self._last_clip_keep = keep
        except Exception:
            debug_log("MMDRenderer", "遮罩调整失败", {"error": traceback.format_exc()})

    def _raise_owner_foreground_controls(self) -> None:
        owner = getattr(self._ctx, "owner_window", None)
        raise_controls = getattr(owner, "_raise_foreground_controls", None)
        if not callable(raise_controls):
            return
        try:
            raise_controls()
        except Exception:
            debug_log("MMDRenderer", "宿主前景控件抬升失败", {"error": traceback.format_exc()})

    def set_lip_sync(self, value: float) -> None:
        self._run_js(f"setLipSync({_clamp(value)})")

    def look_at(self, x: float, y: float) -> None:
        self._run_js(f"lookAt({_clamp_signed(x)}, {_clamp_signed(y)})")

    def set_expression(self, expression_name: str, weight: float = 1.0) -> None:
        self._run_js(f"setExpression({json.dumps(expression_name, ensure_ascii=False)}, {_clamp(weight)})")

    def play_motion(self, motion_name: str, loop: bool = False) -> None:
        self._run_js(f"playMotion({json.dumps(motion_name, ensure_ascii=False)}, {str(bool(loop)).lower()})")

    def stop_motion(self, motion_name: str | None = None) -> None:
        self._run_js(f"stopMotion({json.dumps(motion_name, ensure_ascii=False)})")

    def handle_event(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        _ = payload
        if event_name in {"tts.started", "tts_started"}:
            self.play_motion("talk", loop=True)
        elif event_name in {"tts.finished", "tts_finished", "tts.failed"}:
            self.set_lip_sync(0.0)
            self.stop_motion("talk")
        elif event_name in {"llm.request.started", "llm_request_started"}:
            self.play_motion("thinking", loop=True)
        elif event_name in {"llm.request.finished", "llm.request.failed", "llm_request_finished"}:
            self.stop_motion("thinking")
        elif event_name in {"pet.clicked", "pet_clicked"}:
            self.play_motion("tap", loop=False)

    def _run_js(self, script: str) -> None:
        if self._js_runner is not None:
            self._js_runner.submit(script)


def _normalize_renderer_config(raw_config: dict[str, Any], *, package_dir: Path | None = None) -> dict[str, Any]:
    package = Path(package_dir) if package_dir is not None else Path(".")
    cfg = dict(raw_config or {})
    model_value = str(cfg.get("model") or "").strip()
    if _looks_like_url(model_value):
        model = model_value
        model_url = str(cfg.get("model_url") or model_value)
    elif model_value:
        model_path = Path(model_value)
        if not model_path.is_absolute():
            model_path = (package / model_path).resolve()
        model = str(model_path)
        model_url = str(cfg.get("model_url") or QUrl.fromLocalFile(model).toString())
    else:
        model = ""
        model_url = str(cfg.get("model_url") or "")
    morphs = cfg.get("morphs") if isinstance(cfg.get("morphs"), dict) else {}
    bones = cfg.get("bones") if isinstance(cfg.get("bones"), dict) else {}
    liveness = cfg.get("liveness") if isinstance(cfg.get("liveness"), dict) else {}
    expressions = cfg.get("expressions") if isinstance(cfg.get("expressions"), dict) else {}
    material_overrides = cfg.get("material_overrides") if isinstance(cfg.get("material_overrides"), dict) else {}
    material_name_overrides = cfg.get("material_name_overrides") if isinstance(cfg.get("material_name_overrides"), dict) else {}
    material_preset = str(cfg.get("material_preset") or "game_toon").strip().lower() or "game_toon"
    camera = cfg.get("camera") if isinstance(cfg.get("camera"), dict) else {}
    camera = {
        **{"position": [0, 11, 34], "target": [0, 10, 0], "fov": 45},
        **camera,
    }
    camera.setdefault("frame", "portrait")
    camera.setdefault("coverage", 0.76)
    camera.setdefault("target_ratio", 0.66)
    camera.setdefault("offset_x", 0)
    camera.setdefault("offset_y", 0.0)
    return {
        "engine": str(cfg.get("engine") or "three").strip().lower() or "three",
        "model": str(model),
        "model_url": model_url,
        "material_preset": material_preset,
        "morphs": {
            "mouth": _normalize_morph_selector_list(morphs.get("mouth"), ["あ", "い", "う", "え", "お"]),
            "blink": _normalize_morph_selector(
                morphs.get("blink"),
                ["まばたき", "E_Close", "blink", "Blink"],
            ),
        },
        "liveness": dict(liveness),
        "expressions": dict(expressions),
        "material_overrides": dict(material_overrides),
        "material_name_overrides": dict(material_name_overrides),
        "bones": {
            "chest": str(bones.get("chest", "上半身2")),
            "neck": str(bones.get("neck", "首")),
            "head": str(bones.get("head", "頭")),
            "leftShoulder": str(bones.get("leftShoulder", "左肩")),
            "rightShoulder": str(bones.get("rightShoulder", "右肩")),
            "leftArm": str(bones.get("leftArm", "左腕")),
            "rightArm": str(bones.get("rightArm", "右腕")),
            "leftElbow": str(bones.get("leftElbow", "左ひじ")),
            "rightElbow": str(bones.get("rightElbow", "右ひじ")),
        },
        "camera": camera,
        "model_position": cfg.get("model_position", [0, -8, 0]),
        "model_scale": float(cfg.get("model_scale", 1.0)),
        "mouth_gain": float(cfg.get("mouth_gain", 1.0)),
        "head_pitch_neutral": _clamp_range(cfg.get("head_pitch_neutral", 0.04), -0.25, 0.25, default=0.04),
        "pixel_ratio_max": _clamp_range(cfg.get("pixel_ratio_max", 1.25), 1.0, 2.0, default=1.25),
        "physics_enabled": _parse_bool(cfg.get("physics_enabled"), True),
        "physics_warmup_frames": int(_clamp_range(cfg.get("physics_warmup_frames", 8), 0, 60, default=8)),
        "physics_max_step_num": int(_clamp_range(cfg.get("physics_max_step_num", 1), 1, 3, default=1)),
    }


def _looks_like_url(value: str) -> bool:
    return value.lower().startswith(("file://", "http://", "https://"))


def _normalize_morph_selector(value: Any, default: Any) -> int | str | list[int | str]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        items = [_normalize_morph_selector_item(item) for item in value]
        normalized = [item for item in items if item is not None]
        return normalized or default
    item = _normalize_morph_selector_item(value)
    return item if item is not None else default


def _normalize_morph_selector_list(value: Any, default: list[int | str]) -> list[int | str]:
    normalized = _normalize_morph_selector(value, default)
    if isinstance(normalized, list):
        return normalized
    return [normalized]


def _normalize_morph_selector_item(value: Any) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _clamp_range(value: Any, minimum: float, maximum: float, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _build_html(config: dict[str, Any], *, plugin_dir: Path | None = None) -> str:
    plugin_path = Path(plugin_dir) if plugin_dir is not None else _PLUGIN_DIR
    cfg = _normalize_renderer_config(config)
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    core_url = QUrl.fromLocalFile(str(plugin_path / "web" / "mmd_core")).toString()
    runtime = (plugin_path / "web" / "mmd_runtime.js").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body {{ margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }}
    canvas {{ display: block; width: 100%; height: 100%; background: transparent; }}
  </style>
  <script>window.__SAKURA_MMD_CORE_URL = {json.dumps(core_url)};</script>
  <script src="{core_url}/three.min.js"></script>
  <script src="{core_url}/mmdparser.min.js"></script>
  <script src="{core_url}/ammo.js"></script>
  <script src="{core_url}/TGALoader.js"></script>
  <script src="{core_url}/MMDLoader.js"></script>
  <script src="{core_url}/CCDIKSolver.js"></script>
  <script src="{core_url}/MMDPhysics.js"></script>
  <script src="{core_url}/MMDAnimationHelper.js"></script>
  <script src="{core_url}/OutlineEffect.js"></script>
  <script src="{core_url}/OrbitControls.js"></script>
</head>
<body>
  <script>window.__SAKURA_MMD_INITIAL_CONFIG = {cfg_json};</script>
  <script>
{runtime}
  </script>
</body>
</html>
"""


def _geometry_close(
    old: tuple[int, int, int, int, int] | None,
    new: tuple[int, int, int, int, int],
) -> bool:
    if old is None:
        return False
    return all(abs(a - b) <= 1 for a, b in zip(old, new))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp_signed(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


class MMDRendererPlugin(PluginBase):
    plugin_id = "mmd_renderer"
    plugin_version = "1.0.0"

    def initialize(self, register: PluginCapabilityRegistry, context: PluginContext) -> None:
        _ = context
        register.register_renderer(
            RendererContribution(
                renderer_type="mmd",
                display_name="MMD",
                create=lambda ctx: MMDRenderer(ctx),
                plugin_id=self.plugin_id,
                priority=60,
            )
        )
