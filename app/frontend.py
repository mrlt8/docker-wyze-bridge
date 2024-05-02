import os
import time
from pathlib import Path
from urllib.parse import quote_plus, urlparse

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
from wyze_bridge import WyzeBridge
from wyzebridge import config, web_ui

auth = HTTPBasicAuth()
auth_enabled = os.getenv("WEB_AUTH", "false").lower() != "false"
if auth_enabled:
    user = os.getenv("WEB_USERNAME", os.getenv("WYZE_EMAIL"))
    pw = generate_password_hash(os.getenv("WEB_PASSWORD", os.getenv("WYZE_PASSWORD")))


@auth.verify_password
def verify_password(username, password):
    if not auth_enabled:
        return True
    return check_password_hash(pw, password) if username == user else False


def create_app():
    app = Flask(__name__)
    wb = WyzeBridge()
    try:
        wb.start()
    except RuntimeError as ex:
        print(ex)
        print("Please ensure your host is up to date.")
        exit()

    @app.route("/login", methods=["GET", "POST"])
    def wyze_login():
        if wb.api.creds.is_set:
            return redirect("/")
        if request.method == "GET":
            return render_template(
                "login.html",
                hass=bool(config.HASS_TOKEN),
                version=config.VERSION,
            )
        email = request.form.get("email")
        password = request.form.get("password")
        key_id = request.form.get("keyId")
        api_key = request.form.get("apiKey")
        if email and password and key_id and api_key:
            wb.api.creds.update(email, password, key_id, api_key)
            return {"status": "success"}
        return {"status": "missing email or password"}

    @app.route("/")
    @auth.login_required
    def index():
        if not wb.api.creds.is_set:
            return redirect("/login")
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

        video_format = request.cookies.get("video", "webrtc")
        if req_video := ({"webrtc", "hls", "kvs"} & set(request.args)):
            video_format = req_video.pop()
        host = urlparse(request.root_url).hostname
        resp = make_response(
            render_template(
                "index.html",
                cam_data=web_ui.all_cams(wb.streams, wb.api.total_cams, host),
                number_of_columns=number_of_columns,
                refresh_period=refresh_period,
                hass=bool(config.HASS_TOKEN),
                version=config.VERSION,
                webrtc=bool(config.BRIDGE_IP),
                show_video=show_video,
                video_format=video_format.lower(),
                autoplay=autoplay,
            )
        )

        resp.set_cookie("number_of_columns", str(number_of_columns))
        resp.set_cookie("refresh_period", str(refresh_period))
        resp.set_cookie("show_video", "1" if show_video else "")
        resp.set_cookie("video", video_format)
        fullscreen = "fullscreen" in request.args or bool(
            request.cookies.get("fullscreen")
        )
        resp.set_cookie("fullscreen", "1" if fullscreen else "")
        if order := request.args.get("order"):
            resp.set_cookie("camera_order", quote_plus(order))

        return resp

    @app.route("/mfa/<string:code>")
    def set_mfa_code(code):
        """Set mfa code."""
        if len(code) != 6:
            return {"error": f"Wrong length: {len(code)}"}
        return {"success" if web_ui.set_mfa(code) else "error": f"Using: {code}"}

    @app.route("/api/sse_status")
    def sse_status():
        """Server sent event for camera status."""
        if wb.api.mfa_req:
            return Response(
                web_ui.mfa_generator(wb.api.get_mfa),
                mimetype="text/event-stream",
            )
        return Response(
            web_ui.sse_generator(wb.streams.get_sse_status),
            mimetype="text/event-stream",
        )

    @app.route("/api")
    def api_all_cams():
        host = urlparse(request.root_url).hostname
        return web_ui.all_cams(wb.streams, wb.api.total_cams, host)

    @app.route("/api/<string:cam_name>")
    def api_cam(cam_name: str):
        host = urlparse(request.root_url).hostname
        if cam := wb.streams.get_info(cam_name):
            return cam | web_ui.format_stream(cam_name, host)
        return {"error": f"Could not find camera [{cam_name}]"}

    @app.route("/api/<cam_name>/<cam_cmd>", methods=["GET", "PUT", "POST"])
    @app.route("/api/<cam_name>/<cam_cmd>/<path:payload>")
    def api_cam_control(cam_name: str, cam_cmd: str, payload: str | dict = ""):
        """API Endpoint to send tutk commands to the camera."""
        if args := request.values:
            payload = args.to_dict() if len(args) > 1 else next(args.values())
        elif request.is_json:
            json = request.get_json()
            if isinstance(json, dict):
                payload = json if len(json) > 1 else list(json.values())[0]
            else:
                payload = json
        elif request.data:
            payload = request.data.decode()

        return wb.streams.send_cmd(cam_name, cam_cmd.lower(), payload)

    @app.route("/signaling/<string:name>")
    def webrtc_signaling(name):
        if "kvs" in request.args:
            return wb.api.get_kvs_signal(name)
        return web_ui.get_webrtc_signal(name, urlparse(request.root_url).hostname)

    @app.route("/webrtc/<string:name>")
    def webrtc(name):
        """View WebRTC direct from camera."""
        if (webrtc := wb.api.get_kvs_signal(name)).get("result") == "ok":
            return make_response(render_template("webrtc.html", webrtc=webrtc))
        return webrtc

    @app.route("/snapshot/<string:img_file>")
    def rtsp_snapshot(img_file: str):
        """Use ffmpeg to take a snapshot from the rtsp stream."""
        if wb.streams.get_rtsp_snap(Path(img_file).stem):
            return send_from_directory(config.IMG_PATH, img_file)
        return thumbnail(img_file)

    @app.route("/img/<string:img_file>")
    def img(img_file: str):
        """
        Serve an existing local image or take a new snapshot from the rtsp stream.

        Use the exp parameter to fetch a new snapshot if the existing one is too old.
        """
        try:
            if exp := request.args.get("exp"):
                created_at = os.path.getmtime(config.IMG_PATH + img_file)
                if time.time() - created_at > int(exp):
                    raise NotFound
            return send_from_directory(config.IMG_PATH, img_file)
        except (NotFound, FileNotFoundError, ValueError):
            return rtsp_snapshot(img_file)

    @app.route("/thumb/<string:img_file>")
    def thumbnail(img_file: str):
        if wb.api.save_thumbnail(Path(img_file).stem):
            return send_from_directory(config.IMG_PATH, img_file)
        return redirect("/static/notavailable.svg", code=307)

    @app.route("/photo/<string:img_file>")
    def boa_photo(img_file: str):
        """Take a photo on the camera and grab it over the boa http server."""
        uri = Path(img_file).stem
        if not (cam := wb.streams.get(uri)):
            return redirect("/static/notavailable.svg", code=307)
        if photo := web_ui.boa_snapshot(cam):
            return send_from_directory(config.IMG_PATH, f"{uri}_{photo[0]}")
        return redirect(f"/img/{img_file}", code=307)

    @app.route("/restart/<string:restart_cmd>")
    def restart_bridge(restart_cmd: str):
        """
        Restart parts of the wyze-bridge.

        /restart/cameras:       Restart camera connections.
        /restart/rtsp_server:   Restart rtsp-simple-server.
        /restart/all:           Restart camera connections and rtsp-simple-server.
        """
        if restart_cmd == "cameras":
            wb.streams.stop_all()
            wb.streams.monitor_streams(wb.rtsp.health_check)
        elif restart_cmd == "rtsp_server":
            wb.rtsp.restart()
        elif restart_cmd == "all":
            wb.streams.stop_all()
            wb.rtsp.stop()
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
        host = urlparse(request.root_url).hostname
        cameras = web_ui.format_streams(wb.streams.get_all_cam_info(), host)
        resp = make_response(render_template("m3u8.html", cameras=cameras))
        resp.headers.set("content-type", "application/x-mpegURL")
        return resp

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
