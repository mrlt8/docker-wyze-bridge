from wyzecam import login, get_camera_list
import os,subprocess,concurrent.futures

auth_info = login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
def rtsp_server(name):
    while True:
        print(f'starting rtsp server for {name}...')
        os.environ["WYZE_CAMERA_NAME"] = name
        os.environ["RTMP_URL"] = 'rtmp://rtsp-server:1935/' + name.replace(' ', '-').lower()
        subprocess.call(['python', '/opt/wyzecam/wyzecam-to-rtmp.py']).wait()
with concurrent.futures.ThreadPoolExecutor() as executor:
    for camera in get_camera_list(auth_info):
        executor.submit(rtsp_server, camera.nickname)