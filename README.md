# RTMP/RTSP/HLS Bridge for Wyze Cam

Quick docker container to enable RTMP, RTSP, and HLS streams for Wyze cams using [noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) with [kroo/wyzecam](https://github.com/kroo/wyzecam) and [aler9/rtsp-simple-server](https://github.com/aler9/rtsp-simple-server). 

Has only been tested on macos, but should work on most x64 systems. 

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