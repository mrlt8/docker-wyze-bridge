import logging
from pathlib import Path
from urllib.parse import urlparse
from werkzeug.exceptions import NotFound
from flask import (
    Flask,
    abort,
    make_response,
    render_template,
    request,
    send_from_directory,
)

import wyze_bridge
from wyze_bridge import WyzeBridge

log = logging.getLogger(__name__)
wb: WyzeBridge = None


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
        number_of_columns = int(request.cookies.get("number_of_columns", default="2"))
        refresh_period = int(request.cookies.get("refresh_period", default="30"))
        cameras = wb.get_cameras(urlparse(request.root_url).hostname)
        log.info(cameras)
        resp = make_response(
            render_template(
                "index.html",
                cameras=cameras,
                enabled=len([cam for cam in cameras.values() if cam.get("enabled")]),
                number_of_columns=number_of_columns,
                hass=wb.hass,
                version=wb.version,
                show_video=wb.show_video,
                refresh_period=refresh_period,
            )
        )
        resp.set_cookie("number_of_columns", str(number_of_columns))
        return resp

    @app.route("/cameras")
    def cameras():
        return wb.get_cameras(
            urlparse(request.root_url).hostname
        )  # return json, for introspection or for future ajax UI

    @app.route("/snapshot/<path:img_file>")
    def rtsp_snapshot(img_file: str):
        """Use ffmpeg to take a snapshot from the rtsp stream."""
        uri = Path(img_file).stem
        if not uri in wb.get_cameras():
            abort(404)
        wb.rtsp_snap(uri, wait=True)
        return send_from_directory(wb.img_path, img_file)

    @app.route("/img/<path:img_file>")
    def img(img_file: str):
        """Serve static image if image exists else take a new snapshot from the rtsp stream."""
        try:
            return send_from_directory(wb.img_path, img_file)
        except NotFound:
            return rtsp_snapshot(img_file)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
