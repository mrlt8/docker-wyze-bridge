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