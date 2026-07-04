from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.plugins import PluginBase, PluginCapabilityRegistry, PluginContext, ToolContribution


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


class AtriMusicLibrary:
    def __init__(self, audio_dir: Path) -> None:
        self.audio_dir = Path(audio_dir)

    def list_tracks(self) -> list[dict[str, str]]:
        if not self.audio_dir.is_dir():
            return []
        tracks = [
            path
            for path in self.audio_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
        ]
        return [
            {"name": path.name, "path": str(path)}
            for path in sorted(tracks, key=lambda item: item.name.casefold())
        ]

    def find(self, filename: str) -> Path:
        name = Path(str(filename or "").strip()).name
        if not name:
            raise ValueError("filename is required")
        path = (self.audio_dir / name).resolve()
        root = self.audio_dir.resolve()
        if path != root and root not in path.parents:
            raise ValueError("filename must stay inside the ATRI music directory")
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise FileNotFoundError(f"music file not found: {name}")
        return path

    def first_track(self) -> Path | None:
        tracks = self.list_tracks()
        if not tracks:
            return None
        return Path(tracks[0]["path"])


class AtriMusicPlayer:
    def __init__(self) -> None:
        self._player: Any | None = None
        self._audio_output: Any | None = None
        self._current: Path | None = None

    def play(self, path: Path) -> dict[str, Any]:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception as exc:  # noqa: BLE001 - runtime can still list tracks.
            raise RuntimeError("Qt Multimedia is unavailable for audio playback") from exc

        if self._player is None:
            self._audio_output = QAudioOutput()
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_output)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self._current = path
        return {"status": "playing", "path": str(path)}

    def stop(self) -> dict[str, Any]:
        if self._player is not None:
            self._player.stop()
        self._current = None
        return {"status": "stopped"}


class AtriMusicPlugin(PluginBase):
    plugin_id = "atri_music"
    plugin_version = "1.0.0"

    def __init__(
        self,
        *,
        player_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._player_factory = player_factory or AtriMusicPlayer
        self._player: Any | None = None
        self._library: AtriMusicLibrary | None = None
        self._default_song = "Dear Moments.mp3"

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        context: PluginContext,
    ) -> None:
        config = context.get_config()
        audio_dir = self._resolve_audio_dir(context, config.get("audio_dir", "audio"))
        audio_dir.mkdir(parents=True, exist_ok=True)
        self._library = AtriMusicLibrary(audio_dir)
        self._player = self._player_factory()
        self._default_song = str(config.get("default_song") or "Dear Moments.mp3").strip()
        self._register_tools(register)
        resources = getattr(getattr(context, "services", None), "resources", None)
        register_cleanup = getattr(resources, "register_cleanup", None)
        if callable(register_cleanup):
            register_cleanup(self.shutdown, label="atri-music", shutdown_order=650)

    def shutdown(self) -> None:
        player = self._player
        if player is not None:
            stop = getattr(player, "stop", None)
            if callable(stop):
                stop()

    def _register_tools(self, register: PluginCapabilityRegistry) -> None:
        register.register_tool(
            ToolContribution(
                name="atri_list_music",
                description="List ATRI music files available in the local music directory.",
                parameters=_object_schema({}, []),
                handler=lambda _args: {"tracks": self._require_library().list_tracks()},
                group="atri",
                risk="low",
            )
        )
        register.register_tool(
            ToolContribution(
                name="atri_play_music",
                description="Play one ATRI music file by filename.",
                parameters=_object_schema({"filename": {"type": "string"}}, ["filename"]),
                handler=self._play_music,
                group="atri",
                risk="low",
            )
        )
        register.register_tool(
            ToolContribution(
                name="atri_stop_music",
                description="Stop the current ATRI music playback.",
                parameters=_object_schema({}, []),
                handler=lambda _args: self._require_player().stop(),
                group="atri",
                risk="low",
            )
        )
        register.register_tool(
            ToolContribution(
                name="atri_sing",
                description="Let ATRI sing the configured default song, or the first available track.",
                parameters=_object_schema({}, []),
                handler=lambda _args: self._sing_default(),
                group="atri",
                risk="low",
            )
        )

    def _play_music(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._require_library().find(str(args.get("filename") or ""))
        return self._require_player().play(path)

    def _sing_default(self) -> dict[str, Any]:
        library = self._require_library()
        try:
            path = library.find(self._default_song)
        except (FileNotFoundError, ValueError):
            path = library.first_track()
            if path is None:
                raise FileNotFoundError("no ATRI music files found")
        return self._require_player().play(path)

    def _require_library(self) -> AtriMusicLibrary:
        if self._library is None:
            raise RuntimeError("ATRI music library is not initialized")
        return self._library

    def _require_player(self) -> Any:
        if self._player is None:
            raise RuntimeError("ATRI music player is not initialized")
        return self._player

    def _resolve_audio_dir(self, context: PluginContext, configured: Any) -> Path:
        text = str(configured or "audio").strip()
        candidate = Path(text)
        if candidate.is_absolute():
            return candidate
        try:
            return context.get_data_path(text)
        except Exception:
            return context.data_dir / "audio"


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
