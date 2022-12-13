## What's Changed in v1.10.1

- Home Assistant: disable WEB_AUTH #638

## What's Changed in v1.10.0

- New: Optional basic auth for WebUI with `WEB_AUTH=True` #612 Thanks @yeahme49!
  - Note: this will only protect the WebUI. API and snapshot endpoints are unprotected at this time.
- New: API endpoints and MQTT topic to send commands to the camera.
  - See the [Camera Control](#camera-control) section for more info.
- Updated: Wyze app and iOS version for the Web API
- Updated: rtsp-simple-server to [v0.20.4](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.20.4)

## What's Changed in v1.9.2

- Fixed an issue introduced in v1.9.1 that could cause the bridge from reconnecting to a camera. #619 #620 Thanks @dmkjr and @mjb83!

## What's Changed in v1.9.1

  - Potential Fix: Audio and video lagging #597 Thanks @carldanley!
  - Changed: CPU and memory optimization. 
  - Changed: Allow quality lower than 30. #608
  - Changed: Show video codec.
  - Changed: Use h264 preset `fast` for `h264_nvenc`.
  - Updated: iOS and wyze version for web api.

## What's Changed in v1.9.0

  - New: Wyze Cam V3 Pro 2K support! Should also work with the Pan Pro 2k. #595 Huge thanks to @carldanley!

## What's Changed in v1.8.13

  - Fix: "Fatal Python error" on read/ready events.
  - Fix: occasional snapshot timeouts.
  - Fix: ignore TutkError if camera is offline when using rtsp_fw.
  - Fix: refresh button for WebUI.
  - New: timestamp for last snapshot in API.
  - Update: wyze app version number for web API.
  - Updated: rtsp-simple-server to [v0.20.2](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.20.2).

## What's Changed in v1.8.12

  - Fixed: Local recording creating zero byte files when audio codec was not supported by the mp4 container. #575 Thanks @pldimarco!
    - Note: Bridge wil use the `mov` container if using the raw PCM from camera. Please usee `AUDIO_CODEC=aac` if you require an mp4.
  - New: Show camera status and name in fullscreen WebUI. 
  - New: Optional autoplay in WebUI - Requires autoplay support in the browser. #574 Thanks @JA16122000!
  - New: Query params for web-ui:
    - autoplay `http://localhost:5000/?autoplay`
  - Updated: rtsp-simple-server to v0.20.1
  - Updated: iOS Version
## What's Changed in v1.8.11

  - Fix: missing url for RTSP_FW #564 Thanks @anderfrank!
  - New: Fullscreen/kiosk mode for web-ui that hides all the extra links and buttons. #567 Thanks @RUHavingFun! 
  - New: Pre-built docker images with hwaccel enabled for amd64 #548
  - New: Show time since last snapshot
  - New: Query params for web-ui:
    - Fullscreen/kiosk mode `http://localhost:5000/?fullscreen`
    - Number of columns `http://localhost:5000/?columns=4`
    - Preview refresh interval `http://localhost:5000/?refresh=60`
    - Camera order `http://localhost:5000/?order=front-cam,back-cam,garage,other`
## What's Changed in v1.8.10

  - Fix: bitstream data when using rotation which could cause issues in some clients like Homebridge. Thanks @noelhibbard! #552
  - Fix: broken snapshots for cameras with spaces in the name if stream auth enabled. Thanks @RUHavingFun! #542
  - Updated: iOS and App version bump.
  - New: ENV option `RTSP_FW=True` to proxy an extra RTSP stream if on official RTSP FW (4.19.x, 4.20.x, 4.28.x, 4.29.x, 4.61.x.).
    - Additional stream will be available with the `fw` suffix e.g., `cam-namefw`
  - New: ENV option `H264_ENC` to allow for custom h264 encoder (e.g. h264_cuvid or h264_v4l2m2m) for rotation/re-encoding. #548
    - Additional configuration required for hwaccel encoding. 
    - h264_v4l2m2m currently has bistream issues and is NOT working in certain clients like homebridge. 
    - Use `Dockerfile.hwaccel` for ffmpeg compiled with with h264_cuvid.
  - Fixed: env bug on startup #559 Thanks @tbrausch!
  
## What's Changed in v1.8.8

  - Fixed: 2FA code was not working in Home Assistant Ingress/Web UI. #541 Thanks @rlust!
  - Updated: iOS version number.
  - Beta: Initial support HL_CAM3P (V3 Pro) and HL_PANP (Pan Pro) - 2K streams may need `IGNORE_RES=4`. Additional testing required.

## What's Changed in v1.8.7

This update brings more 2FA related changes as Wyze recently sent out some emails stating that "**all users will be required to use two-factor authentication to log into a Wyze account**".

- Fixed: Adjusted totp parsing to accept alphanumeric chars (#530). Thanks @gusmann!
- New: Enter Two-Factor Verification code directly in the WebUI.
- New: `TOTP_KEY` ENV option as an alternate to the `/tokens/totp` file to automatically generate and enter a Time-based One-Time Password (TOTP).
- New: `http://localhost:5000/mfa/<123456>` WebUI API endpoint to submit a 2FA code.
- Updated: Wyze App version number for Web API.

## What's Changed in v1.8.6

- Fixed: Custom paths for WebUI. #520 Thanks @peasem!
- New: Update camera info from the API on click/tap in the WebUI.
- New: Auto use Home Assistant SSL if available for HLS-LL. #473 Thanks @pgross41!
- ⚠️ Changed: `/cameras` endpoint has changed to `/api`.
- Changed: Ignore on-demand if recording is enabled for a camera.
- Updated: iOS version number for Web API.
- Updated: Wyze App version number for Web API.

## What's Changed in v1.8.5

- Fixed: Remove all non-numeric characters when submitting the 2FA. #518
- Fixed: Catch challenge_response error. #520
- Fixed: RTSP snapshots for WebUI when authentication enabled for streams. #522
- Potential Fix: Invalid credentials message when attempting to login with the production API. Use beta server with ENV `WYZE_BETA_API`. #505
- Potential Fix: Reduce ENR/IOTC_ER_TIMEOUT API cooldown #510
- New: WebUI endpoint to stop on-demand streams: `/events/stop/<camera-name>`
- New: WebUI button to start/stop individual streams.
- Changed: WebUI status icons for connected/connecting/offline/standby.
- Changed: WebUI icon when using authentication for streams. #522

## What's Changed in v1.8.4

- Fixed: Remove connected status on lost connection to bridge.
- Potential Fix: Pull fresh camera data on IOTC_ER_TIMEOUT which is potentially caused by wyze changing the ENR used for authenticating with the cameras. #508 #510 Thanks @krystiancharubin
- Potential Fix: Invalid credentials message when attempting to login with the iOS x-api-key. Can now set a custom key using the ENV `WYZE_APP_API_KEY`. #505
- Changed: The `/restart/all` endpoint will now clear the local cache and pull fresh camera data before restarting the cameras. #508
- Updated: rtsp-simple-server to [v0.20.0](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.20.0)

## What's Changed in v1.8.3

- Fixed: Bug where cameras would go into a "Timed out connecting to ..." loop #391 #484
- Fixed: Bug when restarting the connection to the cameras in the WebUI #391 Thanks @mdabbs!
- Fixed: TypeError when setting a custom `BOA_INTERVAL` #504 Thanks @stevenwbuehler!
- Fixed: Check up on snapshots to prevent zombie processes.
- New: Use server side events to update the connection status color on the Web-UI to show when a camera is actually connected.
- New: Pause/resume snapshots in the web-ui based on the connection status.
- New: API endpoints
  - `/cameras/sse_status` server side event to monitor connection to all cameras.
  - `/cameras/<camera-name>` return json for a single camera.
  - `/cameras/<cam-name>/status` return json with current connection status only.
- Changed: `/cameras` API endpoint format to include the total cameras and enabled cameras.
- Changed: Display on-demand status in the logs.
- Changed: More verbose http exceptions #505

## What's Changed in v1.8.1/2

- Fixed: timeout issue with on-demand stream. #501 Thanks @tremfranz!
- Fixed: disable on-demand wasn't working in HA.
- Fixed: WebUI was still loading live snapshots for on-demand cameras.
- Fixed: use url safe names for on-demand streams. #498 Thanks @terryhonn!

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
