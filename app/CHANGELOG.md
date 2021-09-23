## Changes in v0.6.8

- 🔨 Doorbell (WYZEDB3) related changes. Please post feedback [here #133](https://github.com/mrlt8/docker-wyze-bridge/issues/133)
- ✨ New: `OFFLINE_TIME` env option to specify the time before retrying to connect to a camera that is offline [#143](https://github.com/mrlt8/docker-wyze-bridge/issues/143).

## Changes in v0.6.7

- 🔨 FIX: Set default frame size for WYZEDB3

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

- ✨ NEW: `RTSP_THUMB` ENV parameter to save images from RTSP stream 

## Changes in v0.6.0

- 💥 BREAKING: Renamed `FILTER_MODE` to `FILTER_BLOCK` and will be disabled if blank or set to false.
- 💥 BREAKING: Renamed `FILTER_MODEL` to `FILTER_MODELS`
- 🔨 Reworked auth and caching and other other code refactoring
- ✨ NEW: Use refresh token when token expires - no need to 2FA when your session expires!
- ✨ NEW: Use seed to generate TOTP
- ✨ NEW: `DEBUG_FRAMES` ENV parameter to show all dropped frames
- ⏪ CHANGE: Only show first lost/incomplete frame warning
- 🐧 CHANGE: Switch all base images to debian buster for consistency