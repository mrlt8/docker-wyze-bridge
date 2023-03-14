## What's Changed in v2.0.0

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

[View previous changes](https://github.com/mrlt8/docker-wyze-bridge/releases)