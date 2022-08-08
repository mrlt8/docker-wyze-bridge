## What's Changed in v1.8.0

- New: on-demand streaming. Use the optional `ON_DEMAND=True` ENV to enable.
  - Outdoor cams (WVOD1 and HL_WCO2) will automatically be marked as on-demand.
- Changed: WebUI will NOT auto reload snapshots for cameras marked as on-demand or if ON_DEMAND is enabled, but manually refreshing the image will continue to work.

## What's Changed in v1.7.5

- New: Switch between still preview and video-js directly in the web-ui without having to change the ENV.
- Fixed: background color on mobile view of the Web-UI.
- Web-UI: Disable snapshot reloads by setting reload time to 0. #36
- Web-UI: Darker background on `prefers-color-scheme: dark`.
- Updated: iOS and wyze app version numbers

## What's Changed in v1.7.4

- **Fixed**: Custom strftime in the RECORD_FILE_NAME would produce the wrong format. #487  Thanks @WasabiNME
- **Changed**: Sleep 2 seconds on TutkError
- **Updated**: rtsp-simple-server to v0.19.3

## What's Changed in v1.7.3

- **NEW** - Dark mode for Web-UI!
- **NEW** - Custom url config for HA. (#473)
- **CHANGED** - Cleanup connections before exit.

## What's Changed in v1.7.2

- **NEW** - SD card storage info and audio status icons in Web-UI.
- **FIXED** - extra padding around image/video.
- **FIXED** - Preview image would not load in some situations.
- **FIXED** - Wrong version number in previous release.

## What's new in v1.7.0

Some wyze cams have have a built-in http server "boa" that is enabled when downloading a time lapse from the camera. By enabling this http server, we can have access to the SD card on the camera, so you can download whatever you need off the SD card without having to take each camera down.

PLEASE NOTE: If enabled, anyone on your local network will be able to access/download stuff from the SD Card on the camera.

**NEW** ENV options:

- `ENABLE_BOA` - Enable the boa HTTP server on select cameras with an SD card.
- `BOA_INTERVAL` - The number of seconds between image pulls/keep alives.
- `TAKE_PHOTO` - Take a high quality photo on the camera SD Card on `BOA_INTERVAL`.
- `PULL_PHOTO` - Download latest high-quality photo from camera.
- `PULL_ALARM` - Download latest alarm file from camera and notify via MQTT if available.
- `MOTION_HTTP` - Make a Webhook/HTTP request to any url on motion, e.g., `http://localhost/triggerMotion?cam={cam_name}`.
- `MOTION_COOLDOWN` - Number of seconds to keep the motion flag set to true before resetting it.

Other changes:

- WEB-UI: `/photo/<cam-name>.jpg` endpoint to take a photo on the camera sensor and return it.
- WEB-UI: Display additional `camera_info` from the current session. #436
- MQTT: `/takePhoto` endpoint to take a photo on the camera sensor.
- MQTT: `/motion` endpoint that updates when a new file is detected in the alarm folder on the camera's SD card. Requires `PULL_ALARM` to be enabled.

## Changes in v1.6.13

- **FIXED** Web-UI: reload cached images on page load

## Changes in v1.6.12

- **FIXED** Web-UI image not refreshing in some browsers. #460
- **CHANGED** Home Assistant: Use hostname from request for Web-UI. #465

## Changes in v1.6.11

- **NEW** Restart connection to all cameras or restart rtsp-server from webui.
  - `/restart/cameras`: Stop and start connection to all enabled cameras.
  - `/restart/rtsp_server`: Stop and start rtsp-simple-server.
  - `/restart/all`: Stop and start rtsp-simple-server and connection to all enabled cameras.
- **NEW** ENV `AUDIO_STREAM` or `AUDIO_STREAM_CAM_NAME` to create an audio only sub-stream with the `_audio` suffix: /cam_name_audio #446
- **FIXED** five column view in web-ui.
- **FIXED** static values in web-ui load.
- **FIXED** validate input in webui to prevent invalid values.

## Changes in v1.6.10

- **Home Assistant** Expose port `5000` for web-ui and snapshots. #455
- **Web-UI** Disable reload button while snapshot is updating.
- **Web-UI** Use navbar for filtering and other settings.
- **FIXED** web-ui would fail to load if cookies values were set to none.

## Changes in v1.6.9

Web-UI:

- **FIXED** Dropdown triggering drag, only allow drag from card-title area. Thanks @dsheehan!
- **FIXED** Drag/drop ghost maintain height when columns set to 1. Thanks @dsheehan!
- **CHANGED** Render _url as links in info dropdown. Thanks @dsheehan!
- **CHANGED** Hide filter tabs if all cams enabled.
- **CHANGED** Loading image to match 16x9 ratio.

## Changes in v1.6.8

Once again, huge thanks to @dsheehan!

- **UPDATED** Web-UI: Customizable refresh interval, and improved /img/cam-name.jpg. Thanks @dsheehan!
  - `:5000/snapshot/cam-name.jpg` - Always capture a new snapshot from the rtsp stream. This process may take a couple of seconds.
  - `:5000/img/cam-name.jpg` - Will attempt to return an existing snapshot or capture a new one from the the rtsp stream.
- **NEW** Web-UI: Refresh button to update a snapshot on-demand.
- **FIXED** Zombie processes should be gone now that we're waiting for the images to be returned from ffmpeg.

## Changes in v1.6.7

- **NEW** Web UI: Embed HLS video using videojs. Thanks @dsheehan!
  - Can be enabled with `WB_SHOW_VIDEO=True`
- **FIXED** Web UI: RTSP snapshots for cameras with spaces in their name.
- **CHANGED** Web UI: Defaults to show enabled cameras on load.

## Changes in v1.6.6

- **NEW**: Initial ssupport for the original WyzeCam v1 (WYZEC1). #57 Thanks @jamescochran @Webtron18!
- **NEW**: WEB-UI - Automated RTSP snapshots while page is open. #437
- **FIXED**: `panic: assignment to entry in nil map` in rtsp-simple-server. #419
- **UPDATED**: rtsp-simple-server > [v0.19.2](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.19.2)

## Changes in v1.6.5

- **NEW**: WEB-UI - filter out disabled/offline cameras. #439
- **FIXED**: WEB-UI - Use hostname from request for hls/rtsp/rtmp. #429
- **UPDATED**: ⬆️ API: Wyze app version number bump to 2.32.0.20.

## Changes in v1.6.4

- **IMPROVED**: Reliability of dragging/sorting cameras in Web-UI. Thanks @dsheehan!
- **NEW**: Version check on footer of Web-UI.
- **FIXED**: Static files for Web-UI in Home Assistant.

## Changes in v1.6.3

- **Fixed**: x264 rotation could cause issues with HLS and RTMP. #428 #431 Thanks @jamescochran!

## Changes in v1.6.0/v1.6.1/v1.6.2

Huge thanks goes to @dsheehan for building and adding a web-ui for the bridge!

- **NEW**: Web-UI on port `5000` (must add `- 5000:5000` to the ports section of your docker-compose.yml)
  - 🏠 Home Assistant: Web-ui will be automatically configured and you can add it to your sidebar by enabling it on the info page for the add-on.
- **CHANGED**: `mfa_token` is now `mfa_token.txt` on the docker version to match Home Assistant mode.
- **FIXED**: AttributeError with an unsupported WYZEC1. #422
- **FIXED**: FLASK_APP env error. #424 Thanks @dsheehan
- **FIXED**: clean_name. #424 Thanks @dsheehan

## Changes in v1.5.4

- Auto fetch camera data if upgrading from older version without having to use `FRESH_DATA`. #418
- Display DTLS on Wyze Cam Outdoors if base station has DTLS enabled.

## Changes in v1.5.3

⚠️ This version may require a one-time `FRESH_DATA` to generate the new authkey for compatibility with the WCO.

- **FIXED**: Authkey/DTLS - Wyze Cam Outdoor would timeout when connecting. #384

## Changes in v1.5.2

- **FIXED**: Setting the `WEBRTC` env to false would still pull the WebRTC credentials. #410

## Changes in v1.5.1

- **NEW**: ✨ Home Assistant: `RTSP_SIMPLE_SERVER` option to configure rtsp-simple-server, e.g. use `paths_all_readusers=123` for `paths: all: readuser:123`.
- **UPDATED**: ⬆️ rtsp-simple-server > [v0.19.1](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.19.1)

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
