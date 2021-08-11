# RTMP/RTSP/HLS Bridge for Wyze Cam

Docker container to expose a local RTMP, RTSP, and HLS stream for all your Wyze cameras including v3. No Third-party or special firmware required.

Based on [@noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) with [kroo/wyzecam](https://github.com/kroo/wyzecam), and [aler9/rtsp-simple-server](https://github.com/aler9/rtsp-simple-server).

### Compatibility:

Should work on most x64 systems as well as on some arm-based systems like the Raspberry Pi.

[See here](#armraspberry-pi-support) for instructions to run on arm.

Some reports of issues with v1 and WCO models that need further investigation.

## ⚠️ Latest Firmware Compatibility

Latest version of the Wyze firmware seems to cause connection issues which will result in the error:

```
IOTC_ER_CAN_NOT_FIND_DEVICE
```

## Changes in v0.5.5

- FIX: `invalid path name` for cameras with an apostrophe in the name

[View older changes](https://github.com/mrlt8/docker-wyze-bridge/releases)

## Usage

### docker run

Use your Wyze credentials and run:

```
docker run -p 1935:1935 -p 8554:8554 -p 8888:8888 -e WYZE_EMAIL= -e WYZE_PASSWORD=  mrlt8/wyze-bridge
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
- [ARM/Raspberry Pi](#armraspberry-pi-support)
- [LAN mode](#LAN-Mode)

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

#### Examples:

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

You can reverse any of these whitelists into blacklists by adding _block, blacklist, exclude, ignore, or reverse_ to `FILTER_MODE`.

```yaml
environment:
	..
    - FILTER_NAMES=Bedroom
    - FILTER_MODE=BLOCK
```

## Multi-Factor Authentication

Two-factor authentication ("Two-Step Verification" in the wyze app) is supported and will automatically be detected, however additional steps are required to enter your verification code.

- Echo the verification code directly to `/tokens/mfa_token`:

```bash
docker exec -it wyze-bridge sh -c 'echo "123456" > /tokens/mfa_token'
```

- Mount `/tokens/` locally and add your verification code to a new file `mfa_token`:

```YAML
volumes:
    - ./tokens:/tokens/
```

## ARM/Raspberry Pi Support

The default configuration will use the x64 tutk library, however, you can edit your `docker-compose.yml` to use the 32-bit arm library by setting `dockerfile` as `Dockerfile.arm`:

```YAML
    build:
        context: ./app
        dockerfile: Dockerfile.arm
    environment:
        ..
```

Alternatively, you can pull a pre-built image using:

```yaml
image: mrlt8/wyze-bridge:latest
environment: ..
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

## Bitrate and Resolution

Bitrate and resolution of the stream from the wyze camera can be adjusted with `- QUALITY=HD120`.

- Resolution can be set to `SD` (640x360 cams/480x640 doorbell) or `HD` (1920x1080 cam/1296x1728 doorbell). Default - HD.
- Bitrate can be set from 60 to 240 kb/s. Default - 120.
- Bitrate and resolution changes will apply to ALL cameras.

```yaml
environment:
	..
    - QUALITY=SD60
```

## Custom FFmpeg Commands

You can pass a custom [command](https://ffmpeg.org/ffmpeg.html) to FFmpeg by using `FFMPEG_CMD` in your docker-compose.yml:

### For all cameras:

```YAML
environment:
	..
    - FFMPEG_CMD=-f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/
```

### For a specific camera:

where `CAM_NAME` is the camera name in UPPERCASE and `_` in place of spaces and hyphens:

```yaml
- FFMPEG_CMD_CAM_NAME=ffmpeg -f h264 -i - -vcodec copy -f flv rtmp://rtsp-server:1935/
```

Additional info:

- The `ffmpeg` command is implied and is optional.
- The camera name will automatically be appended to the command, so you need to end with the rtmp/rtsp url.

## rtsp-simple-server

[rtsp-simple-server](https://github.com/aler9/rtsp-simple-server/blob/main/rtsp-simple-server.yml) options can be customized as an environment variable in your docker-compose.yml by prefixing `RTSP_` to the UPPERCASE parameter.

e.g. use `- RTSP_RTSPADDRESS=:8555` to overwrite the default `rtspAddress`.

or `- RTSP_PATHS_ALL_READUSER=123` to customize a path specific option like ` paths: all: readuser:123`

## Debugging options

environment options:

`- URI_SEPARATOR=` Customize the separator used to replace spaces in the URI; available values are `-`, `_`, or use `#` to remove spaces.

`- IGNORE_OFFLINE=true` Ignore ofline cameras until container restarts

`- DEBUG_LEVEL=` Adjust the level of upstream logging

`- RTSP_LOGLEVEL=` Adjust the verbosity of rtsp-simple-server; available values are "warn", "info", "debug".

`- DEBUG_FFMPEG=True` Enable additional logging from FFmpeg

`- FRESH_DATA=True` Remove local cache and pull new data from wyze servers.
