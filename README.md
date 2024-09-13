[![Docker](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/mrlt8/docker-wyze-bridge?logo=github)](https://github.com/mrlt8/docker-wyze-bridge/releases/latest)
[![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/mrlt8/wyze-bridge?sort=semver&logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)
[![Docker Pulls](https://img.shields.io/docker/pulls/mrlt8/wyze-bridge?logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)

# WebRTC/RTSP/RTMP/HLS Bridge for Wyze Cam

![479shots_so](https://user-images.githubusercontent.com/67088095/224595527-05242f98-c4ab-4295-b9f5-07051ced1008.png)


Create a local WebRTC, RTSP, RTMP, or HLS/Low-Latency HLS stream for most of your Wyze cameras including the outdoor, doorbell, and 2K cams. 

No modifications, third-party, or special firmware required.

It just works!

Streams direct from camera without additional bandwidth or subscriptions.

Please consider ⭐️ starring or [☕️ sponsoring](https://ko-fi.com/mrlt8) this project if you found it useful, or use the [affiliate link](https://amzn.to/3NLnbvt) when shopping on amazon!


> [!IMPORTANT]
> As of May 2024, you will need an API Key and API ID from: https://support.wyze.com/hc/en-us/articles/16129834216731.

> [!WARNING]
> Please double check your router/firewall and do NOT forward ports or enable DMZ access to the bridge unless you know what you are doing!


![Wyze Cam V1](https://img.shields.io/badge/wyze_v1-yes-success.svg)
![Wyze Cam V2](https://img.shields.io/badge/wyze_v2-yes-success.svg)
![Wyze Cam V3](https://img.shields.io/badge/wyze_v3-yes-success.svg)
![Wyze Cam V3 Pro](https://img.shields.io/badge/wyze_v3_pro-yes-success.svg)
![Wyze Cam V4](https://img.shields.io/badge/wyze_v4-yes-success.svg)
![Wyze Cam Floodlight](https://img.shields.io/badge/wyze_floodlight-yes-success.svg)
![Wyze Cam Floodlight V2](https://img.shields.io/badge/wyze_floodlight_v2-yes-success.svg)
![Wyze Cam Pan](https://img.shields.io/badge/wyze_pan-yes-success.svg)
![Wyze Cam Pan V2](https://img.shields.io/badge/wyze_pan_v2-yes-success.svg)
![Wyze Cam Pan V3](https://img.shields.io/badge/wyze_pan_v3-yes-success.svg)
![Wyze Cam Pan Pro](https://img.shields.io/badge/wyze_pan_pro-yes-success.svg)
![Wyze Cam Outdoor](https://img.shields.io/badge/wyze_outdoor-yes-success.svg)
![Wyze Cam Outdoor V2](https://img.shields.io/badge/wyze_outdoor_v2-yes-success.svg)
![Wyze Cam Doorbell](https://img.shields.io/badge/wyze_doorbell-yes-success.svg)
![Wyze Cam Doorbell V2](https://img.shields.io/badge/wyze_doorbell_v2-yes-success.svg)

See the [supported cameras](#supported-cameras) section for additional information.


## Quick Start

Install [docker](https://docs.docker.com/get-docker/) and run:

```bash
docker run -p 8554:8554 -p 8888:8888 -p 5050:5000 -e WB_AUTH=false mrlt8/wyze-bridge
```

You can then use the web interface at `http://localhost:5050` where `localhost` is the hostname or ip of the machine running the bridge.

See [basic usage](#basic-usage) for additional information or visit the [wiki page](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant) for additional information on using the bridge as a Home Assistant Add-on.

## What's Changed in v2.10.3

- FIX: Increased `MTX_WRITEQUEUESIZE` to prevent issues with higher bitrates.
- FIX: Restart RTMP livestream on fail (#1333)
- FIX: Restore user data on bridge restart (#1334)
- NEW: `SNAPSHOT_KEEP` Option to delete old snapshots when saving snapshots with a timelapse-like custom format with `SNAPSHOT_FORMAT`. (#1330)
  - Example for 3 min: `SNAPSHOT_KEEP=180`, `SNAPSHOT_KEEP=180s`, `SNAPSHOT_KEEP=3m`
  - Example for 3 days: `SNAPSHOT_KEEP=72h`, `SNAPSHOT_KEEP=3d`
  - Example for 3 weeks: `SNAPSHOT_KEEP=21d`, `SNAPSHOT_KEEP=3w`
- NEW: `RESTREAMIO` option for livestreaming via [restream.io](https://restream.io). (#1333)
  - Example `RESTREAMIO_FRONT_DOOR=re_My_Custom_Key123`

## What's Changed in v2.10.2

- FIX: day/night FPS slowdown for V4 cameras (#1287) Thanks @cdoolin and @Answer-1!
- NEW: Update battery level in WebUI

## What's Changed in v2.10.0/v2.10.1

FIXED: Could not disable `WB_AUTH` if `WB_API` is set. (#1304)

### WebUI Authentication

Simplify default credentials for the WebUI:

  - This will not affect users who are setting their own `WB_PASSWORD` and `WB_API`.
  - Default `WB_PASSWORD` will now be derived from the username part of the Wyze email address instead of using a randomly generated password.
    - Example: For the email address `john123@doe.com`, the `WB_PASSWORD` will be `john123`.
  - Default `WB_API` will be based on the wyze account for persistance.

### Stream Authentication

NEW: `STREAM_AUTH` option to specify multiple users and paths:

  - Username and password should be separated by a `:` 
  - An additional `:` can be used to specify the allowed IP address for the user. 
    - **This does NOT work with docker desktop**
    - Specify multiple IPs using a comma
  - Use the `@` to specify paths accessible to the user. 
    - Paths are optional for each user.  
    - Multiple paths can be specified by using a comma. If none are provided, the user will have access to all paths/streams 
  - Multiple users can be specified by using  `|` as a separator 

  **EXAMPLE**:

  ```
  STREAM_AUTH=user:pass@cam-1,other-cam|second-user:password@just-one-cam|user3:pass
  ```

  - `user:pass`  has access to `cam-1` and `other-cam`
  - `second-user:password` has access to `just-one-cam`
  - `user3:pass` has access to **all** paths/cameras

  See [Wiki](https://github.com/mrlt8/docker-wyze-bridge/wiki/Authentication#custom-stream-auth) for more information and examples.

### Recording via MediaMTX

Recoding streams has been updated to use MediaMTX with the option to delete older clips. 

Use `RECORD_ALL` or `RECORD_CAM_NAME` to enable recording.

- `RECORD_PATH` Available variables are `%path` or `{cam_name}`, `%Y` `%m` `%d` `%H` `%M` `%S` `%f` `%s` (time in strftime format).
- `RECORD_LENGTH` Length of each clip. Use `s` for seconds , `h` for hours. Defaults to `60s`
- `RECORD_KEEP` Delete older clips. Use `s` for seconds , `h` for hours. Set to 0s to disable automatic deletion. Defaults to `0s`

[View previous changes](https://github.com/mrlt8/docker-wyze-bridge/releases)

## FAQ

* How does this work?
  * It uses the same SDK as the app to communicate directly with the cameras. See [kroo/wyzecam](https://github.com/kroo/wyzecam) for details.
* Does it use internet bandwidth when streaming?
  * Not in most cases. The bridge will attempt to stream locally if possible but will fallback to streaming over the internet if you're trying to stream from a different location or from a shared camera. See the [wiki](https://github.com/mrlt8/docker-wyze-bridge/wiki/Network-Connection-Modes) for more details.
* Can this work offline/can I block all wyze services?
  * No. Streaming should continue to work without an active internet connection, but will probably stop working after some time as the cameras were not designed to be used without the cloud. Some camera commands also depend on the cloud and may not function without an active connection. See [wz_mini_hacks](https://github.com/gtxaspec/wz_mini_hacks/wiki/Configuration-File#self-hosted--isolated-mode) for firmware level modification to run the camera offline.
* Why aren't all wyze cams supported yet (OG/Doorbell Pro)?
  * These cameras are using a different SDK and will require a different method to connect and stream. See the awesome [cryze](https://github.com/carTloyal123/cryze) project by @carTloyal123.

## Compatibility

![Supports arm32v7 Architecture](https://img.shields.io/badge/arm32v7-yes-success.svg)
![Supports arm64v8 Architecture](https://img.shields.io/badge/arm64v8-yes-success.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-success.svg)
![Supports Apple Silicon Architecture](https://img.shields.io/badge/apple_silicon-yes-success.svg)

[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
[![Homebridge](https://img.shields.io/badge/homebridge-camera--ffmpeg-blue.svg?logo=homebridge&logoColor=white)](https://sunoo.github.io/homebridge-camera-ffmpeg/configs/WyzeCam.html)
[![Portainer stack](https://img.shields.io/badge/portainer-stack-blue.svg?logo=portainer&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)
[![Unraid Community App](https://img.shields.io/badge/unraid-community--app-blue.svg?logo=unraid&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/issues/236)

Should work on most x64 systems as well as on most modern arm-based systems like the Raspberry Pi 3/4/5 or Apple Silicon M1/M2/M3.

The container can be run on its own, in [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer), [Unraid](https://github.com/mrlt8/docker-wyze-bridge/issues/236), as a [Home Assistant Add-on](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant), locally or remotely in the cloud.



### Ubiquiti Unifi 

> [!NOTE]  
> Some network adjustments may be needed - see [this discussion](https://github.com/mrlt8/docker-wyze-bridge/discussions/891) for more information.

## Supported Cameras

> [!IMPORTANT]
> Some newer camera firmware versions may cause issues with remote access via P2P. Local "LAN" access seems unaffected at this time. A temporary solution is to use a VPN. See the [OpenVPN example](https://github.com/mrlt8/docker-wyze-bridge/blob/main/docker-compose.ovpn.yml).

| Camera                        | Model          | Tutk Support                                                 | Latest FW |
| ----------------------------- | -------------- | ------------------------------------------------------------ | --------- |
| Wyze Cam v1 [HD only]         | WYZEC1         | ✅                                                            | 3.9.4.x   |
| Wyze Cam V2                   | WYZEC1-JZ      | ✅                                                            | 4.9.9.x   |
| Wyze Cam V3                   | WYZE_CAKP2JFUS | ✅                                                            | 4.36.11.x |
| Wyze Cam V4 [2K]              | HL_CAM4        | ✅                                                            | 4.52.3.x  |
| Wyze Cam Floodlight           | WYZE_CAKP2JFUS | ✅                                                            | 4.36.11.x |
| Wyze Cam Floodlight V2 [2k]   | HL_CFL2        | ✅                                                            | 4.53.2.x  |
| Wyze Cam V3 Pro [2K]          | HL_CAM3P       | ✅                                                            | 4.58.11.x |
| Wyze Cam Pan                  | WYZECP1_JEF    | ✅                                                            | 4.10.9.x  |
| Wyze Cam Pan v2               | HL_PAN2        | ✅                                                            | 4.49.11.x |
| Wyze Cam Pan v3               | HL_PAN3        | ✅                                                            | 4.50.4.x  |
| Wyze Cam Pan Pro [2K]         | HL_PANP        | ✅                                                            | -         |
| Wyze Cam Outdoor              | WVOD1          | ✅                                                            | 4.17.4.x  |
| Wyze Cam Outdoor v2           | HL_WCO2        | ✅                                                            | 4.48.4.x  |
| Wyze Cam Doorbell             | WYZEDB3        | ✅                                                            | 4.25.1.x  |
| Wyze Cam Doorbell v2 [2K]     | HL_DB2         | ✅                                                            | 4.51.1.x  |
| Wyze Cam Doorbell Pro 2       | AN_RDB1        | ❓                                                            | -         |
| Wyze Battery Cam Pro          | AN_RSCW        | [⚠️](https://github.com/mrlt8/docker-wyze-bridge/issues/1011) | -         |
| Wyze Cam Flood Light Pro [2K] | LD_CFP         | [⚠️](https://github.com/mrlt8/docker-wyze-bridge/issues/822)  | -         |
| Wyze Cam Doorbell Pro         | GW_BE1         | [⚠️](https://github.com/mrlt8/docker-wyze-bridge/issues/276)  | -         |
| Wyze Cam OG                   | GW_GC1         | [⚠️](https://github.com/mrlt8/docker-wyze-bridge/issues/677)  | -         |
| Wyze Cam OG Telephoto 3x      | GW_GC2         | [⚠️](https://github.com/mrlt8/docker-wyze-bridge/issues/677)  | -         |

## Basic Usage

### docker-compose (recommended)

This is similar to the docker run command, but will save all your options in a yaml file.

1. Install [Docker Compose](https://docs.docker.com/compose/install/).
2. Use the [sample](https://raw.githubusercontent.com/mrlt8/docker-wyze-bridge/main/docker-compose.sample.yml) as a guide to create a `docker-compose.yml` file with your wyze credentials.
3. Run `docker-compose up`.

Once you're happy with your config you can use `docker-compose up -d` to run it in detached mode.

> [!CAUTION]
> If your credentials contain a `$` character, you need to escape it with another `$` sign (e.g., `pa$$word` > `pa$$$$word`) or leave your credentials blank and use the webUI to login.

> [!NOTE] 
> You may need to [update the WebUI links](https://github.com/mrlt8/docker-wyze-bridge/wiki/WebUI#custom-ports) if you're changing the ports or using a reverse proxy.


#### Updating your container

To update your container, `cd` into the directory where your `docker-compose.yml` is located and run:

```bash
docker-compose pull # Pull new image
docker-compose up -d # Restart container in detached mode
docker image prune # Remove old images
```

### 🏠 Home Assistant

Visit the [wiki page](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant) for additional information on Home Assistant.

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmrlt8%2Fdocker-wyze-bridge)


## Additional Info

* [Camera Commands (MQTT/REST API)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Commands)
* [Two-Factor Authentication (2FA/MFA)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Two-Factor-Authentication)
* [ARM/Apple Silicon/Raspberry Pi](https://github.com/mrlt8/docker-wyze-bridge/wiki/Raspberry-Pi-and-Apple-Silicon-(arm-arm64-m1-m2-m3))
* [Network Connection Modes](https://github.com/mrlt8/docker-wyze-bridge/wiki/Network-Connection-Modes)
* [Portainer](https://github.com/mrlt8/docker-wyze-bridge/wiki/Portainer)
* [Unraid](https://github.com/mrlt8/docker-wyze-bridge/issues/236)
* [Home Assistant](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)
* [Homebridge Camera FFmpeg](https://sunoo.github.io/homebridge-camera-ffmpeg/configs/WyzeCam.html)
* [HomeKit Secure Video](https://github.com/mrlt8/docker-wyze-bridge/wiki/HomeKit-Secure-Video)
* [WebUI API](https://github.com/mrlt8/docker-wyze-bridge/wiki/WebUI-API)


## Web-UI

The bridge features a basic Web-UI which can display a preview of all your cameras as well as direct links to all the video streams.

The web-ui can be accessed on the default port `5000`:

```text
http://localhost:5000/
```

See also: 
* [WebUI page](https://github.com/mrlt8/docker-wyze-bridge/wiki/WebUI)
* [WebUI API page](https://github.com/mrlt8/docker-wyze-bridge/wiki/WebUI-API)


## WebRTC

WebRTC should work automatically in Home Assistant mode, however, some additional configuration is required to get WebRTC working in the standard docker mode.

- WebRTC requires two additional ports to be configured in docker:
  ```yaml
    ports:
      ...
      - 8889:8889 #WebRTC
      - 8189:8189/udp # WebRTC/ICE
    ```

- In addition, the `WB_IP` env needs to be set with the IP address of the server running the bridge.
  ```yaml
    environment:
      - WB_IP=192.168.1.116
  ```
- See [documentation](https://github.com/aler9/rtsp-simple-server#usage-inside-a-container-or-behind-a-nat) for additional information/options.

## Advanced Options

All environment variables are optional.

* [Audio](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Audio)
* [Bitrate and Resolution](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Bitrate-and-Resolution)
* [Camera Substreams](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Substreams)
* [MQTT Configuration](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#mqtt-config)
* [Filtering Cameras](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Filtering)
* [Doorbell/Camera Rotation](https://github.com/mrlt8/docker-wyze-bridge/wiki/Doorbell-and-Camera-Rotation)
* [Custom FFmpeg Commands](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#custom-ffmpeg-commands)
* [Interval Snapshots](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#snapshotstill-images)
* [Stream Recording and Livestreaming](https://github.com/mrlt8/docker-wyze-bridge/wiki/Stream-Recording-and-Livestreaming)
* [rtsp-simple-server/MediaMTX Config](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#mediamtx)
* [Offline/IFTTT Webhook](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#offline-camera-ifttt-webhook)
* [Proxy Stream from RTSP Firmware](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#proxy-stream-from-rtsp-firmware)
* [BOA HTTP Server/Motion Alerts](https://github.com/mrlt8/docker-wyze-bridge/wiki/Boa-HTTP-Server)
* [Debugging Options](https://github.com/mrlt8/docker-wyze-bridge/wiki/Advanced-Option#debugging-options)

## Other Wyze Projects

Honorable Mentions:

* [@noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) - Original script that the bridge is bassd on.
* [kroo/wyzecam](https://github.com/kroo/wyzecam) - Original library that the bridge is based on.

Video Streaming:

* [gtxaspec/wz_mini_hacks](https://github.com/gtxaspec/wz_mini_hacks) - Firmware level modification for Ingenic based cameras with an RTSP server and [self-hosted mode](https://github.com/gtxaspec/wz_mini_hacks/wiki/Configuration-File#self-hosted--isolated-mode) to use the cameras without the wyze services.
* [thingino](https://github.com/themactep/thingino-firmware) - Advanced custom firmware for some Ingenic-based wyze cameras.
* [carTloyal123/cryze](https://github.com/carTloyal123/cryze) - Stream video from wyze cameras (Gwell cameras) that use the Iotvideo SDK from Tencent Cloud. 
* [xerootg/cryze_v2](https://github.com/xerootg/cryze_v2) - Stream video from wyze cameras (Gwell cameras) that use the Iotvideo SDK from Tencent Cloud. 
* [mnakada/atomcam_tools](https://github.com/mnakada/atomcam_tools) - Video streaming for Wyze v3.

General Wyze:

* [shauntarves/wyze-sdk](https://github.com/shauntarves/wyze-sdk) - python library to interact with wyze devices over the cloud.
