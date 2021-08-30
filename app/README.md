# RTMP/RTSP/HLS Bridge for Wyze Cam

[![Docker](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/mrlt8/docker-wyze-bridge/actions/workflows/docker-image.yml) [![GitHub release (latest by date)](https://img.shields.io/github/v/release/mrlt8/docker-wyze-bridge?logo=github)](https://github.com/mrlt8/docker-wyze-bridge/releases/latest) [![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/mrlt8/wyze-bridge?sort=semver&logo=docker)](https://hub.docker.com/r/mrlt8/wyze-bridge) [![Docker Pulls](https://img.shields.io/docker/pulls/mrlt8/wyze-bridge?logo=docker)](https://hub.docker.com/r/mrlt8/wyze-bridge) ![GitHub Repo stars](https://img.shields.io/github/stars/mrlt8/docker-wyze-bridge?style=social)

Docker container to expose a local RTMP, RTSP, and HLS stream for all your Wyze cameras including v3. No Third-party or special firmware required.

## Compatibility

Should work on most x64 systems as well as on some arm-based systems like the Raspberry Pi.

Some reports of issues with v1 and WCO models that need further investigation.

### ⚠️ Firmware Compatibility

The bridge currently has issues connecting to cameras on newer firmware with DTLS enabled.

If you wish to continue using your camera with the bridge, you should downgrade or remain on a firmware without DTLS.

Visist [github](https://github.com/mrlt8/docker-wyze-bridge) for additional information.
