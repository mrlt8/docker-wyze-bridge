# Docker Wyze Bridge

(coming soon)

## URIs

`camera-nickname` is the name of the camera set in the Wyze app and are converted to lower case with hyphens in place of spaces.

e.g. 'Front Door' would be `/front-door`

- RTMP:

```
rtmp://homeassistant.local:1935/camera-nickname
```

- RTSP:

```
rtsp://homeassistant.local:8554/camera-nickname
```

- HLS:

```
http://homeassistant.local:8888/camera-nickname/stream.m3u8
```

- HLS can also be viewed in the browser using:

```
http://homeassistant.local:8888/camera-nickname
```

Please visit [github.com/mrlt8/docker-wyze-bridge](https://github.com/mrlt8/docker-wyze-bridge) for additional information.
