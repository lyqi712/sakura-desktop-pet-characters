"""TTS 合成队列与合成引擎（issue #94 第 3 阶段）。

从 ``app/voice/tts.py`` 抽出「合成队列」这一职责：把 speak/prepare 提交的请求串行
化、在后台 daemon 线程里走服务就绪门控 + HTTP 合成 + 写临时 wav，再把结果交回
播放端点（sink）。

线程模型保持不变——每个请求一个一次性 daemon 线程，靠 ``_request_running`` 串行；
该线程登记进协调器自持 ``ResourceManager`` 的 :class:`ThreadResource`，关闭时随
``stop_all`` 走 cancel→join→linger。GPT-SoVITS 与 Genie 的合成差异封装在
:class:`GPTSoVITSSynthesisEngine` / :class:`GenieSynthesisEngine`，队列只负责调度。
"""

from __future__ import annotations

import array
import json
import math
import re
import tempfile
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Protocol

from app.core.debug_log import debug_log
from app.core.interaction import set_interaction_id
from app.llm.chat_reply import DEFAULT_TONE
from app.voice import audio_checks as _audio_checks
from app.voice.tts_settings import ToneReference as _ToneReference
from app.voice.tts_service import (
    _encode_genie_character_name,
    _format_gpt_sovits_http_error,
    _is_soft_synth_failure,
)
from app.voice.tts_types import TTSCallback, TTSPreparedAudio, _TTSRequest

_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
# 可发音字符:数字/拉丁字母/假名/汉字/谚文(含全角)。纯标点、emoji、符号不算——
# 这类文本喂给 GPT-SoVITS 归一化后音素为空,会触发服务端 [Errno 22] Invalid argument。
_VOICEABLE_CHAR_RE = re.compile(
    "[0-9A-Za-z"
    "぀-ヿ"  # 平假名/片假名
    "㐀-䶿"  # CJK 扩展 A
    "一-鿿"  # CJK 基本
    "豈-﫿"  # CJK 兼容
    "가-힣"  # 谚文音节
    "０-９Ａ-Ｚａ-ｚ"  # 全角数字/字母
    "ｦ-ﾟ"  # 半角片假名
    "]"
)
_CJK_TEXT_LANGS = {"ja", "all_ja", "zh", "all_zh", "ko", "all_ko", "yue", "all_yue"}
_CHINESE_PROMPT_LANGS = {"zh", "all_zh", "yue", "all_yue"}
_GPT_SOVITS_PROMPT_TEXT_MAX_VOICEABLE_CHARS = 18
_GPT_SOVITS_SHORT_AUDIO_MIN_CHARS = 10
_GPT_SOVITS_MIN_DURATION_MS_PER_VOICEABLE_CHAR = 150
_GPT_SOVITS_MIN_DURATION_MS_FLOOR = 1200
_GPT_SOVITS_MIN_DURATION_MS_CEILING = 12000
_LEADING_TTS_PUNCTUATION_RE = re.compile(r"^[\s。．.!！?？,，、;；:：]+")
_GPT_SOVITS_SPLIT_PUNCTUATION_RE = re.compile(r"[，。？！,\.?!~:：—…]")
_GPT_SOVITS_STYLE_PARAM_DEFAULTS: dict[str, int | float] = {
    "top_k": 15,
    "top_p": 1,
    "temperature": 1,
    "repetition_penalty": 1.15,
    "speed_factor": 1.0,
    "fragment_interval": 0.3,
}
_GPT_SOVITS_STYLE_PARAM_RANGES: dict[str, tuple[float, float]] = {
    "top_k": (1, 100),
    "top_p": (0.0, 1.0),
    "temperature": (0.0, 2.0),
    "repetition_penalty": (0.1, 3.0),
    "speed_factor": (0.5, 2.0),
    "fragment_interval": (0.0, 2.0),
}


