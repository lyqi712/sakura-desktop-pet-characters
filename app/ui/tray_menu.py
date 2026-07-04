from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QWidget


def build_pet_tray_menu(
    parent: QWidget,
    *,
    chinese_subtitles_checked: bool,
    free_access_checked: bool,
    always_on_top_checked: bool,
    on_hide: Callable[[], None],
    on_show: Callable[[], None],
    on_toggle_chinese_subtitles: Callable[[bool], None],
    on_toggle_free_access: Callable[[bool], None],
    on_toggle_always_on_top: Callable[[bool], None],
    on_show_history: Callable[[], None],
    on_show_runtime_log: Callable[[], None],
    on_show_settings: Callable[[], None],
    live2d_mode: str | None = None,
    on_set_live2d_mode: Callable[[str], None] | None = None,
    live2d_scale: float | None = None,
    on_set_live2d_scale: Callable[[float], None] | None = None,
    mmd_variants: dict[str, str] | None = None,
    mmd_active_variant: str | None = None,
    on_set_mmd_variant: Callable[[str], None] | None = None,
    window_visible: bool = True,
    interactions_enabled: bool = True,
    settings_enabled: bool | None = None,
) -> QMenu:
    """构建桌宠托盘和右键菜单。"""

    menu = QMenu(parent)
    # 让 QSS 大圆角的四角透明生效：原生 QMenu 在 Win11 的圆角不受 QSS 可靠控制，
    # 必须设无边框 + 半透明背景（代价：失去系统原生阴影，由 QSS 边框/底色补偿观感）。
    menu.setWindowFlags(
        menu.windowFlags()
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.NoDropShadowWindowHint
    )
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    visibility_action = QAction("隐藏至托盘" if window_visible else "显示桌宠", parent)
    visibility_action.triggered.connect(on_hide if window_visible else on_show)
    menu.addAction(visibility_action)

    menu.addSeparator()

    subtitle_action = QAction("显示中文字幕", parent)
    subtitle_action.setCheckable(True)
    subtitle_action.setChecked(chinese_subtitles_checked)
    subtitle_action.setEnabled(interactions_enabled)
    subtitle_action.triggered.connect(on_toggle_chinese_subtitles)
    menu.addAction(subtitle_action)

    free_access_action = QAction("完整访问权限", parent)
    free_access_action.setCheckable(True)
    free_access_action.setChecked(free_access_checked)
    free_access_action.setEnabled(interactions_enabled)
    free_access_action.triggered.connect(on_toggle_free_access)
    menu.addAction(free_access_action)

    always_on_top_action = QAction("保持置顶", parent)
    always_on_top_action.setCheckable(True)
    always_on_top_action.setChecked(always_on_top_checked)
    always_on_top_action.setEnabled(interactions_enabled)
    always_on_top_action.triggered.connect(on_toggle_always_on_top)
    menu.addAction(always_on_top_action)

    if live2d_mode in {"full", "half"} and on_set_live2d_mode is not None:
        menu.addSeparator()
        full_action = QAction("Live2D 全身", parent)
        full_action.setCheckable(True)
        full_action.setChecked(live2d_mode == "full")
        full_action.setEnabled(interactions_enabled)
        full_action.triggered.connect(lambda checked=False: on_set_live2d_mode("full"))
        menu.addAction(full_action)

        half_action = QAction("Live2D 半身", parent)
        half_action.setCheckable(True)
        half_action.setChecked(live2d_mode == "half")
        half_action.setEnabled(interactions_enabled)
        half_action.triggered.connect(lambda checked=False: on_set_live2d_mode("half"))
        menu.addAction(half_action)

        if on_set_live2d_scale is not None:
            current_scale = live2d_scale if isinstance(live2d_scale, (int, float)) and live2d_scale > 0 else 1.0
            size_menu = menu.addMenu("角色大小")
            size_menu.setEnabled(interactions_enabled)
            for label, value in (("小", 0.7), ("中（默认）", 1.0), ("大", 1.3), ("特大", 1.6)):
                size_action = QAction(label, parent)
                size_action.setCheckable(True)
                size_action.setChecked(abs(current_scale - value) < 0.01)
                size_action.setEnabled(interactions_enabled)
                size_action.triggered.connect(
                    lambda checked=False, v=value: on_set_live2d_scale(v)
                )
                size_menu.addAction(size_action)

    if mmd_variants and on_set_mmd_variant is not None:
        menu.addSeparator()
        variant_menu = menu.addMenu("MMD 形象")
        variant_menu.setEnabled(interactions_enabled)
        for variant_id, label in mmd_variants.items():
            variant_action = QAction(str(label or variant_id), parent)
            variant_action.setCheckable(True)
            variant_action.setChecked(str(variant_id) == str(mmd_active_variant or ""))
            variant_action.setEnabled(interactions_enabled)
            variant_action.triggered.connect(
                lambda checked=False, v=str(variant_id): on_set_mmd_variant(v)
            )
            variant_menu.addAction(variant_action)

    menu.addSeparator()

    history_action = QAction("历史记录", parent)
    history_action.setEnabled(interactions_enabled)
    history_action.triggered.connect(on_show_history)
    menu.addAction(history_action)

    runtime_log_action = QAction("运行日志", parent)
    runtime_log_action.setEnabled(interactions_enabled)
    runtime_log_action.triggered.connect(on_show_runtime_log)
    menu.addAction(runtime_log_action)

    settings_action = QAction("设置", parent)
    settings_action.setEnabled(interactions_enabled if settings_enabled is None else settings_enabled)
    settings_action.triggered.connect(on_show_settings)
    menu.addAction(settings_action)

    menu.addSeparator()

    quit_action = QAction("退出", parent)
    quit_action.triggered.connect(QApplication.quit)
    menu.addAction(quit_action)

    return menu
