# Docker Wyze Bridge

## Wyze Authentication

As of April 2024, you will need to supply your own API Key and API ID along with your Wyze email and password. 

See the official help documentation on how to generate your developer keys: https://support.wyze.com/hc/en-us/articles/16129834216731.

## Stream and API Authentication

Note that all streams and the REST API will necessitate authentication when WebUI Auth `WB_AUTH` is enabled.

- REST API will require an `api` query parameter. 
  - Example:  `http://homeassistant.local:5000/api/<camera-name>/state?api=<your-wb-api-key>`
- Streams will also require authentication.
  - username: `wb`
  - password: your unique wb api key

Please double check your router/firewall and do NOT forward ports or enable DMZ access to your bridge/server unless you know what you are doing!

## Camera Specific Options

Camera specific options can now be passed to the bridge using `CAM_OPTIONS`. To do so you, will need to specify the `CAM_NAME` and the option(s) that you want to pass to the camera.

`CAM_OPTIONS`:

```YAML
- CAM_NAME: Front
  AUDIO: true
  ROTATE: true
- CAM_NAME: Back door
  QUALITY: SD50
```

Available options:

- `AUDIO` - Enable audio for this camera.
- `FFMPEG` - Use a custom ffmpeg command for this camera.
- `LIVESTREAM` - Specify a rtmp url to livestream to for this camera.
- `NET_MODE` - Change the allowed net mode for this camera only.
- `QUALITY` - Adjust the quality for this camera only.
- `SUBSTREAM` - Enable a substream for this camera.
- `SUB_QUALITY` - Adjust the quality for this substream.
- `RECORD` - Enable recording for this camera.
- `ROTATE` - Rotate this camera 90 degrees clockwise.
- `MOTION_WEBHOOKS` - Specify a url to POST to when motion is detected.

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
