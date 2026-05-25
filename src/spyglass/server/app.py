"""Flask application factory."""

from flask import Flask
from flask import jsonify

from spyglass.db.store import ProjectStore
from spyglass.server.routes import api
from spyglass.server.site import site


def create_app(store: ProjectStore) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store
    app.register_blueprint(api)
    app.register_blueprint(site)

    @app.get("/status")
    def status():
        return jsonify({"status": "ok"})

    return app
