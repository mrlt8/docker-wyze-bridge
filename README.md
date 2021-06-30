# RTMP/RTSP/HLS Bridge for Wyze Cam

Quick docker container to enable RTMP, RTSP, and HLS streams for Wyze cams using [noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) with [kroo/wyzecam](https://github.com/kroo/wyzecam) and [aler9/rtsp-simple-server](https://github.com/aler9/rtsp-simple-server). 

Exposes a local RTMP, RTSP, and HLS stream for all your Wyze Cameras. No Third-party or special firmware required.

Has only been tested on MacOS, but should work on most x64 systems. 

---
#### Usage

git clone this repo, edit the docker-compose.yml with your wyze credentials, then run `docker composer up`.

---

#### URLs

`camera-nickname` is the name of the camera set in the Wyze app and is in lower case with hyphens in place of spaces. e.g. 'Front Door' would be `/front-door`

- RTMP:  
```
rtmp://localhost:1935/camera-nickname
```
- RTSP:  
```
rtsp://localhost:8554/camera-nickname
```
- HLS:  
```
http://localhost:8888/camera-nickname/stream.m3u8
```
- HLS can also be viewed in the browser using:
```
http://localhost:8888/camera-nickname
```

---
#### Filtering

The default option will automatically create a stream for all the cameras on your account, but you can use the following environment options in your `docker-compose.yml` to filter the cameras.

All options are cAsE-InSensiTive, and take single or multiple comma separated values.

- Whitelist by Camera Name (set in the wyze app):
```yaml
environment:
    - WYZE_EMAIL=
    - WYZE_PASSWORD=
    - FILTER_NAMES=Front Door, Driveway, porch
```
- Whitelist by Camera MAC Address:
```yaml
environment:
    - WYZE_EMAIL=
    - WYZE_PASSWORD=
    - FILTER_MACS=00:aA:22:33:44:55, Aa22334455bB
```
- Whitelist by Camera Model:
```yaml
environment:
    - WYZE_EMAIL=
    - WYZE_PASSWORD=
    - FILTER_MODEL=WYZEC1-JZ
```

- Blacklisting:

You can reverse any of these whitelists into blacklists by adding *block, blacklist, exclude, ignore, or reverse* to `FILTER_MODE`. 


```yaml
environment:
    - WYZE_EMAIL=
    - WYZE_PASSWORD=
    - FILTER_NAMES=Bedroom
    - FILTER_MODE=BLOCK
```

---
#### Debugging options

`- DEBUG_FFMPEG=True` Prints stdout from FFmpeg
`- DEBUG_NOKILL=True` Don't force-restart straem on error.  