def _is_voiceable_text(text: str) -> bool:
    """文本是否含可发音内容。纯标点/emoji/符号归一化后音素为空，会触发服务端
    [Errno 22] Invalid argument，提前判定可避免无谓的失败往返。"""
    return bool(_VOICEABLE_CHAR_RE.search(text))


def _resolve_request_text_lang(text: str, configured_text_lang: str) -> str:
    """英文混入中日韩文本时切到 auto，避免 GPT-SoVITS 按单语 BERT 处理失败。"""
    normalized = configured_text_lang.strip().lower()
    if normalized in _CJK_TEXT_LANGS and _LATIN_LETTER_RE.search(text):
        return "auto_yue" if normalized in {"yue", "all_yue"} else "auto"
    return normalized or "zh"


def _voiceable_char_count(text: str) -> int:
    return len(_VOICEABLE_CHAR_RE.findall(text))


def _sanitize_gpt_sovits_text(text: str, text_lang: str = "") -> str:
    """整理 GPT-SoVITS 入参文本，避开中文短开头触发的服务端补句号早停。"""
    stripped = text.strip()
    cleaned = _LEADING_TTS_PUNCTUATION_RE.sub("", stripped).strip()
    cleaned = cleaned or stripped
    return _merge_short_cjk_opening_clause(cleaned, text_lang)


def _merge_short_cjk_opening_clause(text: str, text_lang: str) -> str:
    normalized_lang = text_lang.strip().lower()
    if normalized_lang not in _CHINESE_PROMPT_LANGS:
        return text

    cleaned = text
    while True:
        match = _GPT_SOVITS_SPLIT_PUNCTUATION_RE.search(cleaned)
        if match is None:
            return cleaned

        prefix = cleaned[: match.start()].strip()
        suffix = cleaned[match.end() :].lstrip()
        if not suffix or not _is_voiceable_text(suffix):
            return cleaned

        prefix_voiceable_chars = _voiceable_char_count(prefix)
        if prefix_voiceable_chars == 0 or prefix_voiceable_chars >= 4:
            return cleaned

        cleaned = f"{prefix}{suffix}"


def _minimum_reasonable_duration_ms(text: str) -> int | None:
    voiceable_chars = _voiceable_char_count(text)
    if voiceable_chars < _GPT_SOVITS_SHORT_AUDIO_MIN_CHARS:
        return None
    duration = voiceable_chars * _GPT_SOVITS_MIN_DURATION_MS_PER_VOICEABLE_CHAR
    return max(
        _GPT_SOVITS_MIN_DURATION_MS_FLOOR,
        min(_GPT_SOVITS_MIN_DURATION_MS_CEILING, duration),
    )


def _is_audio_too_short_for_text(audio_path: Path, text: str) -> tuple[bool, int | None, int | None]:
    duration_ms = _audio_checks._wav_duration_ms(audio_path)
    minimum_ms = _minimum_reasonable_duration_ms(text)
    if duration_ms is None or minimum_ms is None:
        return False, duration_ms, minimum_ms
    return duration_ms < minimum_ms, duration_ms, minimum_ms


def _gpt_sovits_prompt_text(reference: _ToneReference) -> str:
    """GPT-SoVITS prompt_text 仅给非中文短参考保留；中文参考只用参考音频。"""
    prompt_text = reference.ref_text.strip()
    if prompt_text and reference.ref_lang.strip().lower() in _CHINESE_PROMPT_LANGS:
        debug_log(
            "TTS",
            "GPT-SoVITS 中文参考文本已从 prompt_text 移除以避免串音和早停",
            {
                "tone": reference.tone,
                "ref_audio_path": reference.ref_audio_path,
                "ref_lang": reference.ref_lang,
                "ref_text_chars": len(prompt_text),
                "voiceable_chars": _voiceable_char_count(prompt_text),
            },
        )
        return ""
    if _voiceable_char_count(prompt_text) > _GPT_SOVITS_PROMPT_TEXT_MAX_VOICEABLE_CHARS:
        debug_log(
            "TTS",
            "GPT-SoVITS 参考文本过长，已从 prompt_text 移除以避免串音",
            {
                "tone": reference.tone,
                "ref_audio_path": reference.ref_audio_path,
                "ref_text_chars": len(prompt_text),
                "voiceable_chars": _voiceable_char_count(prompt_text),
            },
        )
        return ""
    return prompt_text


