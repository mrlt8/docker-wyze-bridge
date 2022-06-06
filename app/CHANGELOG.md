## Changes in v1.5.0

- **NEW**: ✨ ENV: `LLHLS=true` - Enable Low-Latency HLS and generate the certificates required.
- **NEW**: ✨ ENV: `ROTATE_CAM_{CAM_NAME}=True` or `ROTATE_CAM_{CAM_NAME}=(int)` to rotate any cam in any direction. #408
- **NEW**: ✨ Home Assistant: `CAM_OPTIONS` to allow for camera specific configs (AUDIO, FFMPEG, LIVESTREAM, NET_MODE, QUALITY, RECORD, ROTATE). #404
- **NEW**: ✨ Display a message if API rate limit has under 25 attempts left.

- **UPDATED**: ⬆️ API: iOS version bump to 15.5.
- **UPDATED**: ⬆️ API: Wyze app version number bump to 2.31.1.0.
- **UPDATED**: ⬆️ rtsp-simple-server > [v0.19.0](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.19.0)

## Changes in v1.4.5

- **FIXED**: 🔧 Unknown audio codec (codec_id=137) on Wyze Pan set to mulaw. (#385) Thanks @mjb83!

- **UPDATED**: ⬆️ API: Wyze app version number bump to 2.31.0.7.
- **UPDATED**: ⬆️ rtsp-simple-server > [v0.18.4](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.18.4)

## Changes in v1.4.4

- **CHANGED**: 🚧 MQTT now reports camera `state` as "online", "offline", "disconnected", or the connection error.
- **CHANGED**: 🚧 MQTT now displays camera `net_mode`, `wifi`, and `audio`.

- **UPDATED**: ⬆️ rtsp-simple-server > [v0.18.3](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.18.3)

## Changes in v1.4.2/3

- **FIXED**: 🔧 Bug in v1.4.2 if MQTT was enabled in home assistant. (#375) Thanks @JochenKlenk!

- **NEW**: ✨ ENV: `OFFLINE_IFTTT={event}:{key}` - Send a webhook trigger to IFTTT when the camera goes offline (-90).

- **CHANGED**: 🚧 MQTT now reports camera `state` as "connected", "disconnected", "offline", or the connection error. (#359)

- **FIXED**: 🔧 Use case-sensitive keys for livestream. (#371) Thanks @radnor!
- **FIXED**: 🔧 Stream would not come back when audio was enabled. (#347) Thanks @compeek!

## Changes in v1.4.0/1

- **NEW**: 🔊 Audio is now available. [Details](https://github.com/mrlt8/docker-wyze-bridge#audio)

- **UPDATED**: ⬆️ rtsp-simple-server > [v0.18.2](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.18.2)

- **FIXED**: 🔧 Doorbell rotation. (#362) Thanks @krystiancharubin!

## Changes in v1.3.8

Audio is also coming soon. Please check out the audio branch to report any issues.

### 🚧 Changed

- Fixed a bug where the doorbell would fall behind and drift out of sync. Thanks @krystiancharubin!

## Changes in v1.3.7

### ✨ NEW

- Support for Wyze Cam Outdoor v2! (#354) Thanks @urubos!

### 🚧 Changed

- Fixed bug where the add-on would not start in Home Assistant if hostname was not set. (#355) Thanks @cbrightly!
- Fixed bug where rtsp-simple-server would refuse connections if the camera name contained a special character. (#356) Thanks @JochenKlenk!
- Set default doorbell bitrate to 180.

### 🐛 Bugs

There is a known bug/issue with certain doorbells that drift out of sync due to the day/night fps change (#340).

## Changes in v1.3.6

### 🚧 Changed

- Fixed bug in Home Assistant config that was causing the add-onn not to load. (#351) Thanks @jdeath, @JochenKlenk!
- Fixed bug in ffmpeg command to use protocol specified in `RTSP_PROTOCOLS`. (#347) Thanks @AdiAbuAli!

## Changes in v1.3.4/v1.3.5

### ✨ NEW

- ENV option: `IMG_TYPE` - Specify the snapshot image file type, e.g. `IMG_TYPE=png`
- ENV option: `SKIP_RTSP_LOG` - Prevent "read" spam in logs when using RTSP based snapshots.

### 🚧 Changed

- Fixed bug in v1.3.4 that could cause the CPU to spike.
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
