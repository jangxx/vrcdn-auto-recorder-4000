from threading import Thread, Event
import logging
import time
import os
from datetime import datetime
import shutil

from pydantic import BaseModel
from pyrate_limiter import Limiter
import requests
import ffmpeg

from lib.plugin_runner import PluginRunner
from lib.stream_metadata import StreamMetadata
from plugins.plugin_base import Plugin

log = logging.getLogger(__file__)


class VRCDNRecorderOptions(BaseModel):
    username: str
    update_interval: int
    update_end_interval: int
    stream_end_timeout: int
    output_path: str


class VRCDNRecorder(Thread):
    _limiter: Limiter
    _opts: VRCDNRecorderOptions
    _plugins: list[Plugin]

    _recording_url: str
    _stop_event: Event
    _output_path: str

    def __init__(self, limiter: Limiter, opts: VRCDNRecorderOptions, plugins: list[Plugin]):
        super().__init__()

        self._limiter = limiter
        self._opts = opts
        self._plugins = plugins

        self._recording_url = f"https://stream.vrcdn.live/live/{opts.username}.live.ts"
        self._stop_event = Event()
        self._output_path = os.path.join(opts.output_path, opts.username)

        if not os.path.exists(self._output_path):
            os.makedirs(self._output_path, exist_ok=True)

    def stop(self):
        self._stop_event.set()

    def run(self):
        log.info(f"Watching user {self._opts.username}")

        last_check = 0

        finish_recording_paths = []
        finish_stream_metadata = None
        finish_encountered_error = None
        finish_deadline = None

        while not self._stop_event.is_set():
            now = time.time()

            # print("is_restarted", is_restarted, "next", _is_restarted, "since last check", now - last_check, self._opts.update_end_interval)

            # this is the loop iteration where we crossed the end timeout
            if finish_deadline is not None and finish_deadline <= now and finish_stream_metadata is not None:
                # concat all recorded files into a single .ts file

                if len(finish_recording_paths) > 0:
                    final_video_path = os.path.join(
                        self._output_path, f"{finish_stream_metadata.startedAt.strftime('%Y-%m-%d_%H_%M_%S')}.ts"
                    )
                    log.info(f"Concatenating {len(finish_recording_paths)} remuxed file(s) into {final_video_path}")

                    try:
                        with open(final_video_path, "wb") as output_file:
                            for rec in finish_recording_paths:
                                log.info(f"Writing {rec} into {final_video_path}")
                                with open(rec, "rb") as source:
                                    shutil.copyfileobj(source, output_file)
                                output_file.flush()

                        for rec in finish_recording_paths:
                            log.info(f"Deleting remuxed file {rec}")
                            os.unlink(rec)
                    except Exception as ex:
                        log.error(f"Error while concatenating final files {repr(ex)}")
                        finish_encountered_error = ex
                        final_video_path = None
                else:
                    log.error(f"No files to concatenate")
                    final_video_path = None

                    if finish_encountered_error is None:
                        finish_encountered_error = Exception("No recording files produced")

                if len(self._plugins) > 0:
                    runner = PluginRunner(
                        self._plugins,
                        "handle_recording_end",
                        [finish_stream_metadata, final_video_path],
                        {"error": finish_encountered_error, "finish": True},
                    )
                    runner.start()

                finish_recording_paths = []
                finish_stream_metadata = None
                finish_encountered_error = None
                finish_deadline = None

            check_interval = (
                self._opts.update_interval if finish_stream_metadata is None else self._opts.update_end_interval
            )

            if now - last_check >= check_interval:
                last_check = now

                while not self._limiter.try_acquire(timeout=0.5):
                    if self._stop_event.is_set():
                        return  # exit the thread

                encountered_error = None
                recording_path = None
                current_title = None
                recording_started = False

                stream_metadata = (
                    StreamMetadata(
                        username=self._opts.username,
                        startedAt=datetime.now(),
                        additionalData={},
                    )
                    if finish_stream_metadata is None
                    else finish_stream_metadata
                )

                try:
                    with requests.get(self._recording_url, stream=True, timeout=10) as resp:
                        if resp.status_code == 200:
                            if len(self._plugins) > 0:
                                runner = PluginRunner(
                                    self._plugins,
                                    "handle_recording_start",
                                    [stream_metadata],
                                    {"restart": finish_stream_metadata is not None},
                                )
                                runner.start()

                            current_title = f"{stream_metadata.startedAt.strftime('%Y-%m-%d_%H_%M_%S')}_{len(finish_recording_paths)}"
                            recording_path = os.path.join(self._output_path, current_title + "_rec.ts")

                            with open(recording_path, "wb") as output_file:
                                stream_iterator = resp.iter_content(chunk_size=1024 * 10)

                                recording_started = True
                                log.info(f"Started recording of VRCDN user {self._opts.username}")

                                while not self._stop_event.is_set():
                                    data = next(stream_iterator)

                                    output_file.write(data)
                        else:
                            log.debug(f"Stream {self._recording_url} returned status {resp.status_code}")

                except StopIteration:
                    log.debug(f"Stream {self._recording_url} stopped returning data")
                except requests.HTTPError as e:
                    log.error(f"Error while opening stream: {repr(e)}")
                    if e.response is not None:
                        log.error(f"Response body: {e.response.text}")
                    encountered_error = e
                except IOError as e:
                    print(e)
                    log.error(f"Error while starting recording: {repr(e)}")
                    encountered_error = e
                except Exception as e:
                    log.error(f"Error while recording: {repr(e)}")
                    encountered_error = e

                if (
                    recording_path is not None
                    and os.path.exists(recording_path)
                    and current_title is not None
                    and encountered_error is None
                ):
                    if os.path.getsize(recording_path) == 0:
                        os.unlink(recording_path)
                        recording_path = None
                        encountered_error = Exception("Recording was 0 bytes")
                    else:
                        # the recording was successful -> remux file into a new .ts file with a stable stream order

                        remux_path = os.path.join(self._output_path, current_title + "_remux.ts")

                        try:
                            inp_stream = ffmpeg.input(recording_path, fflags="+genpts")

                            # pick out the streams and ensure that stream 0 is always video and stream 1 is always audio
                            video = inp_stream["v:0"]
                            audio = inp_stream["a:0"]

                            out_stream = ffmpeg.output(
                                video,
                                audio,
                                remux_path,
                                **{
                                    "c": "copy",
                                    "bsf:v": "h264_mp4toannexb",
                                    "avoid_negative_ts": "make_zero",
                                },
                            )

                            print(" ".join(out_stream.compile()))

                            out_stream.run()

                            # delete the old unremuxed file after ffmpeg finished without throwing
                            os.unlink(recording_path)
                            recording_path = remux_path
                        except Exception as e:
                            log.error(f"Error while remuxing: {repr(e)}")
                            encountered_error = e

                if recording_started:
                    log.info(f"Stopped recording of VRCDN user {self._opts.username}")

                    now = time.time()

                    last_check = now

                    print("encountered error", encountered_error)

                    # store these for later when the stream end timeout is reached
                    if encountered_error is None:
                        finish_recording_paths.append(recording_path)

                    if finish_stream_metadata is None:
                        finish_stream_metadata = stream_metadata

                    finish_encountered_error = encountered_error
                    finish_deadline = now + self._opts.stream_end_timeout

                    if len(self._plugins) > 0:
                        runner = PluginRunner(
                            self._plugins,
                            "handle_recording_end",
                            [stream_metadata, recording_path],
                            {"error": encountered_error, "finish": False},
                        )
                        runner.start()

            time.sleep(1)
