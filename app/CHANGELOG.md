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