## Changes in v1.3.2

⚠️ Potentially breaking for custom FFMPEG commands.

- Fixed custom ffmpeg ENV for camera names with spaces. #332
- Camera name variable for custom ffmpeg commands with `{cam_name}` for lowercase and `{CAM_NAME}` for uppercase. #334
- Camera name variable for `RECORD_FILE_NAME` and `RECORD_PATH` with `{cam_name}` for lowercase and `{CAM_NAME}` for uppercase.
- Changed default `RECORD_PATH` to `/record/{CAM_NAME}` and to `/media/wyze/{CAM_NAME}` for Home Assistant.
  
## Changes in v1.3.1

### 🚧 Changed

- Adjusted sleep time between frames that could cause the stream to fall behind. (#330) Thanks @bbobrian, @dreondre, and everyone who helped with reporting and testing!
- Additional FFMPEG commands to help reduce lag.
- Fixed spaces in ENV/YAML so that they use `_` instead of `-`. Thanks @ronald-mendoza!
- Updated typos in README. Thanks @ronald-mendoza! (#332)
- Wyze app version number bump (2.29.1).


## Changes in v1.3.0

### ✨ NEW

- Recording directly in the bridge is now here! [Details](#recording-streams-beta).
  
  🏠 Default settings will save recordings to `/media/wyze/` in Home Assistant mode.

### 🚧 Changed

- Adjusted connection timeout #306 #319.
- Check bitrate every 500 frames to detect any external changes #320.
- Correct mismatched FPS camera parameter with ENV: `FPS_FIX`.
- Add sleep between frames to lower CPU usage.
- Fixed import error #324.
- IOS and wyze app version number bump.

## Changes in v1.2.2

- Potential fix for memory leak and connection issues when connecting to a camera #306 #319 #323.
- 🏠 HA: `RTSP_READTIMEOUT` is now optional and will use the standard default of `20s`.

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
