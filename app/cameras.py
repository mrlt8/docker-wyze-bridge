from wyzecam import login, get_camera_list
import os,subprocess,threading,time

auth_info = login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
def rtsp_server(name):
    while True:
        print(f'[{name}]: Starting...',flush=True)
        os.environ["WYZE_CAMERA_NAME"] = name
        os.environ["RTMP_URL"] = 'rtmp://rtsp-server:1935/' + name.replace(' ', '-').lower()
        ffmpeg = subprocess.Popen(['python', '/opt/wyzecam/wyzecam-to-rtmp.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        while True:
            output = ffmpeg.stdout.readline().rstrip()
            if not output:
                break
            if 'DEBUG_FFMPEG' in os.environ:
                print(f'[{name}]: {output.rstrip()}')
                continue
            if 'requests.exceptions.HTTPError' in output:
                print(f'[{name}]: {output.rstrip()}',flush=True)
                ffmpeg.kill()
                break
            if os.environ["RTMP_URL"] in output:
                print(f'[{name}]: {output.rstrip()}',flush=True)
            if 'Conversion failed!' in output:
                print(f'[{name}]: {output.rstrip()}',flush=True)
                ffmpeg.kill()
                break
        time.sleep(10)

for camera in get_camera_list(auth_info):
    threading.Thread(target=rtsp_server, args=(camera.nickname,)).start()