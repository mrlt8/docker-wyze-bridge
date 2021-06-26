# RTMP/HLS Bridge for Wyze Cam

Quick docker container to enable RTMP/HLS streams for Wyze cams based on [noelhibbard's script](https://gist.github.com/noelhibbard/03703f551298c6460f2fd0bfdbc328bd#file-readme-md) using [kroo/wyzecam](https://github.com/kroo/wyzecam) and [alfg/nginx-rtmp](https://hub.docker.com/r/alfg/nginx-rtmp/). 

Has only been tested on macos.

---
### Usage

git clone this repo, edit the docker-compose.yml with your wyze credentials, then run `docker composer up`.


#### URLs

 - Stats:  
```
http://localhost:8080/stat
```
 - RTMP:  
```
rtmp://localhost:1935/stream/CAMERA.NICKNAME
```
- HLS:  
```
http://localhost:8080/live/CAMERA.NICKNAME.m3u8
```
- HLS can also be viewed in the browser using:
```
http://localhost:8080/player.html?url=http://localhost:8080/live/CAMERA.NICKNAME.m3u8
```