from wyzecam import login, get_camera_list
import os, subprocess

auth_info = login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
for camera in get_camera_list(auth_info):
    os.environ["WYZE_CAMERA_NAME"] = camera.nickname
    os.environ["RTMP_URL"] = 'rtmp://nginx:1935/stream/' + camera.nickname.replace(' ', '-').lower()
    subprocess.Popen(['python', '/opt/wyzecam/wyzecam-to-rtmp.py'], start_new_session=True)