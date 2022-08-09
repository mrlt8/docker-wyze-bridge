import logging
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.exceptions import NotFound

import wyze_bridge
from wyze_bridge import WyzeBridge

log = logging.getLogger(__name__)
wb: WyzeBridge = None


def clean_up():
    """Run cleanup before exit."""
    if not wb:
        sys.exit(0)
    wb.clean_up()


signal.signal(signal.SIGTERM, lambda *_: clean_up())


def create_app():
    wyze_bridge.setup_logging()

    log.info("create_app")
    app = Flask(__name__)
    global wb
    if not wb:
        wb = WyzeBridge()
        wb.start()

    @app.route("/")
    def index():
        number_of_columns = request.cookies.get("number_of_columns", "2")
        number_of_columns = int(number_of_columns) if number_of_columns.isdigit() else 0
        refresh_period = request.cookies.get("refresh_period", "30")
        refresh_period = int(refresh_period) if refresh_period.isdigit() else 0
        cameras = wb.get_cameras(urlparse(request.root_url).hostname)
        show_video = bool(request.cookies.get("show_video"))
        if "video" in request.args:
            show_video = True
        elif "snapshot" in request.args:
            show_video = False
        resp = make_response(
            render_template(
                "index.html",
                cameras=cameras,
                enabled=len([cam for cam in cameras.values() if cam.get("enabled")]),
                number_of_columns=number_of_columns,
                refresh_period=refresh_period,
                hass=wb.hass,
                version=wb.version,
                show_video=show_video,
                on_demand=wb.on_demand,
            )
        )
        resp.set_cookie("number_of_columns", str(number_of_columns))
        resp.set_cookie("refresh_period", str(refresh_period))
        resp.set_cookie("show_video", "1" if show_video else "")
        return resp

    @app.route("/events/<path:event>/<path:cam>")
    def events(event: str, cam: str):
        if event == "start":
            try:
                wb.start_on_demand(cam)
            except StopIteration:
                abort(404)
        return {}

    @app.route("/cameras")
    def cameras():
        return wb.get_cameras(
            urlparse(request.root_url).hostname
        )  # return json, for introspection or for future ajax UI

    @app.route("/snapshot/<path:img_file>")
    def rtsp_snapshot(img_file: str):
        """Use ffmpeg to take a snapshot from the rtsp stream."""
        uri = Path(img_file).stem
        if uri not in wb.get_cameras():
            abort(404)
        wb.rtsp_snap(uri, wait=True)
        return send_from_directory(wb.img_path, img_file)

    @app.route("/photo/<path:img_file>")
    def boa_photo(img_file: str):
        """Take a photo on the camera and grab it over the boa http server."""
        uri = Path(img_file).stem
        if not (cam := wb.get_cameras().get(uri)):
            abort(404)
        if photo := wb.boa_photo(cam.get("nickname")):
            file = cam["nickname"] + "_" + photo[0]
            return send_from_directory(wb.img_path, file)

        return redirect(f"/img/{img_file}", code=302)

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
            wb.start()
        elif restart_cmd == "rtsp_server":
            wb.stop_rtsp_server()
            wb.start_rtsp_server()
        elif restart_cmd == "all":
            wb.stop_cameras()
            wb.stop_rtsp_server()
            wb.start()
            restart_cmd = "cameras,rtsp_server"
        else:
            return {"result": "error"}

        return {"result": "ok", "restart": restart_cmd.split(",")}

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
