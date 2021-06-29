from wyzecam import login, get_camera_list
from subprocess import Popen, PIPE, STDOUT
from threading import Thread
from os import environ
from time import sleep

auth_info = login(environ["WYZE_EMAIL"], environ["WYZE_PASSWORD"])

def rtsp_server(name):
    while True:
        print(f'[{name}]: Starting...',flush=True)
        environ["WYZE_CAMERA_NAME"] = name
        environ["RTMP_URL"] = 'rtmp://rtsp-server:1935/' + name.replace(' ', '-').lower()
        ffmpeg = Popen(['python', '/opt/wyzecam/wyzecam-to-rtmp.py'], stdout=PIPE,stderr=STDOUT, text=True)
        while ffmpeg.poll() is None:
            output = ffmpeg.stdout.readline().rstrip()
            if not output:
                continue
            if 'DEBUG_FFMPEG' in environ or any(err in output for err in [environ["RTMP_URL"], 'requests.exceptions.HTTPError','Conversion failed!','Broken pipe']):
                print(f'[{name}]: {output.rstrip()}',flush=True)
            if any(err in output for err in ['requests.exceptions.HTTPError','Broken pipe','Conversion failed!']):
                break
        print(f'[{name}]: Killing ffmpeg...',flush=True)
        ffmpeg.kill()
        sleep(1)

for camera in get_camera_list(auth_info):
    Thread(target=rtsp_server, args=(camera.nickname,)).start()