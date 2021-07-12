import wyzecam, gc, time, subprocess, multiprocessing, warnings, os, datetime, pickle, sys, io, wyze_sdk

class wyze_bridge:
	def __init__(self):
		print('STARTING DOCKER-WYZE-BRIDGE v0.3-MFA', flush=True)
	
	if 'DEBUG_FFMPEG' not in os.environ:
		warnings.filterwarnings("ignore")

	model_names = {'WYZECP1_JEF':'PAN','WYZEC1':'V1','WYZEC1-JZ':'V2','WYZE_CAKP2JFUS':'V3','WYZEDB3':'DOORBELL','WVOD1':'OUTDOOR'}

	def get_env(self,env):
		return [] if not os.environ.get(env) else [x.strip().upper().replace(':','') for x in os.environ[env].split(',')] if ',' in os.environ[env] else [os.environ[env].strip().upper().replace(':','')]

	def env_filter(self,cam):
		return True if cam.nickname.upper() in self.get_env('FILTER_NAMES') or cam.mac in self.get_env('FILTER_MACS') or cam.product_model in self.get_env('FILTER_MODEL') or self.model_names.get(cam.product_model) in self.get_env('FILTER_MODEL') else False

	def twofactor(self):
		mfa_token = '/opt/wyzecam/tokens/mfa_token'
		print(f'MFA Token Required\nAdd token to {mfa_token}',flush=True)
		while True:
			if os.path.exists(mfa_token) and os.path.getsize(mfa_token) > 0:
				with open(mfa_token,'r+') as f:
					lines = f.read().strip()
					f.truncate(0)
					print(f'Using {lines} as token',flush=True)
					sys.stdin = io.StringIO(lines)
					try:
						response = wyze_sdk.Client(email=os.environ['WYZE_EMAIL'], password=os.environ['WYZE_PASSWORD'])
						return wyzecam.WyzeCredential.parse_obj({'access_token':response._token,'refresh_token':response._refresh_token,'user_id':response._user_id,'phone_id':response._api_client().phone_id})
					except Exception as ex:
						print(f'{ex}\nPlease try again!',flush=True)
			time.sleep(2)

	def authWyze(self,name):
		pkl_data = f'/opt/wyzecam/tokens/{name}.pickle'
		if os.environ.get('FRESH_DATA') and ('auth' not in name or not hasattr(self,'auth')):
			print(f'Forced Refresh of {name}!') 
		elif os.path.exists(pkl_data) and os.path.getsize(pkl_data) > 0:
			with(open(pkl_data,'rb')) as f:
				print(f'Fetching {name} data from local cache...',flush=True)
				return pickle.load(f)
		if not hasattr(self,'auth') and 'auth' not in name:
			self.authWyze('auth')
		while True:
			try:
				print(f'Fetching {name} data from wyze...',flush=True)
				if 'auth' in name:
					try:
						self.auth = data =  wyzecam.login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
					except ValueError as ex:
						for err in ex.errors():
							if 'mfa_options' in err['loc']:
								self.auth = data = self.twofactor()
					except Exception as ex:
						[print('Invalid credentials?',flush=True) for err in ex.args if '400 Client Error' in err]
						raise ex
				if 'user' in name:
					data = wyzecam.get_user_info(self.auth)
				if 'cameras' in name:
					data = wyzecam.get_camera_list(self.auth)
				with open(pkl_data,"wb") as f:
					pickle.dump(data, f)
				return data
			except Exception as ex:
				print(f'{ex}\nSleeping for 10s...')
				time.sleep(10)

	def filtered_cameras(self):
		cams = self.authWyze('cameras')
		if 'FILTER_MODE' in os.environ and os.environ['FILTER_MODE'].upper() in ('BLOCK','BLACKLIST','EXCLUDE','IGNORE','REVERSE'):
			filtered = list(filter(lambda cam: not self.env_filter(cam),cams))
			if len(filtered) >0:
				print(f'BLACKLIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS')
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
					print(f'{datetime.datetime.now().strftime("%Y/%m/%d %X")} [{camera.nickname}] Starting {res} {bitrate}kb/s Stream for WyzeCam {self.model_names.get(camera.product_model)} ({camera.product_model}) running FW: {sess.camera.camera_info["basicInfo"]["firmware"]} from {camera.ip} (WiFi Quality: {sess.camera.camera_info["basicInfo"]["wifidb"]}%)...',flush=True)
					cmd = ('ffmpeg ' + os.environ['FFMPEG_CMD'].strip("\'").strip('\"') + camera.nickname.replace(' ', '-').lower()).split() if os.environ.get('FFMPEG_CMD') else ['ffmpeg',
						'-hide_banner',
						# '-stats' if 'DEBUG_FFMPEG' in os.environ else '-nostats',
						'-nostats',
						'-loglevel','info' if 'DEBUG_FFMPEG' in os.environ else 'fatal',
						'-f', sess.camera.camera_info['videoParm']['type'].lower(),
						'-r', sess.camera.camera_info['videoParm']['fps'],
						'-err_detect','ignore_err',
						'-avioflags','direct',
						'-flags','low_delay',
						'-fflags','+flush_packets+genpts+discardcorrupt+nobuffer',
						'-i', '-',
						# '-b:v', str(bitrate)+'k',
						'-vcodec', 'copy', 
						'-rtsp_transport','tcp',
						'-f','rtsp', 'rtsp://rtsp-server:8554/' + camera.nickname.replace(' ', '-').lower()]
					ffmpeg = subprocess.Popen(cmd,stdin=subprocess.PIPE)
					while ffmpeg.poll() is None:
						for (frame,_) in sess.recv_video_data():
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