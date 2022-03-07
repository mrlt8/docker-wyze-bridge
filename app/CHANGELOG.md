## Changes in v1.2.1

- 💥 Breaking: `MAX_NOREADY` and `MAX_BADRES` are being replaced with the time-based `RTSP_READTIMEOUT`.
- ✨ New: ENV option `CONNECT_TIMEOUT` - Force the stream to timeout and close if if can't connect to the cam. Potential fix for #306 and #211 where a stream would get stuck trying to connect until the bridge restarted.
- ✨ New: ENV option `NET_MODE_NAME` - camera-specific net mode filter #309.
- ✨ New: ENV option `FORCE_FPS_NAME` - camera-specific option to force the camera to use a different FPS. Can be used to correct slow/fast SD/cloud recordings.
- 🔨 Fixed: Auth issue when using WEBRTC.
- 🚧 Changed: Additional tweaks to prevent memory leaks.
- 🚧 Changed: Default `RTSP_READTIMEOUT` has been reduced to 20s.
- 🎨 Logging: Stream will now display the fps that the camera is using.

## Changes in v1.2.0

Improved video performance to help with the buffering/frame drops introduced in v.1.0.3. Thanks to @Ceer123 and everyone who helped identify and test the fixes!

Also in this release:

- 🔨 Fixed: logging and other issues related when stream stopped publishing to rtsp-simple-server.
- 🔨 Fixed: `AV_ER_REMOTE_TIMEOUT_DISCONNECT` error on connection timeout.
