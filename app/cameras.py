from wyzecam import login, get_camera_list
from subprocess import Popen, PIPE, STDOUT
from threading import Thread
from os import environ
from time import sleep
from datetime import datetime

auth_info = login(environ["WYZE_EMAIL"], environ["WYZE_PASSWORD"])

def get_env(env):
    return [] if env not in environ or not environ[env] else [x.strip().upper().replace(':','') for x in environ[env].split(',')] if ',' in environ[env] else [environ[env].strip().upper().replace(':','')]
def filter_cam(cam):
	return True if cam.nickname.upper() in get_env('FILTER_NAMES') or cam.mac in get_env('FILTER_MACS') or cam.product_model in get_env('FILTER_MODEL') else False
def filtered_cameras(cams = get_camera_list(auth_info)):
    if 'FILTER_MODE' in environ and environ['FILTER_MODE'].upper() in ('BLOCK','BLACKLIST','EXCLUDE','IGNORE','REVERSE'):
        filtered = list(filter(lambda cam: not filter_cam(cam),cams))
        print(f'BLACKLIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS')
        return filtered
    if any(key.startswith('FILTER_') for key in environ):		
        filtered = list(filter(filter_cam,cams))
        print(f'WHITELIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS')
        return filtered
    print(f'STARTING ALL {len(cams)} CAMERAS')
    return cams
def rtsp_server(camera):
    while True:
        print(f'{datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Starting Camera ({camera.product_model}) on {camera.ip}...',flush=True)
        url = 'rtmp://rtsp-server:1935/' + camera.nickname.replace(' ', '-').lower()
        ffmpeg = Popen(['python', '/opt/wyzecam/wyzecam-to-rtmp.py'], env={**environ,"WYZE_CAMERA_NAME": camera.nickname,"RTMP_URL": url},stdout=PIPE,stderr=STDOUT,text=True)
        while ffmpeg.poll() is None:
            output = ffmpeg.stdout.readline().rstrip()
            if not output:
                continue
            if 'DEBUG_FFMPEG' in environ or any(err in output for err in [url, 'requests.exceptions.HTTPError','Broken pipe','AV_ER_REMOTE_TIMEOUT_DISCONNECT']):
                print(f'{datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] {output.rstrip()}',flush=True)
            if 'DEBUG_NOKILL' not in environ and any(err in output for err in ['requests.exceptions.HTTPError','Broken pipe','AV_ER_REMOTE_TIMEOUT_DISCONNECT']):
                break
        print(f'{datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Killing FFmpeg...',flush=True)
        ffmpeg.kill()
        sleep(1)

for camera in filtered_cameras():
    Thread(target=rtsp_server, args=(camera,)).start()