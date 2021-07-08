import wyzecam, gc, time, subprocess, multiprocessing, warnings, os, datetime

if 'DEBUG_FFMPEG' not in os.environ:
	warnings.filterwarnings("ignore")
model_names = {'WYZECP1_JEF':'PAN','WYZEC1':'V1','WYZEC1-JZ':'V2','WYZE_CAKP2JFUS':'V3','WYZEDB3':'DOORBELL','WVOD1':'OUTDOOR'}


def get_env(env):
	return [] if not os.environ.get(env) else [x.strip().upper().replace(':','') for x in os.environ[env].split(',')] if ',' in os.environ[env] else [os.environ[env].strip().upper().replace(':','')]
def env_filter(cam):
	return True if cam.nickname.upper() in get_env('FILTER_NAMES') or cam.mac in get_env('FILTER_MACS') or cam.product_model in get_env('FILTER_MODEL') or model_names.get(cam.product_model) in get_env('FILTER_MODEL') else False
def login():
	while True:
		try:
			return wyzecam.login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
		except Exception as ex:
			print(f'{ex}\nSleeping for 10s...',flush=True)
			time.sleep(10)
def filtered_cameras(cams = wyzecam.get_camera_list(login())):
	if 'FILTER_MODE' in os.environ and os.environ['FILTER_MODE'].upper() in ('BLOCK','BLACKLIST','EXCLUDE','IGNORE','REVERSE'):
		filtered = list(filter(lambda cam: not env_filter(cam),cams))
		if len(filtered) >0:
			print(f'BLACKLIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS')
			return filtered
	if any(key.startswith('FILTER_') for key in os.environ):		
		filtered = list(filter(env_filter,cams))
		if len(filtered) > 0:
			print(f'WHITELIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS')
			return filtered
	print(f'STARTING ALL {len(cams)} CAMERAS')
	return cams
def start_stream(camera):
	while True:
		try:
			with wyzecam.WyzeIOTC() as iotc, iotc.connect_and_auth(wyzecam.get_user_info(login()), camera) as sess:
				print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Starting WyzeCam {model_names.get(camera.product_model)} ({camera.product_model}) running FW: {sess.camera.camera_info["basicInfo"]["firmware"]} on {camera.ip} (Wifi: -{sess.camera.camera_info["basicInfo"]["wifidb"]} dBm)...',flush=True)
				cmd = ('ffmpeg ' + os.environ['FFMPEG_CMD'].strip("\'").strip('\"') + camera.nickname.replace(' ', '-').lower()).split() if os.environ.get('FFMPEG_CMD') else ['ffmpeg',
					'-hide_banner',
					# '-stats' if 'DEBUG_FFMPEG' in os.environ else '-nostats',
					'-nostats',
					'-loglevel','info' if 'DEBUG_FFMPEG' in os.environ else 'fatal',
					'-f', sess.camera.camera_info['videoParm']['type'].lower(),
					'-framerate', sess.camera.camera_info['videoParm']['fps'],
					'-i', '-',
					'-vcodec', 'copy', 
					'-f','rtsp', 'rtsp://rtsp-server:8554/' + camera.nickname.replace(' ', '-').lower()]
				ffmpeg = subprocess.Popen(cmd,stdin=subprocess.PIPE)
				while ffmpeg.poll() is None:
					for frame in next(sess.recv_video_data()):
						try:
							ffmpeg.stdin.write(frame)
						except Exception as ex:
							print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] [FFMPEG] {ex}',flush=True)
							break
		except Exception as ex:
			print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] {ex}',flush=True)
			if str(ex) == 'IOTC_ER_CAN_NOT_FIND_DEVICE':
				print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Camera offline? Sleeping for 10s.',flush=True)
				time.sleep(10)
		finally:
			if 'ffmpeg' in locals():
				print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Killing FFmpeg...',flush=True)
				ffmpeg.kill()
				time.sleep(0.5)
				ffmpeg.wait()
			if 'iotc' in locals():
				iotc.deinitialize()
			gc.collect()

print('STARTING DOCKER-WYZE-BRIDGE v0.2.2',flush=True)
for camera in filtered_cameras():
	multiprocessing.Process(target=start_stream, args=[camera]).start()