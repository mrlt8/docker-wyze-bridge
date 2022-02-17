## Changes in v1.1.1

- 🔨 Fixed: Refresh cams on `WRONG_AUTH_KEY` error. #292
- 🔨 Fixed: Faster cleanup on shutdown.
- 🔧 Changed: ENV option: `MAX_NOREADY` - Optional. Can now be set to 0 to disable. #221
- 🎨 Logging: Stream up info.

## Changes in v1.1.0

- 🏠 Home Assistant: Specify snapshot dir using `IMG_DIR`.
- ✨ NEW: ENV option `IMG_DIR` - Optional. Change snapshot dir.
- ✨ NEW: ENV option `MAX_NOREADY` - Optional. Number of "NOREADY" frames before restarting the connection.
- ✨ NEW: ENV option `MAX_BADRES` - Optional. Number of frames that have a wrong resolution before restarting the connection.
- ✨ NEW: ENV option `WEBRTC=True` - Optional. Get WebRTC credentials for all cameras.
- 🔨 Fixed: Change resolution without reconnecting.
- 🔨 Fixed: Refresh expired tokens.
- 🔨 Fixed: Refresh cams from API when unable to find device.
- 🔨 Fixed: Compatibility with rtsp-simple-server changes (PUBLISH to READY)
- 🔨 Fixed: Cleanup logging for reads and publish.
- 🔨 Fixed: Attempt to cleanup and exit more gracefully.
- ⬆️ UPDATE: Switched to Python 3.10 base image.
- ⬆️ UPDATE: iOS and Wyze App version for API.
- ⬆️ UPDATE: rtsp-simple-server to v0.17.17.
- 🧹Code refactoring and docstrings.
