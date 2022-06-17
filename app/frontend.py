import logging

from flask import Flask, make_response, render_template, request, send_from_directory

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
        log.info(f"number_of_columns={number_of_columns}")
        resp = make_response(
            render_template(
                "index.html",
                cameras=wb.get_cameras(),
                number_of_columns=number_of_columns,
                hass=wb.hass,
                version=wb.version,
            )
        )
        resp.set_cookie("number_of_columns", str(number_of_columns))
        return resp

    @app.route("/cameras")
    def cameras():
        return wb.get_cameras()  # return json, for introspection or for future ajax UI

    @app.route("/img/<path:path>")
    def img(path: str):
        return send_from_directory(wb.img_path, path)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
