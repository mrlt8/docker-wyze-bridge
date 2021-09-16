# RTMP/RTSP/HLS Bridge for Wyze Cam

[![Docker](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/mrlt8/docker-wyze-bridge?logo=github)](https://github.com/mrlt8/docker-wyze-bridge/releases/latest)
[![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/mrlt8/wyze-bridge?sort=semver&logo=docker)](https://hub.docker.com/r/mrlt8/wyze-bridge)
[![Docker Pulls](https://img.shields.io/docker/pulls/mrlt8/wyze-bridge?logo=docker)](https://hub.docker.com/r/mrlt8/wyze-bridge)

Docker container to expose a local RTMP, RTSP, and HLS stream for all your Wyze cameras including v3. No Third-party or special firmware required.

Based on [@noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) with [kroo/wyzecam](https://github.com/kroo/wyzecam), and [aler9/rtsp-simple-server](https://github.com/aler9/rtsp-simple-server).

## Changes in v0.6.6

- 🐛 Potential fix for WYZEDB3

## Changes in v0.6.5

- 🔨 Always set default frame size and bitrate to prevent restart loop.

## Changes in v0.6.4

- 🐛 BUG: Fixed the issue introduced in v0.6.2 where a resolution change caused issues for RTMP and HLS streams. This will now raise an exception which *should* restart ffmpeg if the resolution doesn't match for more than 30 frames.

## Changes in v0.6.3

- 🐛 BUG: Fixed bug where cam on older firmware would not connect due to missing `wifidb`

## Changes in v0.6.2

- 🔨 FIX: Fixed an issue where chaning the resolution in the app would cause the stream to die. Could also potentially solve an issue with the doorbell.
- 🏠 FIX: Invalid boolean in config

## Changes in v0.6.1

- ✨ NEW: `RTSP_THUMB` ENV parameter to save images from RTSP stream ([details](#still-images))

## Changes in v0.6.0

- 💥 BREAKING: Renamed `FILTER_MODE` to `FILTER_BLOCK` and will be disabled if blank or set to false.
- 💥 BREAKING: Renamed `FILTER_MODEL` to `FILTER_MODELS`
- 🔨 Reworked auth, caching, and other other code refactoring
- ✨ NEW: Refresh token when token expires - no need to 2FA when your session expires!
- ✨ NEW: Use seed to generate TOTP
- ✨ NEW: `DEBUG_FRAMES` ENV parameter to show all dropped frames
- ⏪ CHANGE: Only show first lost/incomplete frame warning
- 🐧 CHANGE: Switch all base images to debian buster for consistency

[View older changes](https://github.com/mrlt8/docker-wyze-bridge/releases)

## Compatibility

![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-success.svg)
![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-success.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-success.svg)
[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
[![Portainer stack](https://img.shields.io/badge/portainer-stack-blue.svg?logo=portainer)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)

Should work on most x64 systems as well as on some arm-based systems like the Raspberry Pi.

The container can be run on its own or as a [Home Assistant Add-on](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant).

## Supported Cameras

![Wyze Cam v1](https://img.shields.io/badge/wyze_v1-no-inactive.svg)
![Wyze Cam V2](https://img.shields.io/badge/wyze_v2-<4.9.6.241-important.svg)
![Wyze Cam V3](https://img.shields.io/badge/wyze_v3-yes-success.svg)
![Wyze Cam Pan](https://img.shields.io/badge/wyze_pan-<4.10.6.241-important.svg)
![Wyze Cam Doorbell](https://img.shields.io/badge/wyze_doorbell-yes-success.svg)
![Wyze Cam Outdoor](https://img.shields.io/badge/wyze_outdoor-no-inactive.svg)

Some reports of issues with v1 and WCO models that need further investigation.

### Firmware Compatibility

The bridge currently has issues connecting to cameras on newer firmware with DTLS enabled.

If you wish to continue using your camera with the bridge, you should downgrade or remain on a firmware without DTLS:
| Camera | Latest Firmware w/o DTLS    |
| ------ | --------------------------- |
| V2     | 4.9.6.241 (March 9, 2021)   |
| V3     | 4.36.3.19 (August 26, 2021) |
| PAN    | 4.10.6.241 (March 9, 2021)  |

## Usage

### docker run

Use your Wyze credentials and run:

```bash
docker run -p 1935:1935 -p 8554:8554 -p 8888:8888 -e WYZE_EMAIL= -e WYZE_PASSWORD=  mrlt8/wyze-bridge:latest
```

or

### Build with docker-compose (recommended)

1. `git clone https://github.com/mrlt8/docker-wyze-bridge.git`
1. `cd docker-wyze-bridge`
1. `cp docker-compose.sample.yml docker-compose.yml`
1. Edit `docker-compose.yml` with your wyze credentials
1. run `docker-compose up --build`

### Additional Info

- [Two-Step Verification](#Multi-Factor-Authentication)
- [ARM/Raspberry Pi](#armraspberry-pi)
- [LAN mode](#LAN-Mode)
- [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)
- [Home Assistant](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)

Once you're happy with your config you can use `docker-compose up -d` to run it in detached mode.

## URIs

`camera-nickname` is the name of the camera set in the Wyze app and are converted to lower case with hyphens in place of spaces.

e.g. 'Front Door' would be `/front-door`

- RTMP:

  ```
  rtmp://localhost:1935/camera-nickname
  ```

- RTSP:

  ```
  rtsp://localhost:8554/camera-nickname
  ```

- HLS:

  ```
  http://localhost:8888/camera-nickname/stream.m3u8
  ```

- HLS can also be viewed in the browser using:

  ```
  http://localhost:8888/camera-nickname
  ```

## Filtering

The default option will automatically create a stream for all the cameras on your account, but you can use the following environment options in your `docker-compose.yml` to filter the cameras.

All options are cAsE-InSensiTive, and take single or multiple comma separated values.

### Examples

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
  - FILTER_MODEL=WYZEC1-JZ
  ```

- Whitelist by Camera Model Name:

  ```yaml
  - FILTER_MODEL=V2, v3, Pan
  ```

- Blacklisting:

  You can reverse any of these whitelists into blacklists by setting `FILTER_BLOCK`.

  ```yaml
  environment:
      ..
      - FILTER_NAMES=Bedroom
      - FILTER_BLOCK=true
  ```

## Multi-Factor Authentication

Two-factor authentication ("Two-Step Verification" in the wyze app) is supported and will automatically be detected, however additional steps are required to enter your verification code.

- Echo the verification code directly to `/tokens/mfa_token`:

  ```bash
  docker exec -it wyze-bridge sh -c 'echo "123456" > /tokens/mfa_token'
  ```

- Mount `/tokens/` locally and add your verification code to a file named `mfa_token`:

  ```YAML
  volumes:
      - ./tokens:/tokens/
  ```

- 🏠 Home Assistant:

  Add your code to the text file: `/config/wyze-bridge/mfa_token.txt`.

## ARM/Raspberry Pi

The default `docker-compose.yml` will pull a multi-arch image that has support for both amrv7 and arm64, and no changes are required to run the container as is.

### libseccomp2

arm/arm64 users on 32-bit Debian-based distros may experience errors such as `can't initialize time` which can be resolved by updating libseccomp2:

```bash
apt-get -y install libseccomp2/unstable
```

or

```bash
wget http://ftp.us.debian.org/debian/pool/main/libs/libseccomp/libseccomp2_2.5.1-1_armhf.deb
sudo dpkg -i libseccomp2_2.5.1-1_armhf.deb
```

### Build from source

If you would like to build the container from source, you will need to edit your `docker-compose.yml` to use the arm libraries. To do so, edit your `docker-compose.yml` and remove or comment out the line `image: mrlt8/wyze-bridge:latest` and add or uncomment the following three lines:

```YAML
build:
    context: ./app
    dockerfile: Dockerfile.arm
```

## LAN Mode

Like the wyze app, the tutk library will attempt to stream directly from the camera when on the same LAN as the camera in "LAN mode" or relay the stream via the cloud in "relay mode".

LAN mode is more ideal as all streaming will be local and won't use additional bandwidth.

You can restrict streaming to LAN only by adding the `LAN_ONLY` environment variable:

```yaml
environment:
    ..
    - LAN_ONLY=True
```

## Still Images

- `API_THUMB`: Will run ONCE at startup

  Enabling the `API_THUMB` ENV option will grab a *high-quality* thumbnail from the wyze api and save it to `/img/cam-name.jpg` on standard docker installs or `/config/www/cam-name.jpg` in Home Assistant mode.

- `RTSP_THUMB`: Will run every 180 seconds (configurable)

  Enabling the `RTSP_THUMB` ENV option will grab a frame from the RTSP stream every 180 seconds if the `RTSP_THUMB` value is not an integer and save it to `/img/cam-name.jpg` on standard docker installs or `/config/www/cam-name.jpg` in Home Assistant mode.

## Bitrate and Resolution

Bitrate and resolution of the stream from the wyze camera can be adjusted with:

```yaml
environment:
    ..
    - QUALITY=HD120
```

Additional info:

- Resolution can be set to `SD` (360p in the app) or `HD` - 640x360/1920x1080 for cams or 480x640/1296x1728 for doorbells.
- Bitrate can be set from 30 to 255. Some bitrates may not work with certain resolutions.
- Bitrate and resolution changes will apply to ALL cameras.
- App equivalents would be:
  - 360p - SD30
  - SD - HD60
  - HD - HD120

## Custom FFmpeg Commands

You can pass a custom [command](https://ffmpeg.org/ffmpeg.html) to FFmpeg by using `FFMPEG_CMD` in your docker-compose.yml:

### For all cameras

```YAML
environment:
    ..
    - FFMPEG_CMD=-f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/
```

### For a specific camera

where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
- FFMPEG_CMD_CAM_NAME=ffmpeg -f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/
```

Additional info:

- The `ffmpeg` command is implied and is optional.
- The camera name will automatically be appended to the end of the command.

## Custom FFmpeg Flags

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

## rtsp-simple-server

[rtsp-simple-server](https://github.com/aler9/rtsp-simple-server/blob/main/rtsp-simple-server.yml) options can be customized as an environment variable in your docker-compose.yml by prefixing `RTSP_` to the UPPERCASE parameter.

e.g. use `- RTSP_RTSPADDRESS=:8555` to overwrite the default `rtspAddress`.

or `- RTSP_PATHS_ALL_READUSER=123` to customize a path specific option like `paths: all: readuser:123`

## Debugging options

environment options:

`- URI_SEPARATOR=` Customize the separator used to replace spaces in the URI; available values are `-`, `_`, or use `#` to remove spaces.

`- IGNORE_OFFLINE=true` Ignore ofline cameras until container restarts

`- DEBUG_FRAMES` Show all lost/incomplete frames

`- DEBUG_LEVEL=` Adjust the level of upstream logging

`- RTSP_LOGLEVEL=` Adjust the verbosity of rtsp-simple-server; available values are "warn", "info", "debug".

`- DEBUG_FFMPEG=True` Enable additional logging from FFmpeg

`- FRESH_DATA=True` Remove local cache and pull new data from wyze servers.
