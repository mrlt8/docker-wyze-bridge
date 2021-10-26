# RTMP/RTSP/HLS Bridge for Wyze Cam

[![Docker](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/mrlt8/docker-wyze-bridge?logo=github)](https://github.com/mrlt8/docker-wyze-bridge/releases/latest)
[![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/mrlt8/wyze-bridge?sort=semver&logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)
[![Docker Pulls](https://img.shields.io/docker/pulls/mrlt8/wyze-bridge?logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)

Docker container to expose a local RTMP, RTSP, and HLS stream for ALL your Wyze cameras including the outdoor and doorbell cams. No third-party or special firmware required.

It just works!

Based on [@noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) with [kroo/wyzecam](https://github.com/kroo/wyzecam) and [aler9/rtsp-simple-server](https://github.com/aler9/rtsp-simple-server).

Please consider [supporting](https://ko-fi.com/mrlt8) this project if you found it useful.

## Changes in v1.0.1

- 🏠 Home Assistant: Potential fix for DNS issue #107 - Thanks [@AlejandroRivera](https://github.com/mrlt8/docker-wyze-bridge/issues/107#issuecomment-950940320)!
- ➕ Added: Camera names for Pan V2 and Outdoor V2
- 🔧 Changed: Remove all special characters from URIs #189
- 🔧 Changed: fflags as potential fix for FFMPEG freezes #187- Thanks [@AdiAbuAli](https://github.com/mrlt8/docker-wyze-bridge/issues/187#issuecomment-951331290)

## Changes in v1.0.0

⚠️ May need to use `FRESH_DATA=true` on first run if upgrading from an exsisting installation.

- ✨ NEW: DTLS Firmware support - bridge should now work on cameras with the latest firmware
- ✨ NEW: Wyze Cam Outdoor (WVOD1) support

[View older changes](https://github.com/mrlt8/docker-wyze-bridge/releases)

## Supported Cameras

![Wyze Cam v1](https://img.shields.io/badge/wyze_v1-no-inactive.svg)
![Wyze Cam V2](https://img.shields.io/badge/wyze_v2-yes-success.svg)
![Wyze Cam V3](https://img.shields.io/badge/wyze_v3-yes-success.svg)
![Wyze Cam Pan](https://img.shields.io/badge/wyze_pan-yes-success.svg)
![Wyze Cam Doorbell](https://img.shields.io/badge/wyze_doorbell-yes-success.svg)
![Wyze Cam Outdoor](https://img.shields.io/badge/wyze_outdoor-yes-success.svg)

V1 is currently not supported due to lack of hardware for development.

| Camera              | Model          | Supported |
| ------------------- | -------------- | --------- |
| Wyze Cam v1         | WYZEC1         | ⚠️         |
| Wyze Cam V2         | WYZEC1-JZ      | ✅         |
| Wyze Cam V3         | WYZE_CAKP2JFUS | ✅         |
| Wyze Cam Pan        | WYZECP1_JEF    | ✅         |
| Wyze Cam Doorbell   | WYZEDB3        | ✅         |
| Wyze Cam Outdoor    | WVOD1          | ✅         |
| Wyze Cam Pan v2     | HL_PAN2        | ❓         |
| Wyze Cam Outdoor v2 | HL_WCO2        | ❓         |

### Firmware Compatibility

The bridge should be compatible with the latest official firmware from wyze.

Installing a firmware with DTLS enabled is **recommended** for secuirty purposes.

## Compatibility

![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-success.svg)
![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-success.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-success.svg)
[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
[![Portainer stack](https://img.shields.io/badge/portainer-stack-blue.svg?logo=portainer&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)

Should work on most x64 systems as well as on some arm-based systems like the Raspberry Pi.

The container can be run on its own, in [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer), or as a [Home Assistant Add-on](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant).

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmrlt8%2Fdocker-wyze-bridge)

## Basic Usage

### docker run

Use your Wyze credentials and run:

```bash
docker run -p 8888:8888 -e WYZE_EMAIL= -e WYZE_PASSWORD=  mrlt8/wyze-bridge:latest
```

This will start the bridge with the HLS ports open and you can view your stream by visiting: `http://localhost:8888/cam-nickname` where localhost is the hostname or ip of the machine running the bridge followed by the cam nickname in lowercase with `-` in place of spaces.

### docker-compose (recommended)

This is similar to the docker run command, but will save all your options in a yaml file.

1. [Download](https://raw.githubusercontent.com/mrlt8/docker-wyze-bridge/main/docker-compose.sample.yml) and rename or create a `docker-compose.yml` file
2. Edit `docker-compose.yml` with your wyze credentials
3. run `docker-compose up`

Once you're happy with your config you can use `docker-compose up -d` to run it in detached mode.

### 🏠 Home Assistant

Visit the [wiki page](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant) for additional information on Home Assistant.

### Additional Info

- [Two-Step Verification](#Multi-Factor-Authentication)
- [ARM/Raspberry Pi](#armraspberry-pi)
- [LAN mode](#LAN-Mode)
- [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)
- [Home Assistant](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
- [HomeKit Secure Video](https://github.com/mrlt8/docker-wyze-bridge/wiki/HomeKit-Secure-Video)

#### Audio Support

Audio is not supported at this time.

#### Special Characters

If your email or password contains a `%` or `$` character, you may need to escape them with an extra character. e.g., `pa$$word` should be entered as `pa$$$$word`

## Camera Stream URIs

By default, the bridge will create three streams for each of your cameras which can be acccessed at the following URIs, where `camera-nickname` is the name of the camera set in the Wyze app and converted to lower case with hyphens in place of spaces. e.g. 'Front Door' would be `/front-door`

Replace localhost with the hostname or ip of the machine running the bridge:

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

### Multi-Factor Authentication

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

- 🏠 Home Assistant:

  Add your code to the text file: `/config/wyze-bridge/mfa_token.txt`.

## ARM/Raspberry Pi

The default `docker-compose.yml` will pull a multi-arch image that has support for both amrv7 and arm64, and no changes are required to run the container as is.

### veth errors on ubuntu 21.10

If you're having trouble starting docker on a raspberry pi running ubuntu 21.10, you may need to run:

```bash
sudo apt install linux-modules-extra-raspi
```

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

If you would like to build the container from source, you will need to edit your `docker-compose.yml` to use the arm libraries by removing or commenting out the line `image: mrlt8/wyze-bridge:latest` and add or uncomment the following three lines:

```YAML
build:
    context: ./app
    dockerfile: Dockerfile.arm
```

## Advanced Options

**WYZE_EMAIL** and **WYZE_PASSWORD** are the only two required environment variables. The following envs are optional.

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

### Snapshot/Still Images

- `SNAPSHOT=API` Will run ONCE at startup and will grab a *high-quality* thumbnail from the wyze api and save it to `/img/cam-name.jpg` on docker installs or `/config/www/cam-name.jpg` in Home Assistant mode.

- `SNAPSHOT=RTSP` Will run every 180 seconds (configurable) and wll grab a new frame from the RTSP stream every iteration and save it to `/img/cam-name.jpg` on standard docker installs or `/config/www/cam-name.jpg` in Home Assistant mode. Can specify a custom interval with `SNAPSHOT=RTSP(INT)` e.g. `SNAPSHOT=RTSP30` to run every 30 seconds

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

```yaml
environment:
    - QUALITY=HD120
```

Additional info:

- Resolution can be set to `SD` (360p in the app) or `HD` - 640x360/1920x1080 for cams or 480x640/1296x1728 for doorbells.
- Bitrate can be set from 30 to 255. Some bitrates may not work with certain resolutions.
- Bitrate and resolution changes will apply to ALL cameras.
- Adjusting the bitrate and resolution in the bridge will also change the stream in the wyze app and vice versa.
- App equivalents would be:
  - 360p - SD30
  - SD - HD60
  - HD - HD120

### Custom FFmpeg Commands

You can pass a custom [command](https://ffmpeg.org/ffmpeg.html) to FFmpeg by using `FFMPEG_CMD` in your docker-compose.yml:

#### For all cameras

```YAML
environment:
    ..
    - FFMPEG_CMD=-f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/
```

#### For a specific camera

where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
- FFMPEG_CMD_CAM_NAME=ffmpeg -f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/
```

Additional info:

- The `ffmpeg` command is implied and is optional.
- The camera name will automatically be appended to the end of the command.

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

### rtsp-simple-server

[rtsp-simple-server](https://github.com/aler9/rtsp-simple-server/blob/main/rtsp-simple-server.yml) options can be customized as an environment variable in your docker-compose.yml by prefixing `RTSP_` to the UPPERCASE parameter.

e.g. use `- RTSP_RTSPADDRESS=:8555` to overwrite the default `rtspAddress`.

or `- RTSP_PATHS_ALL_READUSER=123` to customize a path specific option like `paths: all: readuser:123`

### Debugging options

environment options:

- `URI_SEPARATOR` (-|_|#) Customize the separator used to replace spaces in the URI; available values are `-`, `_`, or use `#` to remove spaces.

- `IGNORE_OFFLINE` (string/bool) Ignore ofline cameras until container restarts

- `OFFLINE_TIME` (int) Customize the sleep time when a camera is offline

- `DEBUG_FRAMES` (string/bool) Show all lost/incomplete frames

- `DEBUG_LEVEL` (debug|info|warning|error) Adjust the level of upstream logging

- `RTSP_LOGLEVEL` (debug|info|warn) Adjust the verbosity of rtsp-simple-server; available values are "warn", "info", "debug".

- `DEBUG_FFMPEG` (string/bool) Enable additional logging from FFmpeg

- `FRESH_DATA` (string/bool) Remove local cache and pull new data from wyze servers.
