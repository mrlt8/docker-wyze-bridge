## Changes in v1.0.4

- 🚧 CHANGE: Use multiprocessing instead of multithreading for each camera - may use more resources, but should keep other streams alive (#211)
- 🔧 FIX: import exceptions (#214, #228)

## Changes in v1.0.3

- 🔧 FIX: Memory leak in video buffer (#197)
- 🔧 FIX: Display wifi signal for Outdoor cams
- 🔧 FIX: Ignore wrong res on stream startup (#221, #133)
- 🔧 FIX: rtsp_event related errors (#214, #228)
- ⬆️ UPDATE: Add additional tutk errors (#228)
- ⬆️ UPDATE: Wyze App version for API
- 🚧 CHANGE: Kill stream if no video frames for 10+ seconds (#201)

## Changes in v1.0.2

- ✨ NEW: Camera specific QUALITY adjustments e.g. `QUALITY_CAM_NAME=SD30` #199
- 🔧 MQTT related fixes and improvements #194 - Thanks @TTerastar!
- 🔧 FIX: FFMPEG related freezes #200 - Thanks @AdiAbuAli!
- 🔧 CHANGE: c_types for tutk library
- ⬆️ UPDATE: iOS and Wyze App version for API
- ⬆️ UPDATE: rtsp-simple-server v0.17.7

## Changes in v1.0.1

- 🏠 Home Assistant: Potential fix for DNS issue #107 - Thanks [@AlejandroRivera](https://github.com/mrlt8/docker-wyze-bridge/issues/107#issuecomment-950940320)!
- ➕ Added: Camera names for Pan V2 and Outdoor V2
- 🔧 Changed: Remove all special characters from URIs #189
- 🔧 Changed: fflags as potential fix for FFMPEG freezes #187- Thanks [@AdiAbuAli](https://github.com/mrlt8/docker-wyze-bridge/issues/187#issuecomment-951331290)

## Changes in v1.0.0

- ✨ NEW: DTLS Firmware support - bridge should now work on cameras with the latest firmware
- ✨ NEW: Wyze Cam Outdoor (WVOD1) support