def _gpt_sovits_style_params(settings: object, tone: str | None) -> dict[str, int | float]:
    params = dict(_GPT_SOVITS_STYLE_PARAM_DEFAULTS)
    _merge_gpt_sovits_style_params(
        params,
        getattr(settings, "gpt_sovits_voice_params", None),
        scope="default",
    )
    tone_key = (tone or DEFAULT_TONE).strip() or DEFAULT_TONE
    tone_params = getattr(settings, "gpt_sovits_tone_params", None)
    if isinstance(tone_params, dict):
        _merge_gpt_sovits_style_params(
            params,
            tone_params.get(tone_key),
            scope=f"tone:{tone_key}",
        )
    return params


def _merge_gpt_sovits_style_params(
    target: dict[str, int | float],
    source: Any,
    *,
    scope: str,
) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        if key not in _GPT_SOVITS_STYLE_PARAM_RANGES:
            debug_log("TTS", "忽略不支持的 GPT-SoVITS 语音参数", {"scope": scope, "key": key})
            continue
        coerced = _coerce_gpt_sovits_style_param(key, value)
        if coerced is None:
            debug_log(
                "TTS",
                "忽略非法 GPT-SoVITS 语音参数",
                {"scope": scope, "key": key, "value": value},
            )
            continue
        target[key] = coerced


def _coerce_gpt_sovits_style_param(key: str, value: Any) -> int | float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    minimum, maximum = _GPT_SOVITS_STYLE_PARAM_RANGES[key]
    if parsed < minimum or parsed > maximum:
        return None
    if key == "top_k":
        return int(parsed)
    return parsed


