"""Flask application factory."""

from flask import Flask
from flask import jsonify

from spyglass.db.store import ProjectStore
from spyglass.server.routes import api
from spyglass.server.site import site
from spyglass.server.write_buffer import WriteBuffer


def create_app(store: ProjectStore, write_buffer: WriteBuffer | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store
    app.config["WRITE_BUFFER"] = write_buffer or WriteBuffer(store)
    app.register_blueprint(api)
    app.register_blueprint(site)

    @app.get("/status")
    def status():
        return jsonify({"status": "ok"})

    return app
