"""Offline tests: fake helper only; no Wyze SDK, cloud or camera access."""
import ast
import base64
from functools import wraps
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask, redirect
from flask_httpauth import HTTPBasicAuth

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from wyzebridge import sd_download as sd

FAKE_HELPER = r'''
import argparse,json,os,pathlib,stat,sys
p=argparse.ArgumentParser()
p.add_argument('--live',action='store_true')
for key in ('credentials','download','media-output','output','max-bytes'): p.add_argument('--'+key,required=True)
a=p.parse_args(); credentials=pathlib.Path(a.credentials); data=json.loads(credentials.read_text())
assert set(data)=={'ip','uid','enr','mac','model'}
assert stat.S_IMODE(credentials.stat().st_mode)==0o600
assert stat.S_IMODE(credentials.parent.stat().st_mode)==0o700
assert int(a.max_bytes)==16777216
pathlib.Path(os.environ['DWB_FAKE_CAPTURE']).write_text(json.dumps({'directory':str(credentials.parent),'keys':sorted(data),'argv':sys.argv[1:]}))
mode=os.environ.get('DWB_FAKE_MODE','success'); media=pathlib.Path(a.media_output)
payload=b'\x00\x00\x00\x18ftypmp42offline-fixture'
if mode=='contract': payload=b'offline-fixture'
if mode=='symlink': media.symlink_to(credentials)
elif mode=='mediafifo': os.mkfifo(media,0o600)
else:
 fd=os.open(media,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'wb') as f: f.write(payload)
result={'phase':'download_complete','operation':'download_sd_file','recording_path':a.download,'downloaded_bytes':len(payload),'elapsed_seconds':0.01}
if mode=='contract': result=json.loads(pathlib.Path(os.environ['DWB_FAKE_RESULT']).read_text())
if mode=='partial': result['phase']='download_sd_file'; result['error']='PRIVATE_PEER_TEXT'
if mode=='wrongpath': result['recording_path']='/media/mmc/record/20000101/00/00.mp4'
if mode=='size': result['downloaded_bytes']+=1
if mode=='oversize': result['downloaded_bytes']=16777217
if mode=='missingop': result.pop('operation')
if mode=='missing': result['error']='file does not exist'
if mode=='resultfifo': os.mkfifo(a.output,0o600)
elif mode=='duplicate': pathlib.Path(a.output).write_text('{"phase":"bad","phase":"download_complete"}')
else: pathlib.Path(a.output).write_text(json.dumps(result))
sys.exit(1 if mode in ('partial','missing') else 0)
'''


