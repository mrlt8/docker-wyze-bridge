# RTMP/RTSP/HLS Bridge for Wyze Cam

[![Docker](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/mrlt8/docker-wyze-bridge?logo=github)](https://github.com/mrlt8/docker-wyze-bridge/releases/latest)
[![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/mrlt8/wyze-bridge?sort=semver&logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)
[![Docker Pulls](https://img.shields.io/docker/pulls/mrlt8/wyze-bridge?logo=docker&logoColor=white)](https://hub.docker.com/r/mrlt8/wyze-bridge)
![GitHub Repo stars](https://img.shields.io/github/stars/mrlt8/docker-wyze-bridge?style=social)

Docker container to expose a local RTMP, RTSP, and HLS stream for all your Wyze cameras including v3. No third-party hacks or special firmware required.

See [https://github.com/mrlt8/docker-wyze-bridge](https://github.com/mrlt8/docker-wyze-bridge) for further details.

Please consider [supporting](https://ko-fi.com/mrlt8) this project if you found it useful.

## System Compatibility

![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-success.svg)
![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-success.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-success.svg)
[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant)

Should work on most x64 systems as well as on some arm-based systems like the Raspberry Pi.

## Supported Cameras

![Wyze Cam v1](https://img.shields.io/badge/wyze_v1-no-inactive.svg)
![Wyze Cam V2](https://img.shields.io/badge/wyze_v2-yes-success.svg)
![Wyze Cam V3](https://img.shields.io/badge/wyze_v3-yes-success.svg)
![Wyze Cam Pan](https://img.shields.io/badge/wyze_pan-yes-success.svg)
![Wyze Cam Doorbell](https://img.shields.io/badge/wyze_doorbell-yes-success.svg)
![Wyze Cam Outdoor](https://img.shields.io/badge/wyze_outdoor-yes-success.svg)

| Camera            | Model          | Supported |
| ----------------- | -------------- | --------- |
| Wyze Cam v1       | WYZEC1         | ❌         |
| Wyze Cam V2       | WYZEC1-JZ      | ✅         |
| Wyze Cam V3       | WYZE_CAKP2JFUS | ✅         |
| Wyze Cam Pan      | WYZECP1_JEF    | ✅         |
| Wyze Cam Outdoor  | WVOD1          | ✅         |
| Wyze Cam Doorbell | WYZEDB3        | ✅         |

---
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/J3J85TD3K)