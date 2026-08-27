import requests
from pydantic import BaseModel

from .plugin_base import Plugin, StreamMetadata
from lib.stream_metadata import StreamMetadata


class PushoverPluginConfig(BaseModel):
    user_key: str
    api_token: str


class PushoverPlugin(Plugin):
    def __init__(self, config: PushoverPluginConfig):
        super().__init__(config)

    @staticmethod
    def create_config(raw_config: dict) -> PushoverPluginConfig:
        return PushoverPluginConfig(**raw_config)

    @staticmethod
    def get_name():
        return "Pushover-Notifications"

    def _send_message(self, message: str):
        requests.post(
            "https://api.pushover.net/1/messages.json",
            json={
                "token": self._config.api_token,
                "user": self._config.user_key,
                "message": message,
            },
        )

    def handle_recording_start(self, stream_metadata: StreamMetadata, restart=False):
        if not restart:
            self._send_message(f"Started recording of VRCDN user {stream_metadata.username}")
        else:
            self._send_message(f"Restarted recording of VRCDN user {stream_metadata.username}")

    def handle_recording_end(self, stream_metadata: StreamMetadata, output_path, error=None, finish=True):
        if finish and error is not None:
            self._send_message(f"Finished recording of VRCDN user {stream_metadata.username} with error: {repr(error)}")
        elif finish:
            self._send_message(f"Finished recording of VRCDN user {stream_metadata.username}")
        elif error is None:  # and not finish
            self._send_message(f"Stopped recording of VRCDN user {stream_metadata.username}")
        else:  # error is not None
            self._send_message(
                f"Encountered error while recording VRCDN user {stream_metadata.username}: {repr(error)}"
            )


PluginExport = PushoverPlugin
