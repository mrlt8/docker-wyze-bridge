import wyzecam, gc, time, subprocess, multiprocessing, warnings, os, datetime, pickle

class wyze_bridge:
	def __init__(self):
		print('STARTING DOCKER-WYZE-BRIDGE v0.3.0', flush=True)

	if 'DEBUG_FFMPEG' not in os.environ:
		warnings.filterwarnings("ignore")

	model_names = {'WYZECP1_JEF':'PAN','WYZEC1':'V1','WYZEC1-JZ':'V2','WYZE_CAKP2JFUS':'V3','WYZEDB3':'DOORBELL','WVOD1':'OUTDOOR'}

	def get_env(env):
		return [] if not os.environ.get(env) else [x.strip().upper().replace(':','') for x in os.environ[env].split(',')] if ',' in os.environ[env] else [os.environ[env].strip().upper().replace(':','')]

	def env_filter(self,cam):
		return True if cam.nickname.upper() in self.get_env('FILTER_NAMES') or cam.mac in self.get_env('FILTER_MACS') or cam.product_model in self.get_env('FILTER_MODEL') or self.model_names.get(cam.product_model) in self.get_env('FILTER_MODEL') else False

	def authWyze(self,name):
		try:
			if os.environ.get('FRESH_DATA') and ('auth' not in name or not hasattr(self,'auth')):
				raise Exception
			print(f'Fetching {name} data from local cache...')
			return pickle.load(open(f"/opt/wyzecam/tokens/{name}.pickle", "rb"))
		except Exception:
			if not hasattr(self,'auth') and 'auth' not in name:
				self.authWyze('auth')
			while True:
				try:
					print(f'Fetching {name} data from wyze...')
					if 'auth' in name:
						self.auth = data =  wyzecam.login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
					if 'user' in name:
						data = wyzecam.get_user_info(self.auth)
					if 'cameras' in name:
						data = wyzecam.get_camera_list(self.auth)
					pickle.dump(data, open(f"/opt/wyzecam/tokens/{name}.pickle", "wb"))
					return data
				except Exception as ex:
					print(f'{ex}\nSleeping for 10s...')
					time.sleep(10)

	def filtered_cameras(self):
		cams = self.authWyze('cameras')
		if 'FILTER_MODE' in os.environ and os.environ['FILTER_MODE'].upper() in ('BLOCK','BLACKLIST','EXCLUDE','IGNORE','REVERSE'):
			filtered = list(filter(lambda cam: not self.env_filter(cam),cams))
			if len(filtered) >0:
				print(f'BLACKLIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS ')
				return filtered
		if any(key.startswith('FILTER_') for key in os.environ):		
			filtered = list(filter(self.env_filter,cams))
			if len(filtered) > 0:
				print(f'WHITELIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS')
				return filtered
		print(f'STARTING ALL {len(cams)} CAMERAS')
		return cams

	def start_stream(self,camera):
		while True:
			try:
				tutk_library = wyzecam.tutk.tutk.load_library()
				resolution = 3 if camera.product_model == 'WYZEDB3' else 0
				bitrate = 120
				res = 'HD'
				if os.environ.get('QUALITY'):
					if 'SD' in os.environ['QUALITY'][:2].upper():
						resolution +=1
						res = 'SD'
					if os.environ['QUALITY'][2:].isdigit() and 30 <= int(os.environ['QUALITY'][2:]) <= 240:
						# bitrate = min([30,60,120,150,240], key=lambda x:abs(x-int(os.environ['QUALITY'][2:])))
						bitrate = int(os.environ['QUALITY'][2:])
				wyzecam.tutk.tutk.iotc_initialize(tutk_library)
				wyzecam.tutk.tutk.av_initialize(tutk_library)	
				with wyzecam.iotc.WyzeIOTCSession(tutk_library,self.user,camera,resolution,bitrate) as sess:
					print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Starting {res} {bitrate}kb/s Stream for WyzeCam {self.model_names.get(camera.product_model)} ({camera.product_model}) running FW: {sess.camera.camera_info["basicInfo"]["firmware"]} from {camera.ip} (Wifi: -{sess.camera.camera_info["basicInfo"]["wifidb"]} dBm)...',flush=True)
					cmd = ('ffmpeg ' + os.environ['FFMPEG_CMD'].strip("\'").strip('\"') + camera.nickname.replace(' ', '-').lower()).split() if os.environ.get('FFMPEG_CMD') else ['ffmpeg',
						'-hide_banner',
						# '-stats' if 'DEBUG_FFMPEG' in os.environ else '-nostats',
						'-nostats',
						'-loglevel','info' if 'DEBUG_FFMPEG' in os.environ else 'fatal',
						'-f', sess.camera.camera_info['videoParm']['type'].lower(),
						'-framerate', sess.camera.camera_info['videoParm']['fps'],
						'-i', '-',
						# '-b:v', str(bitrate)+'k',
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
				if 'tutk_library' in locals():
					wyzecam.tutk.tutk.av_deinitialize(tutk_library)
					wyzecam.tutk.tutk.iotc_deinitialize(tutk_library)
				gc.collect()
	def run(self):
		self.user = self.authWyze('user')
		for camera in self.filtered_cameras():
			multiprocessing.Process(target=self.start_stream, args=[camera]).start()

if __name__ == "__main__":
	wyze_bridge().run()