# RTMP/RTSP/HLS Bridge for Wyze Cam

[![Docker](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/mrlt8/docker-wyze-bridge?logo=github)](https://github.com/mrlt8/docker-wyze-bridge/releases/latest)
[![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/mrlt8/wyze-bridge?sort=semver&logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)
[![Docker Pulls](https://img.shields.io/docker/pulls/mrlt8/wyze-bridge?logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)

Docker container to expose a local RTMP, RTSP, and HLS or Low-Latency HLS stream for ALL your Wyze cameras including the outdoor and doorbell cams. No third-party or special firmware required.

It just works!

Based on [@noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) with [kroo/wyzecam](https://github.com/kroo/wyzecam) and [aler9/rtsp-simple-server](https://github.com/aler9/rtsp-simple-server).

Please consider starring or [sponsoring](https://ko-fi.com/mrlt8) this project if you found it useful.

## Quick Start

Install [docker](https://docs.docker.com/get-docker/) and use your Wyze credentials to run:

```bash
docker run \
  -e WYZE_EMAIL=you@email.com \
  -e WYZE_PASSWORD=yourpassw0rd \
  -p 8888:8888 mrlt8/wyze-bridge:latest
```

You can view your stream by visiting: `http://localhost:8888/cam-nickname` where localhost is the hostname or ip of the machine running the bridge followed by the cam nickname in lowercase with `-` in place of spaces.

See [basic usage](#basic-usage) for additional information.

## Changes in v1.5.4

- Auto fetch camera data if upgrading from older version without having to use `FRESH_DATA`. #418
- Display DTLS on Wyze Cam Outdoors if base station has DTLS enabled.

## Changes in v1.5.3

~~⚠️ This version may require a one-time `FRESH_DATA` to generate the new authkey for compatibility with the WCO.~~

- **FIXED**: Authkey/DTLS - Wyze Cam Outdoor would timeout when connecting. #384

## Changes in v1.5.2

- **FIXED**: Setting the `WEBRTC` env to false would still pull the WebRTC credentials. #410

## Changes in v1.5.1

- **NEW**: ✨ Home Assistant: `RTSP_SIMPLE_SERVER` option to configure rtsp-simple-server, e.g. use `paths_all_readusers=123` for `paths: all: readuser:123`.
- **UPDATED**: ⬆️ rtsp-simple-server > [v0.19.1](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.19.1)

## Changes in v1.5.0

- **NEW**: ✨ ENV: `LLHLS=true` - Enable Low-Latency HLS and generate the certificates required.
- **NEW**: ✨ ENV: `ROTATE_CAM_{CAM_NAME}=True` or `ROTATE_CAM_{CAM_NAME}=(int)` to rotate any cam in any direction. #408
- **NEW**: ✨ Home Assistant: `CAM_OPTIONS` to allow for camera specific configs (AUDIO, FFMPEG, LIVESTREAM, NET_MODE, QUALITY, RECORD, ROTATE). #404
- **NEW**: ✨ Display a message if API rate limit has under 25 attempts left.

- **UPDATED**: ⬆️ API: iOS version bump to 15.5.
- **UPDATED**: ⬆️ API: Wyze app version number bump to 2.31.1.0.
- **UPDATED**: ⬆️ rtsp-simple-server > [v0.19.0](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.19.0)

[View previous changes](https://github.com/mrlt8/docker-wyze-bridge/releases)

## Features

- Access to video and audio for all Wyze-supported cameras via RTSP/RTMP/HLS/Low-Latency HLS.
- Access to HD *or* SD stream with configurable bitrate.
- Local and remote access to any of the cams on your account.
- Runs on almost any x64 or armv7/arm64 based system like a Raspberry Pi that supports docker.
- Support for Wyze 2FA.
- Ability to rotate video for Wyze Doorbell.
- Ability to record streams locally.
- Ability to take snapshots on an interval.
- Ability to live stream directly from the bridge.
- Ability to send a IFTTT webhook when a camera is offline (-90).

## Supported Cameras

![Wyze Cam V2](https://img.shields.io/badge/wyze_v2-yes-success.svg)
![Wyze Cam V3](https://img.shields.io/badge/wyze_v3-yes-success.svg)
![Wyze Cam Floodlight](https://img.shields.io/badge/wyze_floodlight-yes-success.svg)
![Wyze Cam Pan](https://img.shields.io/badge/wyze_pan-yes-success.svg)
![Wyze Cam Pan V2](https://img.shields.io/badge/wyze_pan_v2-yes-success.svg)
![Wyze Cam Outdoor](https://img.shields.io/badge/wyze_outdoor-yes-success.svg)
![Wyze Cam Outdoor V2](https://img.shields.io/badge/wyze_outdoor_v2-yes-success.svg)
![Wyze Cam Doorbell](https://img.shields.io/badge/wyze_doorbell-yes-success.svg)

![Wyze Cam v1](https://img.shields.io/badge/wyze_v1-no-inactive.svg)
![Wyze Cam Doorbell Pro](https://img.shields.io/badge/wyze_doorbell_pro-no-inactive.svg)

| Camera                | Model          | Supported |
| --------------------- | -------------- | --------- |
| Wyze Cam v1           | WYZEC1         | ⚠️         |
| Wyze Cam V2           | WYZEC1-JZ      | ✅         |
| Wyze Cam V3           | WYZE_CAKP2JFUS | ✅         |
| Wyze Cam Floodlight   | WYZE_CAKP2JFUS | ✅         |
| Wyze Cam Pan          | WYZECP1_JEF    | ✅         |
| Wyze Cam Pan v2       | HL_PAN2        | ✅         |
| Wyze Cam Outdoor      | WVOD1          | ✅         |
| Wyze Cam Outdoor v2   | HL_WCO2        | ✅         |
| Wyze Cam Doorbell     | WYZEDB3        | ✅         |
| Wyze Cam Doorbell Pro | GW_BE1         | ❓         |

### Firmware Compatibility

The bridge should be compatible with official firmware from wyze.

## Compatibility

![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-success.svg)
![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-success.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-success.svg)

[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
[![Homebridge](https://img.shields.io/badge/homebridge-camera--ffmpeg-blue.svg?logo=homebridge&logoColor=white)](https://sunoo.github.io/homebridge-camera-ffmpeg/configs/WyzeCam.html)
[![Portainer stack](https://img.shields.io/badge/portainer-stack-blue.svg?logo=portainer&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)
[![Unraid Community App](https://img.shields.io/badge/unraid-community--app-blue.svg?logo=unraid&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/issues/236)

Should work on most x64 systems as well as on some arm-based systems like the Raspberry Pi.

The container can be run on its own, in [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer), [Unraid](https://github.com/mrlt8/docker-wyze-bridge/issues/236), as a [Home Assistant Add-on](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant), locally or remotely in the cloud.

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmrlt8%2Fdocker-wyze-bridge)

## Basic Usage

### docker-compose (recommended)

This is similar to the docker run command, but will save all your options in a yaml file.

1. Install [Docker Compose](https://docs.docker.com/compose/install/).
2. Use the [sample](https://raw.githubusercontent.com/mrlt8/docker-wyze-bridge/main/docker-compose.sample.yml) as a guide to create a `docker-compose.yml` file with your wyze credentials.
3. Run `docker-compose up`.

Once you're happy with your config you can use `docker-compose up -d` to run it in detached mode.

#### Updating your container

To update your container, `cd` into the directory where your `docker-compose.yml` is located and run:

```bash
docker-compose pull # Pull new image
docker-compose up -d # Restart container in detached mode
docker image prune # Remove old images
```

### 🏠 Home Assistant

Visit the [wiki page](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant) for additional information on Home Assistant.

### Additional Info

- [Two-Step Verification](#Multi-Factor-Authentication)
- [ARM/Raspberry Pi](https://github.com/mrlt8/docker-wyze-bridge/wiki/Raspberry-Pi-(armv7-and-arm64))
- [LAN mode](#LAN-Mode)
- [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)
- [Unraid](https://github.com/mrlt8/docker-wyze-bridge/issues/236)
- [Home Assistant](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
- [Homebridge Camera FFmpeg](https://sunoo.github.io/homebridge-camera-ffmpeg/configs/WyzeCam.html)
- [HomeKit Secure Video](https://github.com/mrlt8/docker-wyze-bridge/wiki/HomeKit-Secure-Video)

#### Special Characters

If your email or password contains a `%` or `$` character, you may need to escape them with an extra character. e.g., `pa$$word` should be entered as `pa$$$$word`

#### Camera Stream URIs

By default, the bridge will create three streams for each of your cameras which can be accessed at the following URIs, where `camera-nickname` is the name of the camera set in the Wyze app and converted to lower case with hyphens in place of spaces. e.g. 'Front Door' would be `/front-door`

Replace localhost with the hostname or ip of the machine running the bridge:

- RTMP:

  ```text
  rtmp://localhost:1935/camera-nickname
  ```

- RTSP:

  ```text
  rtsp://localhost:8554/camera-nickname
  ```

- HLS:

  ```text
  http://localhost:8888/camera-nickname/stream.m3u8
  ```

- HLS can also be viewed in the browser using:

  ```text
  http://localhost:8888/camera-nickname
  ```

- Low-Latency HLS (enable with `LLHLS=true`):

  ```text
  https://localhost:8888/camera-nickname
  or
  https://localhost:8888/camera-nickname/stream.m3u8
  ```

#### Multi-Factor Authentication

Two-factor authentication ("Two-Step Verification" in the wyze app) is supported and will automatically be detected, however additional steps are required to enter your verification code.

- Echo the verification code directly to `/tokens/mfa_token` by opening a second terminal window and using:

  ```bash
  docker exec -it wyze-bridge sh -c 'echo "123456" > /tokens/mfa_token'
  ```

- Mount `/tokens/` locally and add your verification code to a file named `mfa_token`:

  ```YAML
  volumes:
      - ./tokens:/tokens/
  ```

- Generate Time-based One-Time Passwords:

  You can have the bridge auto generate and enter a Time-based One-Time Password (TOTP) by adding the secret key to the file `/tokens/totp` on standard installs or `/config/wyze-bridge/totp` for Home Assistant installs. You will need to create the file if it doesn't exist and mount it if necessary.

- 🏠 Home Assistant:

  Add your code to the text file: `/config/wyze-bridge/mfa_token.txt`.

- Portainer:
  
  Use the console to echo your code to the container:

  ```bash
  echo "123456" > /tokens/mfa_token
  ```

## Advanced Options

**WYZE_EMAIL** and **WYZE_PASSWORD** are the only two required environment variables.

**The following envs are all optional.**

### Audio

Audio is disabled by default and must be enabled in the ENV.

#### Enable audio

- For all cameras:

  ```YAML
  environment:
      ..
      - ENABLE_AUDIO=True
  ```

- For a specific camera:

  where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

  ```yaml
    - ENABLE_AUDIO_CAM_NAME=True
    - ENABLE_AUDIO_OTHER_CAM=True
  ```

  🏠 Home Assistant - Use `CAM_OPTIONS` and add a new entry for each camera:
  
  ```yaml
  - CAM_NAME: Cam Name
    AUDIO: true
  - CAM_NAME: other cam
    AUDIO: true
  ```

#### Audio output codec

By default, the bridge will attempt to copy the audio from the camera without re-encoding *unless* the camera is using a codec that isn't supported by RTSP, in which case the audio will be converted to AAC.

The `AUDIO_CODEC` ENV can be used should you need to re-encode the audio to another format for compatibility:

```yaml
  - AUDIO_CODEC=AAC
```

#### Audio filtering

Custom ffmpeg audio filters can be set with `AUDIO_FILTER`, but please note that audio filters will only be applied if re-encoding to another codec.

```yaml
  - AUDIO_FILTER=highpass=f=300,lowpass=f=2500,volume=volume=2
```

### Filtering

The default option will automatically create a stream for all the cameras on your account, but you can use the following environment options in your `docker-compose.yml` to filter the cameras.

All options are case-insensitivE, and take single or comma separated values.

#### Examples

- Whitelist by Camera Name (set in the wyze app):

  ```yaml
  environment:
      ..
      - FILTER_NAMES=Front Door, Driveway, porch cam
  ```

- Whitelist by Camera MAC Address:

  ```yaml
  - FILTER_MACS=00:aA:22:33:44:55, Aa22334455bB
  ```

- Whitelist by Camera Model:

  ```yaml
  - FILTER_MODELS=WYZEC1-JZ
  ```

- Whitelist by Camera Model Name:

  ```yaml
  - FILTER_MODELS=V2, v3, Pan
  ```

- Blacklisting:

  You can reverse any of these whitelists into blacklists by setting `FILTER_BLOCK`.

  ```yaml
  environment:
      ..
      - FILTER_NAMES=Bedroom
      - FILTER_BLOCK=true
  ```

### Network Connection Modes

Like the wyze app, the tutk library has three different modes to connect to the camera and will attempt to stream directly from the camera when on the same LAN as the camera in "LAN mode". If the camera is not available locally, it will either attempt to stream directly from your network using "P2P Mode" or relay the stream via the wyze servers (AWS) in "relay mode".

LAN mode is more ideal as all streaming will be local and won't use additional bandwidth.

#### LAN Mode

By default, the bridge will attempt to connect via "LAN Mode", but will fallback to other methods if LAN mode fails.
You can restrict streaming to LAN only by setting the `NET_MODE=LAN` environment variable:

```yaml
environment:
    ..
    - NET_MODE=LAN
```

#### P2P Mode

`NET_MODE=P2P` is ideal when running the bridge remotely on a different network or on a VPS and will allow the bridge to stream directly from the camera over the internet while blocking "Relay Mode".

#### ANY Mode

`NET_MODE=ANY` is the equivalent to leaving `NET_MODE` unset and will allow the connection to fallback to P2P or relay mode.

#### `NET_MODE` for a specific camera

In the event that you need to allow the bridge to access a select number of cameras outside of your LAN, you can specify them by appending the camera name to `NET_MODE`, where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
    ..
    - NET_MODE=LAN
    - NET_MODE_CAM_NAME=P2P
```

  🏠 Home Assistant - Use `CAM_OPTIONS` and add a new entry for each camera:
  
  ```yaml
  - CAM_NAME: Cam Name
    NET_MODE: P2P
  ```

### Snapshot/Still Images

- `SNAPSHOT=API` Will run ONCE at startup and will grab a *high-quality* thumbnail from the wyze api and save it to `/img/cam-name.jpg` on docker installs or `/config/www/cam-name.jpg` in Home Assistant mode.

- `SNAPSHOT=RTSP` Will run every 180 seconds (configurable) and wll grab a new frame from the RTSP stream every iteration and save it to `/img/cam-name.jpg` on standard docker installs or `/config/www/cam-name.jpg` in Home Assistant mode. Can specify a custom interval with `SNAPSHOT=RTSP(INT)` e.g. `SNAPSHOT=RTSP30` to run every 30 seconds

- `IMG_DIR=/img/` Specify the directory where the snapshots will be saved *within the container*. Use volumes in docker to map to an external directory.

- `IMG_TYPE` Specify the file type of the image, e.g. `IMG_TYPE=png`. Will default to jpg.

### Stream Recording

The bridge can be configured to record all or select camera streams to the container which can be mapped to a local directory.

#### Enable recording

```yaml
environment:
...
  - TZ=America/New_York
  - RECORD_ALL=True
volumes:
  - /local/path/:/record/
```

Or to specify select cameras, where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
  - RECORD_CAM_NAME=True
  - RECORD_OTHER_CAM=True
```

🏠 Home Assistant - Use `CAM_OPTIONS` and add a new entry for each camera:

```yaml
- CAM_NAME: Cam Name
  RECORD: true
- CAM_NAME: Other cam
  RECORD: true
```

See the [Stream Recording wiki page](https://github.com/mrlt8/docker-wyze-bridge/wiki/Stream-Recording#recording-configuration) page for additional options.

### Offline camera IFTTT webhook (BETA)

This option can send a trigger to [IFTTT's webhooks integration](https://ifttt.com/maker_webhooks) when the camera is detected as being offline (-90).

Note:This is still experimental as the connection will sometimes just timeout a number of times before going "offline".

```yaml
  - OFFLINE_IFTTT=MyEventName:my_IFTTT_Webhooks_Key
```

The bridge should then trigger your event with the following values:

```json
{
  "value1" : "cam-name", // camera name
  "value2" : -90, // error no
  "value3" : "IOTC_ER_DEVICE_OFFLINE" // error name
}
```

### Livestream

Basic livestream support is available for YouTube and Facebook, but you can also specify any custom rtmp server for other services like Twitch.

To use this feature, set a new env in your docker-compose.yml with the service (`YOUTUBE_` or `FACEBOOK_`) prefix followed by the camera name in UPPERCASE with `_` in place of spaces and hyphens, and set your stream key as the value. Custom rtmp servers can be specified using the `LIVESTREAM_` prefix:

```yaml
  - YOUTUBE_FRONT_DOOR=MY-STREAM-KEY
  - FACEBOOK_OTHER_CAM=MY-STREAM-KEY
  # twitch example:
  - LIVESTREAM_CAM_NAME=rtmp://jfk.contribute.live-video.net/app/MY-STREAM-KEY
```

🏠 Home Assistant - Use `CAM_OPTIONS` and add a new entry for each camera:

```yaml
- CAM_NAME: Cam Name
  LIVESTREAM: rtmp://jfk.contribute.live-video.net/app/MY-STREAM-KEY
- CAM_NAME: other cam
  LIVESTREAM: rtmp://a.rtmp.youtube.com/live2/my-youtube-key
```

### MQTT (beta)

Some basic MQTT support is now available in v0.7.0.

MQTT auth and discovery should be automatic in Home Assistant mode - can be disabled by setting `MQTT_HOST` to False.

| ENV Name    | Description                                   | Example             |
| ----------- | --------------------------------------------- | ------------------- |
| MQTT_HOST   | IP/Hostname AND Port of the MQTT broker       | core-mosquitto:1883 |
| MQTT_AUTH   | Username AND password; leave blank if none    | user:pass           |
| MQTT_TOPIC  | Optional - Specify topic prefix               | myhome              |
| MQTT_DTOPIC | Optional - Discovery topic for home assistant | homeassistant       |

### Bitrate and Resolution

Bitrate and resolution of the stream from the wyze camera can be adjusted with:

#### Set quality for all cameras

```yaml
environment:
    - QUALITY=HD120
```

#### Set quality for single camera

where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
environment:
    - QUALITY_CAM_NAME=HD120
```

Additional info:

- Resolution can be set to `SD` (360p in the app) or `HD` - 640x360/1920x1080 for cams or 480x640/1296x1728 for doorbells.
- Bitrate can be set from 30 to 255. Some bitrates may not work with certain resolutions.
- Adjusting the bitrate and resolution in the bridge will also change the stream in the wyze app and vice versa.
- App equivalents would be:
  - 360p - SD30
  - SD - HD60 (HD120 for doorbell)
  - HD - HD120 (HD180 for doorbell)

### Custom FFmpeg Commands

You can pass a custom [command](https://ffmpeg.org/ffmpeg.html) to FFmpeg by using `FFMPEG_CMD` in your docker-compose.yml:

#### For all cameras

```YAML
environment:
    ..
    - FFMPEG_CMD=-f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/{cam_name}
```

#### For a specific camera

where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
- FFMPEG_CMD_CAM_NAME=ffmpeg -f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/{cam_name}
```

🏠 Home Assistant - Use `CAM_OPTIONS` and add a new entry for each camera:

```yaml
- CAM_NAME: Cam Name
  FFMPEG: ffmpeg -f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/{cam_name}
```

Additional info:

- The `ffmpeg` command is implied and is optional.
- The camera name is available as a variable `{cam_name}` for lowercase and `{CAM_NAME}` for uppercase.
- The audio pipe and format are available as the variable `{audio_in}`.

### Custom FFmpeg Flags

Custom ffmpeg flags can easily be tested with:

```YAML
environment:
    ..
    - FFMPEG_FLAGS=-fflags +flush_packets+genpts+discardcorrupt+nobuffer
```

or where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
- FFMPEG_FLAGS_CAM_NAME=-flags low_delay
```

### Rotate Video

- Rotate all doorbells:

  ```YAML
  environment:
      ..
      - ROTATE_DOOR=True
  ```

- Rotate other cameras 
  where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

  Rotate by 90 degrees clockwise:

  ```YAML
  environment:
      ..
      - ROTATE_CAM_CAM_NAME=True
  ```

  Rotate video in other directions:

  ```YAML
      - ROTATE_CAM_OTHER_CAM=1 # 90 degrees clockwise.
      - ROTATE_CAM_THIRD_CAM=2 # 90 degrees counter-clockwise.
  ```

 Available options:
  `0` - Rotate by 90 degrees counter-clockwise and flip vertically. This is the default.
  `1` - Rotate by 90 degrees clockwise.
  `2` - Rotate by 90 degrees counter-clockwise.
  `3` - Rotate by 90 degrees clockwise and flip vertically.

### rtsp-simple-server

[rtsp-simple-server](https://github.com/aler9/rtsp-simple-server/blob/main/rtsp-simple-server.yml) options can be customized as an environment variable in your docker-compose.yml by prefixing `RTSP_` to the UPPERCASE parameter.

e.g. use `- RTSP_RTSPADDRESS=:8555` to overwrite the default `rtspAddress`.

or `- RTSP_PATHS_ALL_READUSER=123` to customize a path specific option like `paths: all: readuser:123`

For camera specific options with spaces in the name of the camera (e.g. `Front Door`), be sure to replace the spaces with the `URI_SEPARATOR` which defaults to `-`.  So `Front Door` would be represented as `FRONT-DOOR`, and `paths: Front Door: runOnReady: ffmpeg...` could be set in your docker-compose as:

```yaml
environment:
  ...
  - RTSP_PATHS_FRONT-DOOR_RUNONREADY=ffmpeg...
```

- 🏠 For Home Assistant:
  Enter each customization into `RTSP_SIMPLE_SERVER`, e.g. use `paths_all_readusers=123` for `paths: all: readuser:123`.

### Debugging options

environment options:

- `FRESH_DATA` (bool) Remove local cache and pull new data from wyze servers.

- `URI_SEPARATOR` (-|_|#) Customize the separator used to replace spaces in the URI; available values are `-`, `_`, or use `#` to remove spaces.

- `CONNECT_TIMEOUT` (int) Adjust the number of seconds to wait before timing out when connecting to camera. Default: `15`

- `KEEP_BAD_FRAMES` (bool) Keep frames that may be missing a keyframe or preceding frames.

- `IGNORE_OFFLINE` (bool) Ignore offline cameras until container restarts.

- `OFFLINE_TIME` (int) Customize the sleep time when a camera is offline. Default: `10`

- `DEBUG_FRAMES` (bool) Show all lost/incomplete frames.

- `DEBUG_LEVEL` (debug|info|warning|error) Adjust the level of upstream logging.

- `RTSP_READTIMEOUT` (str) Adjust the max number of seconds of missing frames allowed before a stream is restarted. Be sure to include the s after the number. Default: `20s`

- `RTSP_LOGLEVEL` (debug|info|warn) Adjust the verbosity of rtsp-simple-server; available values are "warn", "info", "debug".

- `SKIP_RTSP_LOG` (bool) Prevent "read" spam in the logs when using RTSP based snapshots. Works by only logginng clients that stay connected for longer than 3s.

- `DEBUG_FFMPEG` (bool) Enable additional logging from FFmpeg.

- `FORCE_FPS_CAM_NAME` (int) Force a specific camera to use a different FPS, where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens.

- `FPS_FIX` (bool) Set camera parameter to match the actual FPS being sent by the camera. Potential fix slow/fast SD card and cloud recordings.

- `WEBRTC` (bool) Display WebRTC credentials for cameras.
