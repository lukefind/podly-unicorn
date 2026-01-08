from flask import Flask

from .auth_routes import auth_bp
from .config_routes import config_bp
from .feed_routes import feed_bp
from .jobs_routes import jobs_bp
from .main_routes import main_bp
from .post_routes import post_bp
from .preset_routes import preset_bp, stats_bp


def register_routes(app: Flask) -> None:
    """Register all route blueprints with the Flask app.
    
    Note: main_bp must be registered LAST because it contains a catch-all
    route (/<path:path>) that serves the React SPA. If registered first,
    it would intercept routes like /trigger before post_bp can handle them.
    """
    app.register_blueprint(feed_bp)
    app.register_blueprint(post_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(preset_bp)
    app.register_blueprint(stats_bp)
    # main_bp MUST be last - it has catch-all route for React SPA
    app.register_blueprint(main_bp)
