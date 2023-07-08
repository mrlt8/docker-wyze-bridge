## What's Changed in v2.3.9

* NEW: ENV Options - token-based authentication (#876)
  * `REFRESH_TOKEN` - Use a valid refresh token to request a *new* access token and refresh token.
  * `ACCESS_TOKEN` - Use an existing valid access token too access the API. Will *not* be able to refresh the token once it expires.
* NEW: Docker "QSV" Images with basic support for QSV hardware accelerated encoding. (#736) Thanks @mitchross, @392media, @chris001, and everyone who helped!
  * Use the `latest-qsv` tag (e.g., `mrlt8/wyze-bridge:latest-qsv`) along with the `H264_ENC=h264_qsv` ENV variable. 
* FIXES:
  * Home Assistant: set max bitrate quality to 255 (#893) Thanks @gtxaspec!
  * WebUI: email 2FA support.
* UPDATES:
  * Docker base image: bullseye -> bookworm
  * MediaMTX: v0.23.6 -> v0.23.7
  * Wyze App: v2.42.6.1 -> v2.43.0.12

## What's Changed in v2.3.8

* FIX: Home Assistant - `API_KEY` and `API_ID` config for wyze API was broken. (#837)
* FIX: Prioritize sms > totp > email for MFA if no MFA_TYPE or primary option is set. (#885)
* Potential fix: Add libx11 to qsv image.

## What's Changed in v2.3.7

* FIX: Regression introduced in v2.3.6 if primary_option for MFA is "Unknown". Will now default to sms or totp if MFA_TYPE is not set. Thanks @Dot50Cal! (#885)
* FIX: Reduce excess logging if rtsp snapshot times out.

## What's Changed in v2.3.6

* NEW: Add support for email 2FA (#880) Thanks @foobarmeow!
* NEW: ENV Option `MFA_TYPE` - allows you to specify a verification type to use when an account has multiple options enabled. Will default to the primary option from the app if not set. Valid options are:
  * `TotpVerificationCode`
  * `PrimaryPhone`
  * `Email`

## What's Changed in v2.3.5

* FIXED: response code and error handling for Wyze Web API.
* FIXED: catch exceptions when taking a snapshot (#873)
* CHANGED: MediaMTX versions are now pinned to avoid breaking changes.
* UPDATED: MediaMTX to 0.23.6 and fixed `MTX_PATH`.

## What's Changed in v2.3.4

* ENV Options:
  * FIX: `FILTER_NAMES` would not work if camera had spaces at the end of the name. Thanks @djak250! (#868)
* Camera Commands:
  * FIX: Regression introduced in v2.3.3 preventing negative values for the `rotary_degree` topic. Thanks @gtxaspec! (#870) (#866)
  * FIX: String cmd lookup for `rotary_degree` and json error response breaking web api. #870 #866
* Other Fixes:
  * Catch exceptions when saving thumbnail from api. (#869)
  * Clear cache on UnpicklingError. (#867)

## What's Changed in v2.3.3

* ENV Option:
  * NEW: Add `SUB_RECORD` config. Thanks @gtxaspec! (#861)
  * FIX: Home Assistant `SUB_QUALITY`
* MQTT:
  * NEW: Update more camera parameters on connect.
* Camera Commands:
  * NEW: Add GET topics for camera params.
  * FIX: Persist bitrate changes on-reconnect (#852)
  * FIX: Limited vertical angle for `ptz_position`. Thanks @Rijswijker! (#862)

## What's Changed in v2.3.2

* Camera commands:
  * SET Topic: `state`; payload: `start|stop|enable|disable` - control the camera stream.
  * GET Topic: `state` - get the state of the stream in the bridge.
  * GET Topic: `power` - get the power switch state (Wyze Cloud API).
* REST/MQTT Control:
  * FIXED: Refresh token if needed when sending `power` commands.
  * FIXED: Remove quotations from payload. (#857)
  * CHANGED: Better error handling for commands.
* MQTT:
  * Updated discovery availability and additional entities.
  * Publish additional topics with current settings.
  * Disable on TimeoutError.
  
## What's Changed in v2.3.1

* NEW: WebUI - Power on/off/restart controls.
  * As these commands are sent over Wyze's Cloud API, the cameras will need access to the wyze servers.
  * These commands also suffer from the same "offline" issue as the app, and will give an error if the camera is reporting offline in the app.
* NEW: Camera commands:
  * Topic: `power`; payload: `on|off|restart` Sent over Wyze Cloud API. (#845) (#841)
  * Topic: `bitrate`; payload: `1-255` Change the video bitrate/quality (#852)
* NEW: Camera specific sub_quality option (#851)
  * Docker: use `SUB_QUALITY_NAME=SD60`
  * Home Assistant: use `SUB_QUALITY: SD60` in [Camera Specific Options](https://github.com/mrlt8/docker-wyze-bridge/wiki/Home-Assistant#camera-specific-options).
* NEW: Home Assistant - add config for 8554/udp (#855)

## What's Changed in v2.3.0

* NEW: Optional `API_KEY` and `API_ID` config for wyze API (#837)
  * Key/ID are optional and the bridge will continue to function without them.
  * `WYZE_EMAIL` and `WYZE_PASSWORD` are still required, but using API key/ID will allow you to skip 2FA without disabling it.
  * Key/ID are tied to a single account, so you will need to generate a new set for each account.
  * See: https://support.wyze.com/hc/en-us/articles/16129834216731
* NEW: Camera commands (#835)
  * GET/SET `cruise_points` for Pan cams. See [cruise_points](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Commands#cruise_points)
  * GET/SET `ptz_position` for Pan cams. See [ptz_position](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Commands#ptz_position)

## What's Changed in v2.2.4

* NEW: Add Wyze credentials via WebUI.
  * This does not replace the old method, but is just an alternate way to pass your wyze credentials to the container.
  * This should hopefully resolve the issue some users were facing when they had special characters in their docker-compose.
  * `WYZE_EMAIL` and `WYZE_PASSWORD` are no longer required to start the bridge. #807
* FIXED: Log wording when filtering is enabled. Thanks @cturra
* UPDATED: MediaMTX to v0.23.5

## What's Changed in v2.2.3

* NEW: `LOG_TIME` config to add timestamps to the logs. #830
* CHANGED: `DEBUG_LEVEL` is now `LOG_LEVEL`
* FIXED: `DEBUG_LEVEL`/`LOG_LEVEL` and `LOG_FILE` were broken in Home Assistant. #830
  * `LOG_FILE` now logs to `/config/wyze-bridge/logs/`
  
## What's Changed in v2.2.2

* FIXED: `autoplay` URL parameter was being ignored - Thanks @stere0123! #826
* NEW: Fullscreen mode on web-ui enables autoplay.
* Disabled `LD_CFP` "Floodlight Pro" because it doesn't use tutk - Thanks @cryptosmasher! #822
  * This seems to be slightly different than the Gwell cameras (OG/Doorbell Pro). Needs further investigation. 
* UPDATED: MediaMTX to [v0.23.4](https://github.com/bluenviron/mediamtx/releases/tag/v0.23.4).

## What's Changed in v2.2.1

* FIXED: topic to set `motion_tracking` Thanks @crslen! #823
* FIXED: additional cam info was missing from web-ui.
* NEW: outdoor cam related tutk commands and `battery` topic for API.

## What's Changed in v2.2.0

⚠️ Breaking changes for MQTT/REST API 

See [wiki](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Commands) for details.

* CHANGED: API commands are now split into topics and payload values for more flexibility.
* NEW: API commands will initiate connection if not connected.
* NEW: json payload for API commands.
* NEW: `PUT`/`POST` methods for REST API.
* NEW: MQTT topics for each get and set command.
* NEW: MQTT value gets updated on set command.
* NEW: start/stop/enable/disable over MQTT.
* FIXED: camera busy on re-connect.

## What's Changed in v2.1.8

* NEW: Camera Commands
  * `set_pan_cruise_on`/ `set_pan_cruise_off`  - Enables or disables the Pan Scan ("Cruise") behavior, where the camera cycles through configured waypoints every 10 seconds. Thanks @jhansche
  * `set_motion_tracking_on`/`set_motion_tracking_off`/`get_motion_tracking` - Follow detected motion events on Pan Cams. Thanks @jhansche
* NEW: ENV Option
  * `ROTATE_IMG_CAM_NAME=<true|0|1|2|3>` - Rotate snapshots for a single camera. #804
* UPDATE: MediaMTX to v0.23.3
* UPDATE: WebRTC offer to use SDP for compatibility with MTX v0.23.3

## What's Changed in v2.1.7

* FIX: WebRTC not loading in the WebUI.
* UPDATE: MediaMTX to v0.23.2

## What's Changed in v2.1.6

* UPDATE: MediaMTX to v0.23.0
* FIXED: Error reading some events.
* FIXED: Restart MediaMTX on exit and kill flask on cleanup which could prevent the bridge from restarting.

## What's Changed in v2.1.5

* FIX: set_alarm_on/set_alarm_off was inverted #795. Thanks @iferlive!
* NEW: `URI_MAC=true` to append last 4 characters of the MAC address to the URI to avoid conflicting URIs when multiple cameras share the same name. #760
* Home Assistant: Add RECORD_FILE_NAME option #791
* UPDATE: base image to bullseye.

## What's Changed in v2.1.4

* FIX: Record option would not auto-connect. #784 Thanks @JA16122000!

## What's Changed in v2.1.2/3

* Increase close on-demand time to 60s to prevent reconnect messages. #643 #750 #764
* Disable default LL-HLS for compatibility with apple. LL-HLS can still be enabled with `LLHLS=true` which will generate the necessary SSL certificates to work on Apple devices.
* Disable MQTT if connection refused.
* UPDATED: MediaMTX to [v0.22.2](https://github.com/aler9/mediamtx/releases/tag/v0.22.2)

## What's Changed in v2.1.1

* FIXED: WebRTC on UDP Port #772
* UPDATED: MediaMTX to [v0.22.1](https://github.com/aler9/mediamtx/releases/tag/v0.22.1)
* ENV Options: Re-enable `ON_DEMAND` to toggle connection mode. #643 #750 #764

## What's Changed in v2.1.0

⚠️ This version updates the backend rtsp-simple-server to MediaMTX which may cause some issues if you're using custom rtsp-simple-server related configs.

* CHANGED: rtsp-simple-server to MediaMTX.
* ENV Options:
  * New: `SUB_QUALITY` - Specify the quality to be used for the substream. #755
  * New: `SNAPSHOT_FORMAT` - Specify the output file format when using `SNAPSHOT` which can be used to create a timelapse/save multiple snapshots. e.g., `SNAPSHOT_FORMAT={cam_name}/%Y-%m-%d/%H-%M.jpg` #757:
* Home Assistant/MQTT:
  * Fixed: MQTT auto-discovery error #751
  * New: Additional entities for each of the cameras.
  * Changed: Default IMG_DIR to `media/wyze/img/` #660

## What's Changed in v2.0.2

* Camera Control: Don't wait for a response when sending `set_rotary_` commands. #746
* Camera Control: Add commands for motion tagging (potentially useful if using waitmotion in mini hacks):
  * `get_motion_tagging` current status: `1`=ON, `2`=OFF.
  * `set_motion_tagging_on` turn on motion tagging.
  * `set_motion_tagging_off` turn off motion tagging
* WebUI: Refresh image previews even if camera is not connected but enabled. (will still ignore battery cameras) #750
* WebUI: Add battery icon to cameras with a battery.
* WebUI: Use Last-Modified date to calculate the age of the thumbnails from the wyze API. 
* Update documentation for K10010ControlChannel media controls for potential on-demand control of video/audio.

## What's Changed in v2.0.1

* Fixed a bug where the WebUI would not start if 2FA was required. #741

## What's Changed in v2.0.0

⚠️ All streams will be on-demand unless local recording is enabled.

* NEW: Substreams - Add a secondary lower resolution stream:
  * `SUBSTREAM=True` to enable a lower resolution sub-stream on all cameras with a compatible firmware.
  * `SUBSTREAM_CAM_NAME=True` to enable sub-stream for a single camera without a firmware version check.
  * Secondary 360p stream will be available using the `cam-name-sub` uri.
  * See the [substream](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Substreams) page for more info.
* NEW: WebUI endpoints:
  * `/img/camera-name.jpg?exp=90` Take a new snapshot if the existing one is older than the `exp` value in seconds.
  * `/thumb/cam-name.jpg` Pull the latest thumbnail from the wyze API.
  * `/api/cam-name/enable` Enable the stream for recording and streaming. #717
  * `/api/cam-name/disable` Disable the stream for recording and streaming. #717
* NEW: ENV Options:
  * `LOG_FILE=true` Log to file (`/logs/debug.log`).
  * `SUBJECT_ALT_NAME=str` Specify the subjectAltName for SSL. #725
* NEW: WebUI controls: `start/stop/enable/disable` as well as some basic controls for the night vision.
* NEW: JS notifications when the status of a stream changes.
* NEW: Browser notifications when the page is in the background. Requires a secure context.
* Performance improvements and memory optimization!
* Updated boa to work alongside other camera controls on supported firmware.
* Bump python to 3.11
* Bump rtsp-simple-server to [v0.21.6](https://github.com/aler9/rtsp-simple-server/releases/tag/v0.21.6)
* Bump Wyze app version.

Some ENV options have been deprecated:
* `ON_DEMAND` - No longer used as all streams are now on-demand.
* `TAKE_PHOTO` -> `BOA_TAKE_PHOTO`
* `PULL_PHOTO` -> `BOA_PHOTO`
* `PULL_ALARM` -> `BOA_ALARM`
* `MOTION_HTTP` -> `BOA_MOTION`
* `MOTION_COOLDOWN` -> `BOA_COOLDOWN`


[View previous changes](https://github.com/mrlt8/docker-wyze-bridge/releases)