import os
import time
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus

from flask import (
    Flask,
    Response,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.exceptions import NotFound
from wyze_bridge import WyzeBridge
from wyzebridge import config, web_ui
from wyzebridge.web_ui import url_for


def create_app():
    app = Flask(__name__)
    wb = WyzeBridge()
    try:
        wb.start()
    except RuntimeError as ex:
        print(ex)
        print("Please ensure your host is up to date.")
        exit()

    def auth_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not wb.api.auth:
                return redirect(url_for("wyze_login"))
            return web_ui.auth.login_required(view)(*args, **kwargs)

        return wrapped_view

    @app.route("/login", methods=["GET", "POST"])
    def wyze_login():
        if wb.api.auth:
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template(
                "login.html",
                api=config.WB_API,
                version=config.VERSION,
            )

        tokens = request.form.get("tokens")
        refresh = request.form.get("refresh")

        if tokens or refresh:
            wb.api.token_auth(tokens=tokens, refresh=refresh)
            return {"status": "success"}

        credentials = {
            "email": request.form.get("email"),
            "password": request.form.get("password"),
            "key_id": request.form.get("keyId"),
            "api_key": request.form.get("apiKey"),
        }

        if all(credentials.values()):
            wb.api.creds.update(**credentials)
            return {"status": "success"}

        return {"status": "missing credentials"}

    @app.route("/")
    @auth_required
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

        video_format = request.cookies.get("video", "webrtc")
        if req_video := ({"webrtc", "hls", "kvs"} & set(request.args)):
            video_format = req_video.pop()
        resp = make_response(
            render_template(
                "index.html",
                cam_data=web_ui.all_cams(wb.streams, wb.api.total_cams),
                number_of_columns=number_of_columns,
                refresh_period=refresh_period,
                api=config.WB_API,
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

    @app.route("/api/sse_status")
    @auth_required
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
    @auth_required
    def api_all_cams():
        return web_ui.all_cams(wb.streams, wb.api.total_cams)

    @app.route("/api/<string:cam_name>")
    @auth_required
    def api_cam(cam_name: str):
        if cam := wb.streams.get_info(cam_name):
            return cam | web_ui.format_stream(cam_name)
        return {"error": f"Could not find camera [{cam_name}]"}

    @app.route("/api/<cam_name>/<cam_cmd>", methods=["GET", "PUT", "POST"])
    @app.route("/api/<cam_name>/<cam_cmd>/<path:payload>")
    @auth_required
    def api_cam_control(cam_name: str, cam_cmd: str, payload: str | dict = ""):
        """API Endpoint to send tutk commands to the camera."""
        if not payload and (args := request.values.to_dict()):
            args.pop("api", None)
            payload = next(iter(args.values())) if len(args) == 1 else args
        if not payload and request.is_json:
            json = request.get_json()
            if isinstance(json, dict):
                payload = json if len(json) > 1 else list(json.values())[0]
            else:
                payload = json
        elif not payload and request.data:
            payload = request.data.decode()

        return wb.streams.send_cmd(cam_name, cam_cmd.lower(), payload)

    @app.route("/signaling/<string:name>")
    @auth_required
    def webrtc_signaling(name):
        if "kvs" in request.args:
            return wb.api.get_kvs_signal(name)
        return web_ui.get_webrtc_signal(name, config.WB_API)

    @app.route("/webrtc/<string:name>")
    @auth_required
    def webrtc(name):
        """View WebRTC direct from camera."""
        if (webrtc := wb.api.get_kvs_signal(name)).get("result") == "ok":
            return make_response(render_template("webrtc.html", webrtc=webrtc))
        return webrtc

    @app.route("/snapshot/<string:img_file>")
    @auth_required
    def rtsp_snapshot(img_file: str):
        """Use ffmpeg to take a snapshot from the rtsp stream."""
        if wb.streams.get_rtsp_snap(Path(img_file).stem):
            return send_from_directory(config.IMG_PATH, img_file)
        return thumbnail(img_file)

    @app.route("/img/<string:img_file>")
    @auth_required
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
    @auth_required
    def thumbnail(img_file: str):
        if wb.api.save_thumbnail(Path(img_file).stem):
            return send_from_directory(config.IMG_PATH, img_file)
        return redirect("/static/notavailable.svg", code=307)

    @app.route("/photo/<string:img_file>")
    @auth_required
    def boa_photo(img_file: str):
        """Take a photo on the camera and grab it over the boa http server."""
        uri = Path(img_file).stem
        if not (cam := wb.streams.get(uri)):
            return redirect("/static/notavailable.svg", code=307)
        if photo := web_ui.boa_snapshot(cam):
            return send_from_directory(config.IMG_PATH, f"{uri}_{photo[0]}")
        return redirect(f"/img/{img_file}", code=307)

    @app.route("/restart/<string:restart_cmd>")
    @auth_required
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
        elif restart_cmd == "cam_data":
            wb.refresh_cams()
            restart_cmd = "cameras"
        elif restart_cmd == "all":
            wb.restart(fresh_data=True)
            restart_cmd = "cameras,rtsp_server"
        else:
            return {"result": "error"}
        return {"result": "ok", "restart": restart_cmd.split(",")}

    @app.route("/cams.m3u8")
    @auth_required
    def iptv_playlist():
        """
        Generate an m3u8 playlist with all enabled cameras.
        """
        cameras = web_ui.format_streams(wb.streams.get_all_cam_info())
        resp = make_response(render_template("m3u8.html", cameras=cameras))
        resp.headers.set("content-type", "application/x-mpegURL")
        return resp

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
