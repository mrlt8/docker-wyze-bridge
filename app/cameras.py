from wyzecam import login, get_camera_list
from subprocess import Popen, PIPE, STDOUT
from threading import Thread
from os import environ
from time import sleep

auth_info = login(environ["WYZE_EMAIL"], environ["WYZE_PASSWORD"])

def get_env(env):
    if env not in environ or not environ[env]:
        return []
    return [x.strip().upper().replace(':','') for x in environ[env].split(',')] if ',' in environ[env] else [environ[env].strip().upper().replace(':','')]
def filter_cam(cam):
	if cam.nickname.upper() in get_env('FILTER_NAMES') or cam.mac in get_env('FILTER_MACS') or cam.product_model in get_env('FILTER_MODEL'):
		return True
def filtered_cameras(cams = get_camera_list(auth_info)):
    if 'FILTER_MODE' in environ and environ['FILTER_MODE'].upper() in ('BLOCK','BLACKLIST','EXCLUDE','IGNORE','REVERSE'):
        print('BLACKLIST MODE ON')
        return filter(lambda cam: not filter_cam(cam),cams)
    if any(key.startswith('FILTER_') for key in environ):		
        print('WHITELIST MODE ON')
        return filter(filter_cam,cams)
    return cams 
       
def rtsp_server(name):
    while True:
        print(f'[{name}]: Starting...',flush=True)
        url = 'rtmp://rtsp-server:1935/' + name.replace(' ', '-').lower()
        ffmpeg = Popen(['python', '/opt/wyzecam/wyzecam-to-rtmp.py'], env={**environ,"WYZE_CAMERA_NAME": name,"RTMP_URL": url},stdout=PIPE,stderr=STDOUT, text=True)
        while ffmpeg.poll() is None:
            output = ffmpeg.stdout.readline().rstrip()
            if not output:
                continue
            if 'DEBUG_FFMPEG' in environ or any(err in output for err in [url, 'requests.exceptions.HTTPError','Broken pipe','Conversion failed!']):
                print(f'[{name}]: {output.rstrip()}',flush=True)
            if 'DEBUG_NOKILL' not in environ and any(err in output for err in ['requests.exceptions.HTTPError','Broken pipe','Conversion failed!']):
                break
        print(f'[{name}]: Killing ffmpeg...',flush=True)
        ffmpeg.kill()
        sleep(1)

for camera in filtered_cameras():
    Thread(target=rtsp_server, args=(camera.nickname,)).start()