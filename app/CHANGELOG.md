# Changes in v0.7.2 ~ v0.7.5

- 🔨 Doorbell related changes: adjust HD frame size. Please post feedback [here](https://github.com/mrlt8/docker-wyze-bridge/issues/133)

# Changes in v0.7.1

- 🔨 Doorbell related changes - rotate other direction and set HD frame size.
- 🏠 Home Assistant: Add additional RTSP intervals.

# Changes in v0.7.0

- 💥 BREAKING: `API_THUMB` and `RTSP_THUMB` are now `SNAPSHOT=API` or `SNAPSHOT=RTSP` or `SNAPSHOT=RTSP30` for custom interval. [See Snapshot](https://github.com/mrlt8/docker-wyze-bridge#snapshotstill-images)
- 💥 BREAKING: `LAN_ONLY` is now `NET_MODE=LAN`. See [LAN Mode](https://github.com/mrlt8/docker-wyze-bridge#lan-mode)
- ✨ NEW: `NET_MODE=P2P` to block relay mode and stream from the camera using P2P mode for VPS/cloud and remote installs. [See P2P Mode](https://github.com/mrlt8/docker-wyze-bridge#p2p-mode)
- ✨ NEW: Basic MQTT support with discovery - publishes camera status, connections to camera, and snapshot if available [See MQTT](https://github.com/mrlt8/docker-wyze-bridge#mqtt-beta)
- ✨ NEW: `ROTATE_DOOR` will use ffmpeg to roate the Doorbell (WYZEDB3) stream. NOTE: this will re-encoding rather than copy h264 stream, which may require additional processing power.
- 🔀 Removed Supervisord
- 📦 Switch to static build of [ffmpeg-for-homebridge](https://github.com/homebridge/ffmpeg-for-homebridge)
- 🔨 Fixed broken rtsp auth
