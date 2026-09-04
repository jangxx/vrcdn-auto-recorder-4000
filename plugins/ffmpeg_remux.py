import re
import logging

from .plugin_base import Plugin

import ffmpeg

log = logging.getLogger(__file__)


class FFmpegRemuxPlugin(Plugin):
    def __init__(self, config):
        super().__init__(config)

    @staticmethod
    def get_name():
        return "FFmpeg-Remux"

    def handle_recording_end(self, stream_metadata, output_path, error=None, finish=True):
        if error is None and finish:
            mp4_filename = re.sub(r"\.ts$", ".mp4", output_path)

            stream = ffmpeg.input(output_path, fflags="+genpts", analyzeduration="100M", probesize="100M").output(
                mp4_filename, codec="copy", movflags="faststart"
            )

            log.info("Running: " + " ".join(stream.compile()))

            stream.run()


PluginExport = FFmpegRemuxPlugin