@unittest.skipUnless(os.name == "posix", "Docker helper requires POSIX private files")
class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dwb-adapter-test-")
        self.root = Path(self.tmp.name)
        self.helper = self.root / "fake-helper"
        self.helper.write_text("#!" + sys.executable + "\n" + FAKE_HELPER)
        self.helper.chmod(0o700)
        self.capture = self.root / "capture.json"
        self.env = patch.dict(os.environ, {"SD_DOWNLOAD_HELPER": str(self.helper),
                                          "DWB_FAKE_CAPTURE": str(self.capture), "DWB_FAKE_MODE": "success",
                                          "DWB_FAKE_RESULT": str(Path(__file__).parent / "fixtures/sd-helper-result.json")})
        self.env.start()
        self.camera = SimpleNamespace(ip="192.168.1.10", dtls=1, p2p_id="ABCDEFGHIJKLMNOPQRST",
                                      enr="PRIVATE_ENR_TEST", mac="AABBCCDDEEFF", product_model="WYZE_CAKP2JFUS")
        self.stream = SimpleNamespace(camera=self.camera)
        self.bridge = SimpleNamespace(api=SimpleNamespace(auth=True),
                                      streams=SimpleNamespace(get=lambda name: self.stream if name == "test" else None))
        auth = HTTPBasicAuth()
        auth.verify_password(lambda username, password: username == "tester" and password == "fixture")
        # Exercise the actual frontend auth_required definition without importing
        # or starting WyzeBridge/the SDK. Only this function's AST is executed.
        source = ast.parse((Path(__file__).resolve().parents[1] / "app/frontend.py").read_text())
        definition = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == "auth_required")
        namespace = {"wraps": wraps, "wb": self.bridge, "web_ui": SimpleNamespace(auth=auth),
                     "redirect": redirect, "url_for": lambda name: "/login"}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])), "frontend-auth", "exec"), namespace)
        self.app = Flask(__name__)
        self.app.testing = True
        sd.register_sd_download(self.app, self.bridge, namespace["auth_required"])
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Basic " + base64.b64encode(b"tester:fixture").decode()}
        self.body = {"date": "20261030", "hour": "03", "minute": 4}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def post(self, **kwargs):
        return self.client.post("/api/test/sd/recording", headers=self.headers,
                                **(kwargs or {"json": self.body}))

    def test_auth_and_bridge_state_block_helper(self):
        self.assertEqual(self.client.post("/api/test/sd/recording", json=self.body).status_code, 401)
        self.bridge.api.auth = None
        self.assertEqual(self.post().status_code, 302)
        self.assertFalse(self.capture.exists())

    def test_disabled_unknown_camera_and_invalid_pairing(self):
        with patch.dict(os.environ, {"SD_DOWNLOAD_HELPER": ""}):
            self.assertEqual(self.post().status_code, 501)
        with patch.dict(os.environ, {"SD_DOWNLOAD_HELPER": "relative-helper"}):
            self.assertEqual(self.post().status_code, 503)
        response = self.client.post("/api/missing/sd/recording", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.camera.ip = "127.0.0.1"
        self.assertEqual(self.post().status_code, 422)
        self.assertFalse(self.capture.exists())

    def test_strict_request_rejection_before_helper(self):
        cases = [dict(self.body, date="20260229"), dict(self.body, hour=True),
                 dict(self.body, minute=60), dict(self.body, hour="../1"),
                 dict(self.body, path="/etc/passwd"), dict(self.body, new="true"),
                 dict(self.body, minute=1.5), {"date": "20261030"}, []]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.post(json=body).status_code, 400)
        self.assertEqual(self.post(data='{"date":"20261030","date":"20261031","hour":1,"minute":2}', content_type="application/json").status_code, 400)
        self.assertEqual(self.post(data="x"*1025, content_type="application/json").status_code, 413)
        self.assertEqual(self.post(data="plain").status_code, 415)
        self.assertFalse(self.capture.exists())

    def test_success_holds_private_files_and_lock_until_response_close(self):
        response = self.post(json=dict(self.body, new=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("20261030-0304_new.mp4", response.headers["Content-Disposition"])
        capture = json.loads(self.capture.read_text())
        scratch = Path(capture["directory"])
        self.assertTrue(scratch.exists())
        self.assertNotIn("PRIVATE_ENR_TEST", str(capture["argv"]))
        self.assertEqual(self.post().status_code, 409)
        self.assertIn(b"offline-fixture", response.data)
        response.close()
        response.close()
        self.assertFalse(scratch.exists())
        self.assertTrue(sd._download_lock.acquire(blocking=False))
        sd._download_lock.release()

    def test_partial_mismatched_oversized_symlink_or_duplicate_output_never_served(self):
        for mode in ("partial", "wrongpath", "size", "oversize", "symlink", "duplicate", "missingop", "resultfifo", "mediafifo"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"DWB_FAKE_MODE": mode}):
                response = self.post()
                self.assertEqual(response.status_code, 502)
                self.assertNotIn(b"PRIVATE", response.data)
                self.assertFalse(Path(json.loads(self.capture.read_text())["directory"]).exists())

    def test_actual_go_helper_result_schema(self):
        # Generated offline by marshaling the example helper's actual Go result
        # struct, rather than by copying this fake helper's dictionary schema.
        with patch.dict(os.environ, {"DWB_FAKE_MODE": "contract"}):
            response = self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"offline-fixture")
            response.close()

    def test_missing_and_timeout_cleanup(self):
        with patch.dict(os.environ, {"DWB_FAKE_MODE": "missing"}):
            self.assertEqual(self.post().status_code, 404)
        with patch.object(sd.subprocess, "run", side_effect=subprocess.TimeoutExpired("PRIVATE", 65)) as run:
            response = self.post()
            scratch = Path(run.call_args.args[0][run.call_args.args[0].index("--credentials")+1]).parent
            self.assertEqual(response.status_code, 504)
            self.assertEqual(run.call_args.kwargs["timeout"], 65)
            self.assertFalse(scratch.exists())
            self.assertNotIn(b"PRIVATE", response.data)


if __name__ == "__main__":
    unittest.main()
