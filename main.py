import argparse
import os
import logging
import importlib
import sys
import json
import threading
from typing import Any, Type, cast
import signal

from pydantic import ValidationError
import yaml
from pyrate_limiter import Duration, limiter_factory

from lib.vrcdn_recorder import VRCDNRecorder, VRCDNRecorderOptions
from plugins.plugin_base import Plugin
from lib.config import Config, ConfigMerger, DefaultConfigDict, non_empty_dict_or_none

from _version import __version__

parser = argparse.ArgumentParser(description="A tool to automatically records streams from VRCDN as streamers go live")
parser.add_argument(
    "-O",
    "--output-path",
    metavar="path",
    dest="output_path",
    help="Path where the recordings are stored (Default: ./recordings)",
)
parser.add_argument(
    "-s",
    metavar="username",
    dest="watched_accounts",
    help="Add a username to the list of watched streamers.",
    action="append",
    default=[],
)
parser.add_argument(
    "--update-interval",
    metavar="seconds",
    dest="update_interval",
    help="Update interval in seconds (Default: 120)",
    type=int,
)
parser.add_argument(
    "--update-end-interval",
    metavar="seconds",
    dest="update_end_interval",
    help="Update interval in seconds after a recording has stopped but before it is finished (Default: 10)",
    type=int,
)
parser.add_argument(
    "--stream-end-timeout",
    metavar="seconds",
    dest="stream_end_timeout",
    help="Time to wait after a recording ended before considering the stream as finished (Default: 0)",
    type=int,
)
parser.add_argument(
    "--log",
    metavar="loglevel",
    dest="loglevel",
    help="Sets the loglevel, one of CRITICAL, ERROR, WARNING, INFO, DEBUG (Default: INFO)",
    default="INFO",
)
parser.add_argument(
    "-C", "--config", metavar="path", dest="config_file_path", help="Optional path to a config file in YAML format"
)
parser.add_argument(
    "--print-config", dest="print_config", action="store_true", help="Print the config for debug purposes"
)
parser.add_argument("-V", "--version", action="version", version=__version__)

args = parser.parse_args()
config_dict: dict = DefaultConfigDict

# merge config file
if args.config_file_path is not None:
    with open(args.config_file_path, "r") as config_file:
        config_file_content = yaml.load(config_file, yaml.Loader)

    if config_file_content is not None:  # don't raise an error when the config file is empty
        config_dict = ConfigMerger.merge(config_dict, dict(config_file_content))

# merge command line options
config_dict = ConfigMerger.merge(
    config_dict,
    {
        "streamers": args.watched_accounts,
        "output_path": args.output_path,
        "update_interval": args.update_interval,
        "update_end_interval": args.update_end_interval,
        "stream_end_timeout": args.stream_end_timeout,
    },
)

if args.print_config:
    print(json.dumps(config_dict, indent=4))

try:
    config = Config(**config_dict)
except ValidationError as err:
    print(err)
    sys.exit(1)

if args.print_config:
    sys.exit(0)

logging.basicConfig(
    level=args.loglevel, format="[%(levelname)s] %(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__file__)

charset_normalizer_logger = logging.getLogger("charset_normalizer")
charset_normalizer_logger.setLevel(logging.CRITICAL)

# this is a hardcoded limit. we only hit VRCDN _at most_ once every 3 seconds across all recorders
global_limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=1, duration=3 * Duration.SECOND)

shutdown_event = threading.Event()


def _request_shutdown(signum, frame):
    log.info("Shutdown requested, stopping recorders...")
    shutdown_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    if not os.path.exists(config.output_path):
        log.info(f"Output path {config.output_path} doesn't exist, creating it now...")
        os.makedirs(config.output_path, exist_ok=True)

    # list of tuples (class, config)
    plugins: list[tuple[Type[Plugin], Any]] = []

    for plugin_name, plugin_config_dict in config.plugins.items():
        plugin = importlib.import_module(f"plugins.{plugin_name}").PluginExport
        plugin_class = cast(type[Plugin], plugin)

        try:
            plugin_config = plugin_class.create_config(plugin_config_dict)
        except ValidationError as err:
            print(err)
            sys.exit(1)

        plugins.append((plugin_class, plugin_config))

    for p in plugins:
        log.info(f"Loaded plugin {p[0].get_name()}")

    recorders = [
        VRCDNRecorder(
            global_limiter,
            VRCDNRecorderOptions(
                username=username,
                update_interval=config.update_interval,
                update_end_interval=config.update_end_interval,
                stream_end_timeout=config.stream_end_timeout,
                output_path=config.output_path,
            ),
            [p(c) for p, c in plugins],
        )
        for username in config.streamers
    ]

    for rec in recorders:
        rec.start()

    while not shutdown_event.is_set():
        shutdown_event.wait(1)

    for rec in recorders:
        rec.stop()

    for rec in recorders:
        rec.join()
