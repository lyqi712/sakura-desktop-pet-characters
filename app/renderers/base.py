"""app/renderers/base.py — 通用角色渲染器抽象接口。

定义 :class:`CharacterRenderer`：一个与具体渲染后端无关的角色显示接口，
后续 PNG / Live2D / VRM / MMD 都实现同一套接口，宿主只面向接口编程。

设计要点：
- 接口命名通用，不绑定任何具体后端（不出现 MMD 字样）。
- 所有方法默认是空操作（no-op），这样调用方无需到处判断渲染器能力，
  未实现的能力静默忽略即可。
- ``is_available`` 用于宿主判断该后端在当前环境是否可用，便于降级。
"""

from __future__ import annotations

from typing import Any


class CharacterRenderer:
    """角色渲染器抽象基类。

    子类至少应覆盖 :attr:`renderer_name`，并按需覆盖其余方法。
    未覆盖的方法保持空操作语义，不抛异常。
    """

    # 渲染后端标识，子类覆盖（如 "default" / "mmd" / "live2d"）。
    renderer_name: str = "base"
    # 是否接管角色主体显示；为 True 时宿主隐藏默认 PNG 立绘。
    replaces_default_portrait: bool = False
    # 几何坐标是否相对于宿主窗口；独立窗口渲染器保持屏幕坐标。
    uses_owner_coordinates: bool = False
    # 是否支持拖拽时由宿主窗口用静态快照代替渲染窗口，避免透明顶层窗口移动产生合成残影。
    supports_drag_snapshot: bool = False

    def initialize(self, app_context: dict[str, Any] | None = None) -> None:
        """初始化渲染后端。可能创建窗口、加载资源等。

        约定：初始化失败应抛异常，由 :class:`RendererManager` 捕获并降级。
        """

    def load_character(self, character_config: dict[str, Any]) -> None:
        """加载角色配置（模型、动作、表情、口型等映射）。"""

    def show(self) -> None:
        """显示角色。"""

    def hide(self) -> None:
        """隐藏角色。"""

    def close(self) -> None:
        """关闭并释放资源。"""

    def capture_snapshot(self) -> Any | None:
        """返回当前渲染内容快照；不支持的后端返回 None。"""
        return None

    def set_position(self, x: int, y: int) -> None:
        """设置角色窗口左上角的屏幕坐标。"""

    def set_geometry(self, x: int, y: int, width: int, height: int, layout_height: int | None = None) -> None:
        """设置角色窗口屏幕几何；不支持尺寸的后端可只响应位置。

        layout_height 为可选的完整布局参考高度（用于 canvas 被裁短时仍按完整高度缩放模型）；
        不支持的后端忽略即可。
        """
        self.set_position(x, y)

    def stack_below(self, owner_window: Any, *, topmost: bool | None = None) -> None:
        """将独立角色窗口放到宿主窗口下方；单窗口后端可忽略。"""

    def set_clip_mask(self, keep_top_height: int | None) -> None:
        """把独立角色窗口顶部保留 keep_top_height 像素、其下挖空（透出宿主气泡/输入栏）。

        keep_top_height 为 None 时清除遮罩（整窗可见）。用于让气泡永远盖在角色前面：
        窗口几何保持完整立绘高度（canvas 尺寸恒定不触发 WebGL framebuffer 重建 → 不闪），
        仅用窗口 mask 裁掉气泡顶以下的下半身，使宿主窗口绘制的气泡从挖空处透出到最前。
        单窗口/无独立窗口的后端可忽略。
        """

    def set_scale(self, scale: float) -> None:
        """设置角色缩放比例（1.0 为原始大小）。"""

    def set_mode(self, mode: str) -> None:
        """设置渲染模式（例如 half/full）；不支持的后端可忽略。"""

    def play_motion(self, motion_name: str, loop: bool = False) -> None:
        """播放指定动作；``loop`` 为 True 时循环。"""

    def stop_motion(self, motion_name: str | None = None) -> None:
        """停止动作；``motion_name`` 为 None 时停止全部。"""

    def set_expression(self, expression_name: str, weight: float = 1.0) -> None:
        """设置表情；``weight`` 为权重（0~1）。"""

    def set_lip_sync(self, value: float) -> None:
        """设置口型开合程度（0~1）。"""

    def look_at(self, x: float, y: float) -> None:
        """让角色看向归一化坐标 (x, y)。"""

    def handle_event(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """处理来自宿主事件总线的事件（如 tts.started / llm.request.started）。"""

    def trigger_scene_action(self, kind: str, name: str | None = None) -> None:
        """Trigger a renderer-specific scene action."""

    def is_available(self) -> bool:
        """该渲染后端在当前环境是否可用。默认可用。"""
        return True
