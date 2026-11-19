# VRCDN Auto Recorder 4000
A better way to automatically record streams from [VRCDN](https://vrcdn.live) as they go live.

This is a sister project of the [Twitch Auto Recorder 3000](https://github.com/jangxx/twitch-auto-recorder-3000), focused entirely on VRCDN.
It's also designed to be nice to VRCDN's servers by reducing the number of connections as much as possible.

## Running in docker

The easiest way to run this script is by using docker:

```
docker run -v "./recordings:/data/recordings" -v "./config.yaml:/data/config.yaml" jangxx/vrcdn-auto-recorder-4000
```

This will put the recordings into a folder _./recordings_ and read the config from a file _config.yaml_, both in the current directory.
You can also add launch arguments after the image name:

```
docker run -v "./recordings:/data/recordings" jangxx/vrcdn-auto-recorder-4000 -s <vrcdn-stream>
```

The `<vrcdn-stream>` name can be taken from a VRCDN URL.
If you are streaming to `rtspt://stream.vrcdn.live/live/your-username`, you would use `your-username` for the parameter.

The available launch arguments and config file options are outlined below.

## Local installation

If you don't want to use Docker, you can also install the script locally into a virtualenv.

### Requirements

- Python 3.13 (might work on older versions, but hasn't been tested)
- `ffmpeg` _binary in PATH_
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation

Clone this repository and run the following command in its directory to create a virtualenv and install all dependencies:

```bash
uv sync
```

Afterwards you can run the script using:

```bash
uv run main.py
```

## Launch arguments & configuration file

`-h, --help`  
Show help message and exit.

`-V, --version`  
Show the version number and exit.

`-s <username>`  
**Required:** Add a VRCDN username to the list of watched streamers. Can be specified multiple times.

`-C <path>, --config <path>`  
**Optional:** Path to a config file in YAML format.

`-O <path>, --output-path <path>`  
**Optional:** Path where the recordings are stored (Default: ./recordings)

`--update-interval <seconds>`  
**Optional:** Update interval in seconds (Default: 120)

`--update-end-interval <seconds>`  
**Optional:** Update interval in seconds after a recording has stopped but before the stream is considered finished. This should be shorter than the normal interval, so that a stream which only dropped out briefly is picked up again quickly (Default: 10)

`--stream-end-timeout <seconds>`  
**Optional:** Time to wait after a recording ended before considering the stream as finished. If the stream comes back within this time, the new recording is treated as part of the same stream (Default: 0)

`--log <loglevel>`  
**Optional:** Sets the loglevel, one of CRITICAL, ERROR, WARNING, INFO, DEBUG (Default: INFO)

`--print-config`  
Print the config for debug purposes, to figure out if it got merged correctly.

Instead of supplying these values as command line arguments, you can also write a config file that contains all (or some) of them.
Options from the config file and the command line will be merged, with command line arguments taking precedence, so you can mix and match.

The config file uses this format:

```yaml
streamers:
    - <username1>
    - <username2>
plugins:
    plugin_name:
        option1: <value>
        option2: <value>
    # some plugins don't have configuration 
    # and just need an empty object here to be included
    plugin2_name: {} 
output_path: <path>
update_interval: <interval>
update_end_interval: <interval>
stream_end_timeout: <time>
```

Except for the plugin options, all configuration options can be set with command line arguments as well.

_Note:_ To avoid hammering VRCDN, requests are globally rate limited to at most one every 3 seconds across all watched streams.

## Plugins

Plugins can add some additional postprocessing to your recordings. A few plugins are included in the _plugins/_ directory, which also serve as examples on how to write your own.
Plugins can only be enabled through the config file.

`ffmpeg_remux`  
Automatically remuxes the finished .ts file into a .mp4 (with faststart for better streamability).
It has no config options, so it can be enabled by adding `ffmpeg_remux: {}` to the plugin section of the config file.  
_Note:_ The original .ts file is kept after remuxing.

`pushover`  
This plugin uses [pushover](https://pushover.net) to send notifications about your recordings to your phone.
```yaml
plugins:
    pushover:
        user_key: <user_key>
        api_token: <api_token>
```
You get your user key and an API token on the pushover website.

`discord_notifications`  
This plugin sends notifications about your recordings to a Discord channel by utilizing the [Webhooks](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) feature.
```yaml
plugins:
    discord_notifications:
        webhook: <webhook_url>
```
