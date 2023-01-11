import logging
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from flask_httpauth import HTTPBasicAuth
from werkzeug.exceptions import NotFound
from werkzeug.security import check_password_hash, generate_password_hash
from wyze_bridge import WyzeBridge, setup_logging

log = logging.getLogger(__name__)
wb: WyzeBridge = None
auth = HTTPBasicAuth()
auth_enabled = os.getenv("WEB_AUTH", "false").lower() != "false"
if auth_enabled:
    user = os.getenv("WEB_USERNAME", os.getenv("WYZE_EMAIL"))
    pw = generate_password_hash(os.getenv("WEB_PASSWORD", os.getenv("WYZE_PASSWORD")))


def clean_up():
    """Run cleanup before exit."""
    if not wb:
        sys.exit(0)
    wb.clean_up()


signal.signal(signal.SIGTERM, lambda *_: clean_up())


@auth.verify_password
def verify_password(username, password):
    if not auth_enabled:
        return True
    return check_password_hash(pw, password) if username == user else False


def create_app():
    setup_logging()
    app = Flask(__name__)
    global wb
    if not wb:
        wb = WyzeBridge()
        wb.start()

    @app.route("/")
    @auth.login_required
    def index():
        if not (columns := request.args.get("columns")):
            columns = request.cookies.get("number_of_columns", "2")
        if not (refresh := request.args.get("refresh")):
            refresh = request.cookies.get("refresh_period", "30")
        number_of_columns = int(columns) if columns.isdigit() else 0
        refresh_period = int(refresh) if refresh.isdigit() else 0
        show_video = bool(request.cookies.get("show_video"))
        autoplay = bool(request.cookies.get("autoplay"))
        if "autoplay" in request.args:
            autoplay = True

        if "video" in request.args:
            show_video = True
        elif "snapshot" in request.args:
            show_video = False
        resp = make_response(
            render_template(
                "index.html",
                cameras=wb.get_cameras(urlparse(request.root_url).hostname),
                number_of_columns=number_of_columns,
                refresh_period=refresh_period,
                hass=wb.hass,
                version=wb.version,
                webrtc=bool(wb.bridge_ip),
                show_video=show_video,
                autoplay=autoplay,
            )
        )

        resp.set_cookie("number_of_columns", str(number_of_columns))
        resp.set_cookie("refresh_period", str(refresh_period))
        resp.set_cookie("show_video", "1" if show_video else "")
        fullscreen = "fullscreen" in request.args or bool(
            request.cookies.get("fullscreen")
        )
        resp.set_cookie("fullscreen", "1" if fullscreen else "")
        if order := request.args.get("order"):
            resp.set_cookie("camera_order", order)

        return resp

    @app.route("/mfa/<path:mfa_code>")
    def set_mfa_code(mfa_code):
        """Set mfa code."""
        if len(mfa_code) != 6:
            return {"error": f"Wrong length: {len(mfa_code)}"}
        return {"success" if wb.set_mfa(mfa_code) else "error": f"Using: {mfa_code}"}

    @app.route("/api/sse_status")
    def sse_status():
        """Server sent event for camera status."""
        return Response(wb.sse_status(), mimetype="text/event-stream")

    @app.route("/api")
    @app.route("/api/<path:cam_name>")
    @app.route("/api/<path:cam_name>/<path:cam_cmd>")
    def api(cam_name=None, cam_cmd=None):
        """JSON api endpoints."""
        if cam_name and cam_cmd == "status":
            return {"status": wb.get_cam_status(cam_name)}
        if cam_name and cam_cmd == "start":
            return {"success": wb.start_on_demand(cam_name)}
        if cam_name and cam_cmd == "stop":
            return {"success": wb.stop_on_demand(cam_name)}
        if cam_name and cam_cmd:
            return wb.cam_cmd(cam_name, cam_cmd)

        host = urlparse(request.root_url).hostname
        return wb.get_cam_info(cam_name, host) if cam_name else wb.get_cameras(host)

    @app.route("/snapshot/<path:img_file>")
    def rtsp_snapshot(img_file: str):
        """Use ffmpeg to take a snapshot from the rtsp stream."""
        if wb.rtsp_snap(Path(img_file).stem, wait=True):
            return send_from_directory(wb.img_path, img_file)
        return redirect("/static/notavailable.svg", code=307)

    @app.route("/photo/<path:img_file>")
    def boa_photo(img_file: str):
        """Take a photo on the camera and grab it over the boa http server."""
        uri = Path(img_file).stem
        if photo := wb.boa_photo(uri):
            return send_from_directory(wb.img_path, f"{uri}_{photo[0]}")
        return redirect(f"/img/{img_file}", code=307)

    @app.route("/img/<path:img_file>")
    def img(img_file: str):
        """Serve static image if image exists else take a new snapshot from the rtsp stream."""
        try:
            return send_from_directory(wb.img_path, img_file)
        except NotFound:
            return rtsp_snapshot(img_file)

    @app.route("/restart/<string:restart_cmd>")
    def restart_bridge(restart_cmd: str):
        """
        Restart parts of the wyze-bridge.

        /restart/cameras:       Stop and start all enabled cameras.
        /restart/rtsp_server:   Stop and start rtsp-simple-server.
        /restart/all:           Stop and start all enabled cameras and rtsp-simple-server.
        """
        if restart_cmd == "cameras":
            wb.stop_cameras()
            wb.run()
        elif restart_cmd == "rtsp_server":
            wb.stop_rtsp_server()
            wb.start_rtsp_server()
        elif restart_cmd == "all":
            wb.stop_cameras()
            wb.stop_rtsp_server()
            wb.run(fresh_data=True)
            restart_cmd = "cameras,rtsp_server"
        else:
            return {"result": "error"}
        return {"result": "ok", "restart": restart_cmd.split(",")}

    @app.route("/cams.m3u8")
    def iptv_playlist():
        """
        Generate an m3u8 playlist with all enabled cameras.
        """
        hostname = urlparse(request.root_url).hostname
        cameras = wb.get_cameras(hostname)["cameras"]
        resp = make_response(render_template("m3u8.html", cameras=cameras))
        resp.headers.set("content-type", "application/x-mpegURL")
        return resp

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
