from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

from app.llm.prompts.runtime import estimate_prompt_tokens
from app.llm.prompts.types import ContextFragment
from app.storage.paths import StoragePaths
from app.storage.chat_history import ChatHistoryEntry
from app.storage.history_digest import DigestLine, clean_recent_dialogue


# 当前会话窗口已经有这么多条最近消息时，不再注入跨会话历史切片：
# 此时上次会话的尾巴已被本次实时对话覆盖，再注入只是重复 token。
SESSION_DIGEST_INJECT_MAX_RECENT_MESSAGES = 2
SESSION_STATE_TOKEN_BUDGET = 1024

_INTRO = "最近会话状态（历史事实，不是用户新消息；请自然参考，不要机械复述）："
ACTIVE_SESSION_TOKEN_BUDGET = 768
SESSION_STATE_LIST_LIMIT = 8


@dataclass(frozen=True)
class SessionState:
    """当前会话的结构化短期状态，不进入长期向量记忆。"""

    current_topic: str = ""
    user_goals: list[str] = field(default_factory=list)
    open_tasks: list[str] = field(default_factory=list)
    commitments: list[str] = field(default_factory=list)
    affective_state: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionState":
        return cls(
            current_topic=_clean_text(data.get("current_topic")),
            user_goals=_clean_text_list(data.get("user_goals")),
            open_tasks=_clean_text_list(data.get("open_tasks")),
            commitments=_clean_text_list(data.get("commitments")),
            affective_state=_clean_text(data.get("affective_state")),
            updated_at=_clean_text(data.get("updated_at")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "current_topic": self.current_topic,
            "user_goals": [*self.user_goals],
            "open_tasks": [*self.open_tasks],
            "commitments": [*self.commitments],
            "affective_state": self.affective_state,
            "updated_at": self.updated_at,
        }

    def is_empty(self) -> bool:
        return not any(
            (
                self.current_topic,
                self.user_goals,
                self.open_tasks,
                self.commitments,
                self.affective_state,
            )
        )


class SessionStateStore:
    """按角色保存短期结构化 session state。"""

    def __init__(self, base_dir: Path, *, character_id: str = "default") -> None:
        self.base_dir = Path(base_dir)
        self.character_id = character_id or "default"
        self.path = StoragePaths(self.base_dir).session_state_for(self.character_id)

    def load(self) -> SessionState:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return SessionState()
        except (OSError, json.JSONDecodeError):
            return SessionState()
        if not isinstance(data, dict):
            return SessionState()
        return SessionState.from_dict(data)

    def save(self, state: SessionState) -> None:
        data = state.to_dict()
        if not data.get("updated_at"):
            data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def build_active_session_fragment(state: SessionState) -> ContextFragment | None:
    if state.is_empty():
        return None
    body = ["当前会话状态（短期工作记忆，不是长期记忆；用于保持本轮任务连续性）："]
    if state.current_topic:
        body.append(f"- 当前话题：{state.current_topic}")
    if state.user_goals:
        body.append("- 用户目标：" + "；".join(state.user_goals[:5]))
    if state.open_tasks:
        body.append("- 待推进事项：" + "；".join(state.open_tasks[:6]))
    if state.commitments:
        body.append("- 最近承诺：" + "；".join(state.commitments[:6]))
    if state.affective_state:
        body.append(f"- 互动状态：{state.affective_state}")
    content = "\n".join(body)
    return ContextFragment(
        fragment_id="session_state.active",
        source="session_state",
        content=content,
        trust="untrusted",
        priority=90,
        freshness=state.updated_at,
        token_budget=ACTIVE_SESSION_TOKEN_BUDGET,
        sensitivity="private",
        cache_scope="turn",
    )


def build_session_state_fragment(
    entries: Sequence[ChatHistoryEntry],
    *,
    recent_message_count: int = 0,
    freshness: str = "",
    current_input: str = "",
) -> ContextFragment | None:
    """把上次会话尾部清洗后的对话渲染成跨会话续接上下文。

    仅在会话刚开始（实时窗口尚浅）时注入；内容直接来自持久化的聊天历史，
    读取时现算，对突然关闭天然免疫。
    """

    if recent_message_count >= SESSION_DIGEST_INJECT_MAX_RECENT_MESSAGES:
        return None
    lines = clean_recent_dialogue(entries, current_input=current_input)
    if not lines:
        return None
    body = [_INTRO, "最近对话："]
    rendered_lines = [_render_line(line) for line in lines]
    while estimate_prompt_tokens("\n".join([*body, *rendered_lines])) > SESSION_STATE_TOKEN_BUDGET:
        rendered_lines.pop(0)
    body.extend(rendered_lines)
    return ContextFragment(
        fragment_id="session_state.recent_history",
        source="session_state",
        content="\n".join(body),
        trust="untrusted",
        priority=75,
        freshness=freshness,
        token_budget=SESSION_STATE_TOKEN_BUDGET,
        sensitivity="private",
        cache_scope="turn",
    )


def update_session_state_from_turn(
    previous: SessionState,
    *,
    user_text: str,
    assistant_text: str = "",
    assistant_tones: Sequence[str] | None = None,
) -> SessionState:
    """从最新一轮对话轻量推进短期工作记忆。

    这不是长期记忆抽取器；只沉淀当前任务连续性需要的状态，供下一轮 prompt
    注入。长期偏好仍交给 MemoryCurator / mem0。
    """

    user_text = _clean_text(user_text)
    assistant_text = _clean_text(assistant_text)
    tones = [item for item in (_clean_text_list(list(assistant_tones or []))) if item]
    current_topic = _infer_current_topic(user_text) or previous.current_topic
    goals = _merge_unique(
        [*previous.user_goals, *_infer_user_goals(user_text)],
        limit=SESSION_STATE_LIST_LIMIT,
    )
    open_tasks = _merge_unique(
        [*previous.open_tasks, *_infer_open_tasks(user_text)],
        limit=SESSION_STATE_LIST_LIMIT,
    )
    commitments = _merge_unique(
        [*previous.commitments, *_infer_commitments(assistant_text)],
        limit=SESSION_STATE_LIST_LIMIT,
    )
    affective_state = _infer_affective_state(user_text, tones) or previous.affective_state
    return SessionState(
        current_topic=current_topic,
        user_goals=goals,
        open_tasks=open_tasks,
        commitments=commitments,
        affective_state=affective_state,
        updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def _render_line(line: DigestLine) -> str:
    speaker = "用户" if line.role == "user" else "Sakura"
    return f"- {speaker}：{line.content}"


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:1000]


def _clean_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            result.append(text)
    return result[:12]


def _infer_current_topic(user_text: str) -> str:
    if not user_text:
        return ""
    sentences = _split_sentences(user_text)
    if not sentences:
        return ""
    preferred_keywords = ("问题", "优化", "bug", "Live2D", "模型", "TTS", "记忆", "表情", "口型")
    for sentence in sentences:
        if any(keyword in sentence for keyword in preferred_keywords):
            return _trim_topic_prefix(sentence)[:80]
    return _trim_topic_prefix(sentences[0])[:80]


def _infer_user_goals(user_text: str) -> list[str]:
    goals: list[str] = []
    if not user_text:
        return goals
    if "TTS" in user_text or "语音" in user_text or "吞语音" in user_text:
        goals.append("TTS 语音要跟随对话输出，不能吞语音")
    if "表情" in user_text or "星星眼" in user_text:
        goals.append("表情要明显显示，并拓展星星眼等表现")
    if "嘴" in user_text or "口型" in user_text:
        goals.append("说话时嘴动要自然，不要过快")
    if "全身" in user_text or "半身" in user_text or "大小" in user_text or "比例" in user_text:
        goals.append("Live2D 全身/半身大小比例要舒服，全身保持清晰")
    if "记忆" in user_text:
        goals.append("记忆架构要更深，短期任务和长期记忆分层清楚")
    return goals


def _infer_open_tasks(user_text: str) -> list[str]:
    tasks: list[str] = []
    if any(token in user_text for token in ("大小", "比例", "全身", "半身", "糊")):
        tasks.append("处理 Live2D 模型大小/比例/清晰度")
    if any(token in user_text for token in ("表情", "星星眼")):
        tasks.append("拓展并验证 Live2D 表情显示")
    if any(token in user_text for token in ("嘴", "口型", "嘴动")):
        tasks.append("调慢并验证 Live2D 口型节奏")
    if any(token in user_text for token in ("TTS", "语音", "吞语音", "跟随对话")):
        tasks.append("排查并修复 TTS 吞语音/不同步")
    if "记忆" in user_text:
        tasks.append("深化短期会话状态和长期记忆分层架构")
    return tasks


def _infer_commitments(assistant_text: str) -> list[str]:
    if not assistant_text:
        return []
    commitments: list[str] = []
    sentences = _split_sentences(assistant_text)
    for sentence in sentences:
        if re.search(r"(我会|我现在|接下来|马上|先|继续|准备|会)", sentence):
            commitments.append(sentence[:120])
    return commitments[:4]


def _infer_affective_state(user_text: str, tones: Sequence[str]) -> str:
    text = user_text
    if any(token in text for token in ("还是", "不能", "问题", "有点", "太快", "糊")):
        return "用户在持续验收桌宠视觉和语音体验，要求直接落地验证"
    if any(tone in {"不满", "困惑", "哭"} for tone in tones):
        return "用户可能对当前体验仍有疑虑，需要明确验证结果"
    return ""


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]
    return [" ".join(part.split()) for part in parts]


def _trim_topic_prefix(text: str) -> str:
    return re.sub(r"^(现在|目前|然后就是|然后|还有就是|就是|另外|同时|接下来)", "", text).strip()


def _merge_unique(values: Sequence[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result[-limit:]
