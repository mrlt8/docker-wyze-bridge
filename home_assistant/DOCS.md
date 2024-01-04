# Docker Wyze Bridge

## Required Configs

Credentials for the wyze account you are trying to use.

- `WYZE_EMAIL`
- `WYZE_PASSWORD`

### Two-Step Verification

If you have Two-Step Verification enabled on the account, you can add your verification code to the text file: /config/wyze-bridge/mfa_token.txt

## Optional Configs

- `NET_MODE` - Allowed connection mode between the camera and the bridge:
  - `LAN` - Restrict connections to local access only. Will NOT use additional bandwidth.
  - `P2P` - Allow streaming from the camera over the internet if camera cannot be found locally. MAY use additional bandwidth.
  - `ANY` - Allow the stream to be relayed over the wyze server. MAY use additional bandwidth if in P2P or relay mode.
- `SNAPSHOT` - Enable snapshots for all cameras.
  - `API` - Will run ONCE at startup and will grab a high-quality thumbnail from the wyze api.
  - `RTSPX` - Will grab a new frame from the RTSP stream every X seconds.

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

- `AUDIO` - enable audio for this camera.
- `FFMPEG` - use a custom ffmpeg command for this camera.
- `LIVESTREAM` - specify a rtmp url to livestream to for this camera.
- `NET_MODE` - change the allowed net mode for this camera only.
- `QUALITY` - Adjust the quality for this camera only.
- `RECORD` - enable recording for this camera.
- `ROTATE` - rotate this camera 90 degrees clockwise.

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
