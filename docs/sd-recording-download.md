# Optional camera SD recording download

This experimental adapter retrieves one existing normal camera SD recording through an optional external helper. The helper implements authenticated LAN RDT transfer; the bridge does not duplicate that protocol. It does not use BOA, record a live stream, or download a cloud event clip. No new player or download scheduler is included.

The feature is disabled unless the administrator sets `SD_DOWNLOAD_HELPER` to an absolute executable path in the Linux container. Mount a compatible helper built for the container's architecture; no helper is downloaded automatically, and the default Docker images and dependencies are unchanged. Hardware/firmware coverage depends on the selected helper. The initial target is DTLS-capable Wyze Cam v3 normal `/media/mmc/record/` recordings; do not assume compatibility with all Wyze models or firmware.

## Request

Use the existing bridge authentication (HTTP Basic or API key in the `api` header):

```http
POST /api/front-door/sd/recording
Content-Type: application/json
api: YOUR_BRIDGE_API_KEY

{"date":"20261030","hour":15,"minute":"07","new":false}
```

`date` is a valid calendar date formatted `YYYYMMDD`. `hour` and `minute` are integers or one/two-digit ASCII strings, in ranges 0–23 and 0–59. These identify the camera's local recording filename; the bridge performs no timezone conversion. Optional `new` must be a JSON boolean; `true` requests the `_new.mp4` variant. Unknown or duplicate fields are rejected. Bodies are limited to 1024 bytes. There is no arbitrary filename/path parameter or automatic variant fallback.

On success the response is an attachment containing the unchanged MP4 bytes, with `Cache-Control: no-store`. Audio compatibility is determined by the original file's codecs. Only cameras already present in the bridge's streams are eligible. Pairing data comes from the cached camera object; this request does not invoke cloud discovery or log in to Wyze again.

Only one SD request runs at a time per bridge process. The helper has a 65-second process timeout and a 16 MiB file limit. The private temporary directory (0700), pairing JSON (0600), helper result and media are deleted after response completion/disconnection; failed transfers are never served. The lock remains held until the response closes. It does not stop/reconfigure the bridge's existing live streams. Simultaneous live/SD support still depends on the camera and helper.

Fixed JSON errors distinguish disabled (501), unavailable backend (503), invalid input/pairing (400/415/422), missing camera/recording (404), busy (409), oversized request (413), incomplete/invalid helper results (502), and helper timeout (504). Raw helper logs, peer responses, pairing data, and filesystem errors are not returned.

## Helper contract

The executable receives these arguments directly, without a shell:

```text
HELPER --live --credentials PRIVATE/camera.json --download /media/mmc/record/YYYYMMDD/HH/MM.mp4 --media-output PRIVATE/clip.mp4 --output PRIVATE/result.json --max-bytes 16777216
```

The bridge creates `camera.json` with only `ip`, `uid`, `enr`, `mac`, `model`. It passes no Wyze account password, API key, or access token. The helper must create a fresh authenticated camera session for each invocation and perform exactly one RDT operation; reopening RDT on a reused authenticated session is not supported. It must enforce `--max-bytes` during transfer, create a new private media file, finish protocol cleanup, and exit. The adapter launches a new helper process per request. Standard output/error are discarded. Use a trusted helper; configuration of this executable is an administrator capability.

Success requires exit zero and JSON fields `phase: "download_complete"`, `operation: "download_sd_file"`, `recording_path` exactly matching the request, and integer `downloaded_bytes` equal to the regular, private media file's length (1–16777216 bytes). A nonempty `error`, missing/wrong metadata, symlink, oversized or partial output is rejected. The result JSON is limited to 16 KiB. A missing recording uses `error: "file does not exist"` with the matching operation/path; other errors remain opaque to the adapter.

The matching public Go helper is supplied separately; it is not bundled in this patch. No all-day bulk download or native-SDK RDT symbols are required in Docker Wyze Bridge.

## Offline validation

With the project's Flask/Flask-HTTPAuth dependencies installed, run:

```sh
python -m unittest discover -s tests -v
```

Tests use fake local helper executables and the actual frontend authentication wrapper in isolation. They do not start the bridge, load the camera SDK, or contact a camera/cloud service.
