"""Audio amplitude helpers for renderer lip sync."""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import QObject, QTimer


def amplitude_from_pcm_bytes(data: bytes, *, sample_width: int, channels: int = 1) -> float:
    """Return a normalized RMS mouth-open value for signed 16-bit PCM."""
    if not data or sample_width != 2 or channels < 1:
        return 0.0

    frame_width = sample_width * channels
    frame_count = len(data) // frame_width
    if frame_count <= 0:
        return 0.0

    total = 0.0
    for frame in range(frame_count):
        frame_sum = 0.0
        base = frame * frame_width
        for channel in range(channels):
            offset = base + channel * sample_width
            sample = int.from_bytes(data[offset : offset + sample_width], byteorder="little", signed=True)
            frame_sum += sample
        mixed = frame_sum / channels
        total += mixed * mixed

    rms = math.sqrt(total / frame_count) / 32768.0
    return min(1.0, max(0.0, rms * 5.0))


def amplitude_frames_from_wav(audio_path: Path | str, *, fps: int = 25) -> Iterator[float]:
    """Yield smoothed mouth-open values sampled from a WAV file."""
    path = Path(audio_path)
    with wave.open(str(path), "rb") as wav_file:
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        frame_rate = wav_file.getframerate()
        frames_per_tick = max(1, int(frame_rate / max(1, fps)))
        smoothed = 0.0

        while True:
            chunk = wav_file.readframes(frames_per_tick)
            if not chunk:
                break
            target = amplitude_from_pcm_bytes(chunk, sample_width=sample_width, channels=channels)
            smoothed += (target - smoothed) * 0.65
            yield round(smoothed, 4)


class RendererLipSyncDriver(QObject):
    """Drive a renderer's mouth value from the currently playing WAV file."""

    def __init__(self, renderer_getter, *, fps: int = 25, parent: QObject | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self._renderer_getter = renderer_getter
        self._fps = max(1, int(fps))
        self._timer = QTimer(self)
        self._timer.setInterval(max(10, int(1000 / self._fps)))
        self._timer.timeout.connect(self._tick)
        self._frames: Iterator[float] | None = None

    def start(self, audio_path: Path | str) -> None:
        self.stop()
        try:
            self._frames = amplitude_frames_from_wav(Path(audio_path), fps=self._fps)
        except Exception:
            self._frames = None
            self._set_value(0.0)
            return
        self._timer.start()

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self._frames = None
        self._set_value(0.0)

    def _tick(self) -> None:
        if self._frames is None:
            self.stop()
            return
        try:
            value = next(self._frames)
        except StopIteration:
            self.stop()
            return
        except Exception:
            self.stop()
            return
        self._set_value(value)

    def _set_value(self, value: float) -> None:
        renderer = self._renderer_getter()
        if renderer is None:
            return
        setter = getattr(renderer, "set_lip_sync", None)
        if callable(setter):
            setter(max(0.0, min(1.0, float(value))))
