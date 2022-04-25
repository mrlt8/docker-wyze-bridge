## Changes in v1.3.4/v1.3.5

### 🐛 v1.3.4 Bug

There was a bug in v1.3.4 that could cause the CPU to spike.
Please avoid v1.3.4 and upgrade to v1.3.5.

---

There is a known bug/issue with certain doorbells that drift out of sync due to the day/night fps change (#340).

Audio is also coming soon. Please check out the audio branch to report any issues.

### ✨ NEW

- ENV option: `IMG_TYPE` - Specify the snapshot image file type, e.g. `IMG_TYPE=png`
- ENV option: `SKIP_RTSP_LOG` - Prevent "read" spam in logs when using RTSP based snapshots.

### 🚧 Changed

- Fixed bug in `FILTER_MODELS` ENV that wouldn't match certain cameras (#346). Thanks @ragenhe!
- Fixed bug that could cause the stream to block when changing resolution/bitrate midstream (#340).
- Update rtsp-simple-server to v0.18.1.
- Improved speed of RTSP based snapshots!
- Force keyframes every two seconds on doorbell rotation.
- Limit doorbell bitrate to 3,000kb/s.
- MQTT related code refactoring and cleanup of unused topics.
- API: Wyze app version number bump to 2.30.0.

## Changes in v1.3.3

### ✨ NEW

- Livestreaming option now available. [Details](https://github.com/mrlt8/docker-wyze-bridge#livestream)

### 🚧 Changed

- Update FFmpeg to 5.0.
- Update rtsp-simple-server to v0.18.0.
- Tweaked doorbell rotation command for performance. #330
- HA: make `SNAPSHOT` optional and add `RTSP5`. #336
- Tweaked FFmpeg commands to use [tee muxer](https://ffmpeg.org/ffmpeg-formats.html#tee).
- API: iOS version bump to 15.4.1.
- API: Wyze app version number bump to 2.29.2.

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
