## Changes in v1.2.0

Improved video performance to help with the buffering/frame drops introduced in v.1.0.3. Thanks to @Ceer123 everyone who helped identify and test the fixes!

Also in this release:

- 🔨 Fixed: logging and other issues related when stream stopped publishing to rtsp-simple-server.
- 🔨 Fixed: `AV_ER_REMOTE_TIMEOUT_DISCONNECT` error on connection timeout.

## Changes in v1.1.2

- 🏠 Home Assistant: Create the IMG_DIR at startup if it does not exist.
- 🏠 Home Assistant: Added `KEEP_BAD_FRAMES`, `MAX_NOREADY`, `MAX_BADRES`, and `WEBRTC` options.
- ✨ NEW: ENV option `KEEP_BAD_FRAMES` - Optional. Keep frames that may be missing a keyframe. May cause some video artifacts.
- 🔨 Fixed: Get API snapshots one time at container startup to avoid expired thumbnails.
- 🧹Code refactoring.

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
