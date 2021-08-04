import wyzecam, gc, time, subprocess, threading, warnings, os, pickle, sys, logging

if 'DEBUG_LEVEL' in os.environ:
	logging.basicConfig(format='%(asctime)s %(name)s - %(levelname)s - %(message)s',datefmt='%Y/%m/%d %X', stream=sys.stdout, level=os.environ.get('DEBUG_LEVEL').upper())
if 'DEBUG_LEVEL' not in os.environ or 'DEBUG_FFMPEG' not in os.environ:
	warnings.filterwarnings("ignore")
handler = logging.StreamHandler(stream=sys.stdout)
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter('%(asctime)s %(message)s','%Y/%m/%d %X'))
log = logging.getLogger('wyze_bridge')
log.addHandler(handler)
log.setLevel(logging.INFO)

class wyze_bridge:
	def __init__(self):
		print('STARTING DOCKER-WYZE-BRIDGE v0.5.1')
		if 'DEBUG_LEVEL' in os.environ:
			print(f'DEBUG_LEVEL set to {os.environ.get("DEBUG_LEVEL")}')

	model_names = {'WYZECP1_JEF':'PAN','WYZEC1':'V1','WYZEC1-JZ':'V2','WYZE_CAKP2JFUS':'V3','WYZEDB3':'DOORBELL','WVOD1':'OUTDOOR'}

	def get_env(self,env):
		return [] if not os.environ.get(env) else [x.strip().upper().replace(':','') for x in os.environ[env].split(',')] if ',' in os.environ[env] else [os.environ[env].strip().upper().replace(':','')]

	def env_filter(self,cam):
		return True if cam.nickname.upper() in self.get_env('FILTER_NAMES') or cam.mac in self.get_env('FILTER_MACS') or cam.product_model in self.get_env('FILTER_MODEL') or self.model_names.get(cam.product_model) in self.get_env('FILTER_MODEL') else False

	def wyze_login(self):
		phone_id = str(wyzecam.api.uuid.uuid4())
		payload = {"email": os.environ['WYZE_EMAIL'], "password": wyzecam.api.triplemd5(os.environ['WYZE_PASSWORD'])}
		response = wyzecam.api.requests.post(
		"https://auth-prod.api.wyze.com/user/login",
			json=payload,
			headers=wyzecam.api.get_headers(phone_id),
		)
		response.raise_for_status()
		if response.json()['mfa_options'] is not None:
			mfa_token = '/tokens/mfa_token'
			log.warn(f'MFA Token Required\nAdd token to {mfa_token}')
			while response.json()['access_token'] is None:
				json_resp = response.json()
				# Request SMS code
				if 'PrimaryPhone' in json_resp['mfa_options']:
					sms_resp = wyzecam.api.requests.post(
					"https://auth-prod.api.wyze.com/user/login/sendSmsCode",
						json={},
						params={'mfaPhoneType': 'Primary', 'sessionId': json_resp['sms_session_id'],'userId': json_resp['user_id']},
						headers=wyzecam.api.get_headers(phone_id),
					)
					sms_resp.raise_for_status()
				while True:
					if os.path.exists(mfa_token) and os.path.getsize(mfa_token) > 0:
						with open(mfa_token,'r+') as f:
							verification_code = f.read().strip()
							f.truncate(0)
							log.warn(f'Using {verification_code} as verification code')
							try:
								resp = wyzecam.api.requests.post(
									"https://auth-prod.api.wyze.com/user/login",
									json={
										'email': os.environ['WYZE_EMAIL'],
										'password': wyzecam.api.triplemd5(os.environ['WYZE_PASSWORD']),
										'mfa_type': json_resp['mfa_options'][0],
										'verification_id': sms_resp.json()['session_id'] if 'sms_resp' in vars() else json_resp['mfa_details']['totp_apps'][0]['app_id'],
										'verification_code': verification_code,
									},
									headers=wyzecam.api.get_headers(phone_id),
									# nonce=round(time.time() * 1000),
								)
								resp.raise_for_status()
								if 'access_token' in resp.json():
									response = resp
							except Exception as ex:
								[log.warn('Wrong Code?') for err in ex.args if '400 Client Error' in err]
								log.warn(f'Error: {ex}\nPlease try again!')
						break
					time.sleep(2)
		return wyzecam.api_models.WyzeCredential.parse_obj(dict(response.json(), phone_id=phone_id))

	def authWyze(self,name):
		pkl_data = f'/tokens/{name}.pickle'
		if os.path.exists(pkl_data) and os.path.getsize(pkl_data) > 0:
			if os.environ.get('FRESH_DATA') and ('auth' not in name or not hasattr(self,'auth')):
				print(f'[FORCED REFRESH] Removing local cache for {name}!')
				os.remove(pkl_data)
			else:
				with(open(pkl_data,'rb')) as f:
					print(f'Fetching {name} from local cache...')
					return pickle.load(f)
		else:
			print(f'Could not find local cache for {name}')
		if not hasattr(self,'auth') and 'auth' not in name:
			self.authWyze('auth')
		while True:
			try:
				print(f'Fetching {name} from wyze api...')
				if 'auth' in name:
					try:
						self.auth = data = self.wyze_login()
					except Exception as ex:
						[print('Invalid credentials?') for err in ex.args if '400 Client Error' in err]
						raise ex
				if 'user' in name:
					data = wyzecam.get_user_info(self.auth)
				if 'cameras' in name:
					data = wyzecam.get_camera_list(self.auth)
				with open(pkl_data,"wb") as f:
					print(f'Saving {name} to local cache...')
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
				resolution = 3 if camera.product_model == 'WYZEDB3' else 0
				bitrate = 120
				res = 'HD'
				iotc = [self.iotc.tutk_platform_lib,self.user,camera]
				if os.environ.get('QUALITY'):
					if 'SD' in os.environ['QUALITY'][:2].upper():
						resolution +=1
						res = 'SD'
					if os.environ['QUALITY'][2:].isdigit() and 30 <= int(os.environ['QUALITY'][2:]) <= 240:
						# bitrate = min([30,60,120,150,240], key=lambda x:abs(x-int(os.environ['QUALITY'][2:])))
						bitrate = int(os.environ['QUALITY'][2:])
					iotc.extend((resolution,bitrate))
				with wyzecam.iotc.WyzeIOTCSession(*iotc) as sess:
					if sess.session_check().mode != 2:
						if os.environ.get('LAN_ONLY'):
							raise Exception('NON-LAN MODE')
						log.warn(f'[{camera.nickname}] WARNING: Camera is connected via "{"P2P" if sess.session_check().mode ==0 else "Relay" if sess.session_check().mode == 1 else "LAN" if sess.session_check().mode == 2 else "Other ("+sess.session_check().mode+")" } mode". Stream may consume additional bandwidth!')
					log.info(f'[{camera.nickname}] Starting {res} {bitrate}kb/s Stream for WyzeCam {self.model_names.get(camera.product_model)} ({camera.product_model}) in "{"P2P" if sess.session_check().mode ==0 else "Relay" if sess.session_check().mode == 1 else "LAN" if sess.session_check().mode == 2 else "Other ("+sess.session_check().mode+")" } mode" FW: {sess.camera.camera_info["basicInfo"]["firmware"]} IP: {camera.ip} WiFi: {sess.camera.camera_info["basicInfo"]["wifidb"]}%')
					cmd = ('ffmpeg ' + os.environ['FFMPEG_CMD'].strip("\'").strip('\"') + camera.nickname.replace(' ', '-').replace('#', '').lower()).split() if os.environ.get('FFMPEG_CMD') else ['ffmpeg',
						'-hide_banner',
						'-nostats',
						'-loglevel','info' if 'DEBUG_FFMPEG' in os.environ else 'fatal',
						# '-f','h265',
						# '-f', sess.camera.camera_info['videoParm']['type'] if 'type' in sess.camera.camera_info['videoParm'] else 'h264',
						# '-r', sess.camera.camera_info['videoParm']['fps'],
						# '-err_detect','ignore_err',
						# '-avioflags','direct',
						# '-flags','low_delay',
						# '-fflags','+flush_packets+genpts+discardcorrupt+nobuffer',
						'-i', '-',
						# '-map','0:v:0',
						'-vcodec', 'copy',
						'-rtsp_transport','tcp' if ('RTSP_PROTOCOLS' in os.environ and 'tcp' in os.environ.get('RTSP_PROTOCOLS')) else 'udp',
						'-f','rtsp', 'rtsp://0.0.0.0' + (os.environ.get('RTSP_RTSPADDRESS') if 'RTSP_RTSPADDRESS' in os.environ else ':8554') + '/' + camera.nickname.replace(' ', '-').replace('#', '').lower()]
					ffmpeg = subprocess.Popen(cmd,stdin=subprocess.PIPE)
					while ffmpeg.poll() is None:
						for (frame,_) in sess.recv_video_data():
							try:
								ffmpeg.stdin.write(frame)
							except Exception as ex:
								raise Exception(f'[FFMPEG] {ex}')
			except Exception as ex:
				log.info(f'[{camera.nickname}] {ex}')
				if str(ex) == 'IOTC_ER_DEVICE_OFFLINE':
					if 'IGNORE_OFFLINE' in os.environ:
						log.info(f'[{camera.nickname}] Camera is offline. Will NOT try again until container restarts.')
						sys.exit()
					offline_time = (offline_time+10 if offline_time < 600 else 30) if 'offline_time' in vars() else 10
					log.info(f'[{camera.nickname}] Camera is offline. Will retry again in {offline_time}s.')
					time.sleep(offline_time)
			finally:
				if 'ffmpeg' in locals():
					log.info(f'[{camera.nickname}] Cleaning up FFmpeg...')
					ffmpeg.kill()
					time.sleep(0.5)
					ffmpeg.wait()
				gc.collect()
	def run(self):
		self.user = self.authWyze('user')
		self.cameras = self.filtered_cameras()
		self.iotc = wyzecam.WyzeIOTC(max_num_av_channels=len(self.cameras)).__enter__()
		for camera in self.cameras:
			threading.Thread(target=self.start_stream, args=[camera]).start()

if __name__ == "__main__":
	wyze_bridge().run()