def _write_genie_audio(audio_data: bytes, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_data[:4] == b"RIFF":
        output_path.write_bytes(audio_data)
        return _audio_checks._is_valid_wav_file(output_path)
    return _write_raw_float_or_pcm_as_wav(audio_data, output_path, sample_rate=32000)


def _write_raw_pcm_as_wav(raw_bytes: bytes, output_path: Path, *, sample_rate: int) -> bool:
    if not raw_bytes or len(raw_bytes) % 2 != 0:
        return False
    try:
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(raw_bytes)
        return _audio_checks._is_valid_wav_file(output_path)
    except (OSError, wave.Error):
        return False


def _write_raw_float_or_pcm_as_wav(raw_bytes: bytes, output_path: Path, *, sample_rate: int) -> bool:
    pcm_bytes = b""
    if len(raw_bytes) % 4 == 0:
        try:
            floats = array.array("f")
            floats.frombytes(raw_bytes)
            finite_values = [value for value in floats if math.isfinite(value)]
            if finite_values and max(abs(value) for value in finite_values) <= 2.0:
                pcm = array.array("h")
                for value in floats:
                    if not math.isfinite(value):
                        value = 0.0
                    pcm.append(int(max(-1.0, min(1.0, value)) * 32767.0))
                pcm_bytes = pcm.tobytes()
        except (OverflowError, ValueError):
            pcm_bytes = b""
    if not pcm_bytes and len(raw_bytes) % 2 == 0:
        pcm_bytes = raw_bytes
    if not pcm_bytes:
        return False
    return _write_raw_pcm_as_wav(pcm_bytes, output_path, sample_rate=sample_rate)


class TTSSynthesisSink(Protocol):
    """合成结果交回播放端点（commit 5 前由协调器实现）的契约。"""

    def deliver_audio(
        self,
        audio_path: str,
        on_started: TTSCallback | None,
        on_finished: TTSCallback | None,
        text: str,
    ) -> None:
        """投递一段已合成音频到播放队列。"""

    def deliver_prepared(self, handle: TTSPreparedAudio, audio_path: str) -> None:
        """投递一段预生成音频到对应句柄。"""

    def fail_audio_request(self, request: _TTSRequest, message: str) -> None:
        """合成失败：走失败回调并按需向 UI 报错。"""

    def skip_audio_request(self, request: _TTSRequest, reason: str) -> None:
        """合成静默跳过：正常走完回调但不报错。"""

    def schedule_cleanup(self, audio_path: Path) -> None:
        """安排清理无效/废弃的临时 wav。"""


class GPTSoVITSSynthesisEngine:
    """GPT-SoVITS HTTP 合成引擎：就绪门控 + 权重 + POST + Broken pipe 重启重试。"""

    service_label = "GPT-SoVITS"

    def synthesize(self, queue: "TTSSynthesisQueue", request: _TTSRequest, *, fail, skip) -> Path | None:
        supervisor = queue._supervisor
        settings = queue.settings
        restart_attempted = False
        short_audio_retry_attempted = False
        request_attempt = 1
        request_text = _sanitize_gpt_sovits_text(request.text, settings.text_lang)
        while True:
            if not supervisor._ensure_service_available(fail):
                return None

            if not supervisor._ensure_character_weights(fail):
                return None

            reference = queue._select_reference(request.tone)
            prompt_text = _gpt_sovits_prompt_text(reference)
            style_params = _gpt_sovits_style_params(settings, request.tone)
            payload = {
                "text": request_text,
                "text_lang": _resolve_request_text_lang(
                    request_text,
                    settings.text_lang,
                ),
                "ref_audio_path": str(reference.ref_audio_path),
                "prompt_text": prompt_text,
                "prompt_lang": reference.ref_lang,
                "text_split_method": getattr(settings, "text_split_method", "cut2") or "cut2",
                "parallel_infer": False,
                "batch_size": 1,
                "split_bucket": False,
                "media_type": "wav",
                "streaming_mode": False,
                **style_params,
            }
            debug_log(
                "TTS",
                "发送 GPT-SoVITS 请求",
                {
                    "api_url": settings.api_url,
                    "text": request_text,
                    "source_text": request.text,
                    "tone": request.tone,
                    "reference": {
                        "tone": reference.tone,
                        "ref_audio_path": reference.ref_audio_path,
                        "ref_lang": reference.ref_lang,
                    },
                    "payload": payload,
                    "attempt": request_attempt,
                    "short_audio_retry": short_audio_retry_attempted,
                },
            )
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            http_request = urllib.request.Request(
                url=settings.api_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )

            try:
                with urllib.request.urlopen(
                    http_request,
                    timeout=settings.timeout_seconds,
                ) as response:
                    audio_data = response.read()
                    debug_log(
                        "TTS",
                        "GPT-SoVITS 请求成功",
                        {
                            "status": getattr(response, "status", None),
                            "audio_bytes": len(audio_data),
                            "attempt": request_attempt,
                        },
                    )
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                debug_log(
                    "TTS",
                    "GPT-SoVITS HTTP 失败",
                    {
                        "status": exc.code,
                        "error_body": error_body,
                        "attempt": request_attempt,
                    },
                )
                if (
                    not restart_attempted
                    and supervisor._restart_local_service_after_http_failure(exc.code, error_body)
                ):
                    restart_attempted = True
                    request_attempt += 1
                    continue
                message = _format_gpt_sovits_http_error(exc.code, error_body)
                if _is_soft_synth_failure(exc.code, error_body):
                    # 单段合成失败（服务端 tts failed）：文本已照常显示，语音缺一段无需
                    # 打断用户，静默跳过、正常完成回调，不向 UI 弹 TTS 异常。
                    skip(message)
                else:
                    fail(message)
                return None
            except urllib.error.URLError as exc:
                debug_log("TTS", "GPT-SoVITS 请求失败", {"reason": str(exc.reason)})
                if (
                    not restart_attempted
                    and supervisor._restart_local_service_after_transport_failure(exc)
                ):
                    restart_attempted = True
                    request_attempt += 1
                    continue
                fail(
                    f"GPT-SoVITS 请求失败，请确认服务已启动并可访问 {settings.api_url}：{exc.reason}"
                )
                return None
            except TimeoutError:
                debug_log("TTS", "GPT-SoVITS 请求超时")
                if (
                    not restart_attempted
                    and supervisor._restart_local_service_after_transport_failure(
                        TimeoutError(f"request timed out: {settings.api_url}")
                    )
                ):
                    restart_attempted = True
                    request_attempt += 1
                    continue
                fail("GPT-SoVITS 请求超时。")
                return None

            if not audio_data:
                debug_log("TTS", "GPT-SoVITS 返回空音频")
                fail("GPT-SoVITS 返回了空音频。")
                return None

            with tempfile.NamedTemporaryFile(
                prefix="sakura_tts_",
                suffix=".wav",
                delete=False,
                dir=str(queue._cache_dir),
            ) as audio_file:
                audio_file.write(audio_data)
                audio_path = Path(audio_file.name)
            debug_log("TTS", "临时音频已写入", {"audio_path": audio_path, "bytes": len(audio_data)})
            audio_issue = _audio_checks._verify_generated_audio(audio_path)
            if audio_issue is not None:
                debug_log("TTS", "生成音频校验失败", {"audio_path": audio_path, "issue": audio_issue})
                fail(f"GPT-SoVITS 生成的音频无效（{audio_issue}）。")
                queue._cleanup(audio_path)
                return None

            too_short, duration_ms, minimum_ms = _is_audio_too_short_for_text(audio_path, request_text)
            if too_short and not short_audio_retry_attempted:
                debug_log(
                    "TTS",
                    "GPT-SoVITS 音频短于文本最低合理时长，重试一次",
                    {
                        "text": request_text,
                        "source_text": request.text,
                        "audio_path": audio_path,
                        "duration_ms": duration_ms,
                        "minimum_ms": minimum_ms,
                        "voiceable_chars": _voiceable_char_count(request_text),
                    },
                )
                queue._cleanup(audio_path)
                short_audio_retry_attempted = True
                request_attempt += 1
                continue
            if too_short:
                debug_log(
                    "TTS",
                    "GPT-SoVITS 重试后音频仍偏短，丢弃该段",
                    {
                        "text": request_text,
                        "source_text": request.text,
                        "audio_path": audio_path,
                        "duration_ms": duration_ms,
                        "minimum_ms": minimum_ms,
                        "voiceable_chars": _voiceable_char_count(request_text),
                    },
                )
                queue._cleanup(audio_path)
                fail(
                    "GPT-SoVITS 生成的音频短于文本最低合理时长，"
                    "已丢弃该段以避免播放错乱语音。"
                )
                return None
            return audio_path


class GenieSynthesisEngine:
    """Genie TTS 合成引擎：就绪门控 + 角色模型/参考音频 + POST + WAV 转换。"""

    service_label = "Genie TTS"

    def synthesize(self, queue: "TTSSynthesisQueue", request: _TTSRequest, *, fail, skip) -> Path | None:
        supervisor = queue._supervisor
        settings = queue.settings
        if not supervisor._ensure_service_available(fail):
            return None

        reference = queue._select_reference(request.tone)
        if not supervisor._ensure_character_model(reference.ref_lang, fail):
            return None
        if not supervisor._ensure_reference_audio(reference, fail):
            return None

        payload = {
            "character_name": _encode_genie_character_name(supervisor._genie_character_name()),
            "text": request.text,
            "split_sentence": False,
        }
        debug_log(
            "TTS",
            "发送 Genie TTS 请求",
            {
                "api_url": settings.api_url,
                "text": request.text,
                "tone": request.tone,
                "payload": payload,
            },
        )
        try:
            audio_data = supervisor._post_json_and_read_bytes(
                "tts",
                payload,
                timeout=max(settings.timeout_seconds, 120),
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            fail(f"Genie TTS HTTP {exc.code}: {error_body}")
            return None
        except urllib.error.URLError as exc:
            fail(f"Genie TTS 请求失败，请确认服务已启动并可访问 {settings.api_url}：{exc.reason}")
            return None
        except TimeoutError:
            fail("Genie TTS 请求超时。")
            return None

        if not audio_data:
            fail("Genie TTS 返回了空音频。")
            return None

        with tempfile.NamedTemporaryFile(
            prefix="sakura_genie_tts_",
            suffix=".wav",
            delete=False,
            dir=str(queue._cache_dir),
        ) as audio_file:
            audio_path = Path(audio_file.name)
        try:
            if not _write_genie_audio(audio_data, audio_path):
                fail("Genie TTS 返回的音频无法转换为 WAV。")
                queue._cleanup(audio_path)
                return None
        except OSError as exc:
            fail(f"Genie TTS 写入临时音频失败：{exc}")
            queue._cleanup(audio_path)
            return None

        debug_log("TTS", "Genie 临时音频已写入", {"audio_path": audio_path, "bytes": len(audio_data)})
        audio_issue = _audio_checks._verify_generated_audio(audio_path)
        if audio_issue is not None:
            debug_log("TTS", "Genie 生成音频校验失败", {"audio_path": str(audio_path), "issue": audio_issue})
            fail(f"Genie TTS 生成的音频无效（{audio_issue}）。")
            queue._cleanup(audio_path)
            return None
        return audio_path


class TTSSynthesisQueue:
    """串行化 speak/prepare 请求，在后台 daemon 线程里调引擎合成并交回 sink。

    线程域 = PYTHON_THREAD：每请求一个一次性 daemon 线程，靠 ``_request_running``
    串行；当前在飞线程登记进 RM 的 :class:`ThreadResource`，关闭随 stop_all 收敛。
    """

    def __init__(
        self,
        *,
        supervisor: object,
        engine: object,
        cache_dir: Path,
        resource_manager: object | None,
        sink: TTSSynthesisSink,
        is_closed,
    ) -> None:
        self._supervisor = supervisor
        self._engine = engine
        self._cache_dir = cache_dir
        self._resource_manager = resource_manager
        self._sink = sink
        self._is_closed = is_closed
        self._lock = threading.Lock()
        self._pending_requests: list[_TTSRequest] = []
        self._request_running = False
        self._tone_indices: dict[str, int] = {}
        self._thread_resource = (
            resource_manager.track_python_thread(label="tts_synthesis")
            if resource_manager is not None
            else None
        )

    @property
    def settings(self):  # type: ignore[no-untyped-def]
        return self._supervisor.settings

    def submit(self, request: _TTSRequest) -> None:
        # is_closed 走协调器的 _close_lock；避免在持有本队列锁时回调形成反向锁序。
        if self._is_closed():
            if request.prepared_audio is not None:
                request.prepared_audio.failed = True
            debug_log(
                "TTS",
                "Provider 已关闭，丢弃新请求",
                {
                    "text": request.text,
                    "tone": request.tone,
                    "prepared": request.prepared_audio is not None,
                },
            )
            return
        with self._lock:
            self._pending_requests.append(request)
            pending_count = len(self._pending_requests)
        debug_log(
            "TTS",
            "请求加入队列",
            {
                "text": request.text,
                "tone": request.tone,
                "prepared": request.prepared_audio is not None,
                "pending_count": pending_count,
            },
        )
        self._start_next_request()

    def _start_next_request(self) -> None:
        if self._is_closed():
            return
        with self._lock:
            if self._request_running or not self._pending_requests:
                return
            request = self._pending_requests.pop(0)
            self._request_running = True

        debug_log(
            "TTS",
            "开始处理队列请求",
            {
                "text": request.text,
                "tone": request.tone,
                "prepared": request.prepared_audio is not None,
            },
        )
        thread = threading.Thread(
            target=self._request_audio,
            args=(request,),
            daemon=True,
        )
        # 必须先登记再启动：若 close() 恰好落在 start/track 之间，stop_all 会漏掉
        # 已经运行的线程，使其可能在 Qt 对象析构后继续投递结果。
        if self._thread_resource is not None:
            self._thread_resource.track(thread)
        thread.start()

    def _request_audio(self, tts_request: _TTSRequest) -> None:
        # 请求线程恢复发起方的交互 ID，使本线程内日志可与该次交互串联
        set_interaction_id(tts_request.interaction_id)
        try:
            if self._is_closed():
                debug_log("TTS", "Provider 已关闭，跳过音频请求", {"text": tts_request.text})
                return
            if tts_request.prepared_audio is not None and tts_request.prepared_audio.cancelled:
                debug_log("TTS", "请求已取消，跳过音频生成", {"text": tts_request.text})
                return

            # 纯标点/emoji/符号段没有可发音内容，喂给服务端会归一化成空音素并触发
            # [Errno 22]；提前判定为“无需发音”，正常走完回调但不发请求、不报错。
            if not _is_voiceable_text(tts_request.text):
                debug_log("TTS", "文本无可发音内容，跳过合成", {"text": tts_request.text})
                self._sink.skip_audio_request(tts_request, "无可发音内容")
                return

            fail = lambda message: self._sink.fail_audio_request(tts_request, message)
            skip = lambda reason: self._sink.skip_audio_request(tts_request, reason)
            audio_path = self._engine.synthesize(self, tts_request, fail=fail, skip=skip)
            if audio_path is None:
                return
            if tts_request.prepared_audio is None:
                self._sink.deliver_audio(
                    str(audio_path),
                    tts_request.on_started,
                    tts_request.on_finished,
                    tts_request.text,
                )
            else:
                self._sink.deliver_prepared(tts_request.prepared_audio, str(audio_path))
        finally:
            with self._lock:
                self._request_running = False
            self._start_next_request()

    def _select_reference(self, tone: str | None) -> _ToneReference:
        tone_key = (tone or DEFAULT_TONE).strip() or DEFAULT_TONE
        references = self.settings.tone_references.get(tone_key)
        if not references:
            references = self.settings.tone_references.get(DEFAULT_TONE)
        if not references:
            reference = _ToneReference(
                tone=DEFAULT_TONE,
                ref_audio_path=self.settings.ref_audio_path,
                ref_text=self.settings.ref_text,
                ref_lang=self.settings.ref_lang,
            )
            debug_log(
                "TTS",
                "选择默认参考音频",
                {
                    "requested_tone": tone,
                    "ref_audio_path": reference.ref_audio_path,
                    "ref_lang": reference.ref_lang,
                },
            )
            return reference

        index = self._tone_indices.get(tone_key, 0) % len(references)
        self._tone_indices[tone_key] = index + 1
        reference = references[index]
        debug_log(
            "TTS",
            "选择语气参考音频",
            {
                "requested_tone": tone,
                "resolved_tone": tone_key,
                "index": index,
                "count": len(references),
                "ref_audio_path": reference.ref_audio_path,
                "ref_lang": reference.ref_lang,
            },
        )
        return reference

    def _cleanup(self, audio_path: Path) -> None:
        self._sink.schedule_cleanup(audio_path)

    def discard_pending(self, handle: TTSPreparedAudio) -> None:
        """从待合成队列移除指定预生成句柄的请求。"""
        with self._lock:
            self._pending_requests = [
                request
                for request in self._pending_requests
                if request.prepared_audio is not handle
            ]

    def clear_pending(self) -> None:
        """清空待合成队列（关闭时调用）。"""
        with self._lock:
            self._pending_requests.clear()
