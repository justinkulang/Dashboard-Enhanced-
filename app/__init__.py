import os
import logging
from flask import Flask, g, current_app
from flask_cors import CORS
from flask_babel import Babel
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from datetime import timedelta

# Global instances of extensions, to be initialized in create_app
babel = Babel()
login_manager = LoginManager()
csrf = CSRFProtect()

# To store the application-specific config (loaded from JSON/ENV)
# This will be attached to the app object as app.app_config_instance
app_config_instance = None
config_loader_instance = None

module_logger = logging.getLogger("app")

def setup_logging_factory(app_cfg, app_name="app"):
    # Use a logger specific to the application instance if possible,
    # or fall back to a general logger name.
    logger_to_configure = logging.getLogger(app_name)

    # Clear existing handlers to prevent duplication if factory is called multiple times (e.g. tests)
    if logger_to_configure.hasHandlers():
        logger_to_configure.handlers.clear()
    logger_to_configure.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Console Handler
    ch = logging.StreamHandler()
    console_log_level_str = app_cfg.get('server', {}).get('log_level_console', 'INFO').upper()
    console_log_level = getattr(logging, console_log_level_str, logging.INFO)
    ch.setLevel(console_log_level)
    ch.setFormatter(formatter)
    logger_to_configure.addHandler(ch)
    logger_to_configure.info(f"AppFactory: Console logging for '{app_name}' configured with level: {logging.getLevelName(ch.level)}")

    # File Handler
    try:
        log_file_path = app_cfg.get('server', {}).get('log_file', 'mikrotik_dashboard.log')
        log_dir = os.path.dirname(log_file_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        fh = logging.FileHandler(log_file_path)
        file_log_level_str = app_cfg.get('server', {}).get('log_level_file', 'INFO').upper()
        file_log_level = getattr(logging, file_log_level_str, logging.INFO)
        fh.setLevel(file_log_level)
        fh.setFormatter(formatter)
        logger_to_configure.addHandler(fh)
        logger_to_configure.info(f"AppFactory: File logging for '{app_name}' configured to: {log_file_path} with level: {file_log_level_str}")
    except Exception as e:
        logger_to_configure.error(f"AppFactory: Failed to configure file logging for '{app_name}': {e}", exc_info=True)


def create_app(config_file_override=None):
    """Application Factory Function"""
    global app_config_instance, config_loader_instance # Allow modification of these module-level vars

    # app = Flask(__name__) # Using __name__ here means logger name might be 'app'
    # If blueprints are in subdirectories, __name__ is fine.
    # The static_url_path defaults to /static.
    # template_folder and static_folder default to 'templates' and 'static' in the app root path.
    app = Flask(__name__.split('.')[0], # Use 'app' as the import name for Flask if this is app/__init__.py
                instance_relative_config=False,
                template_folder='templates',
                static_folder='static')


    # --- Configuration Loading ---
    # ConfigLoader needs to be imported from its new location once moved.
    # For now, assuming it's still accessible from where 'run.py' (old app.py) is.
    # This will be a problem if ConfigLoader itself tries to use 'app_config' during its init.
    # Let's assume ConfigLoader is self-contained for now.
    from run import ConfigLoader, get_base_path # TEMPORARY - these need to move into app package

    # Determine the base path for config_file relative to project root, not app package root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    default_config_path = os.path.join(project_root, 'config.json')

    cfg_file_to_load = config_file_override if config_file_override else default_config_path

    # Temporarily adjust get_base_path if ConfigLoader uses it to find config.json
    # This is a HACK because ConfigLoader is not yet part of the 'app' package.
    # We want ConfigLoader to look for 'config.json' in the project root.
    original_get_base_path = None
    if hasattr(ConfigLoader, '_get_base_path_for_config'): # Hypothetical method
        pass
    else: # Assuming ConfigLoader uses a get_base_path that implies script location
        # This monkeypatching is risky and structure-dependent.
        def mock_get_base_path_for_loader(): return project_root

        # Check if get_base_path is a global in the module where ConfigLoader is defined (run.py)
        import run as old_app_module
        if hasattr(old_app_module, 'get_base_path'):
            original_get_base_path = old_app_module.get_base_path
            old_app_module.get_base_path = mock_get_base_path_for_loader


    config_loader_instance = ConfigLoader(config_file=cfg_file_to_load)

    # Restore original get_base_path if it was patched
    if original_get_base_path and hasattr(old_app_module, 'get_base_path'):
        old_app_module.get_base_path = original_get_base_path

    app_config_instance = config_loader_instance.get_config()
    app.app_config_instance = app_config_instance # Attach loaded config to app instance

    # Setup logging using the loaded configuration
    setup_logging_factory(app.app_config_instance, app.name)

    # --- Flask App Configuration ---
    SECRET_KEY_FALLBACK = "a_very_secret_and_stable_key_for_development_do_not_use_in_prod_app_factory"
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', SECRET_KEY_FALLBACK)
    if app.config['SECRET_KEY'] == SECRET_KEY_FALLBACK:
        app.logger.warning("WARNING (Factory): FLASK_SECRET_KEY environment variable not set. Using a default, insecure key.")

    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=app.app_config_instance.get('server', {}).get('session_lifetime_minutes', 30))
    app.config['LANGUAGES'] = app.app_config_instance.get('server', {}).get('languages', ['en', 'ar', 'fr'])
    app.config['BABEL_DEFAULT_LOCALE'] = app.app_config_instance.get('server', {}).get('babel_default_locale', 'en')
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = os.path.join(project_root, 'translations') # Assuming translations dir is at project root
    app.config["WTF_CSRF_HEADER_NAME"] = "X-CSRFToken"

    # Update Flask's own config with server settings from app_config_instance for convenience if needed
    app.config.update(app.app_config_instance.get('server', {}))


    # --- Initialize Extensions ---
    CORS(app)
    babel.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login_page' # Adjusted for blueprint, will be registered later
    login_manager.session_protection = "strong"

    # --- User Loader for Flask-Login ---
    # User class needs to be defined or imported. For now, assume it's in run.py
    # This also needs to be moved into the app package.
    from run import User as AppUser # TEMPORARY

    # Make app_config_instance accessible to User.get if it needs it
    # A better way: User.get uses current_app.app_config_instance
    AppUser.app_config = app.app_config_instance

    @login_manager.user_loader
    def load_user(user_id):
        return AppUser.get(user_id)

    # --- Request Hooks (before_request, teardown_appcontext) ---
    # These also need to be moved from run.py
    # For now, we'll define them here. They need access to get_mikrotik_api, etc.
    # These dependencies show the intertwined nature of the old app.py.

    # Placeholder for these hooks - will be properly defined when routes are moved
    # @app.before_request
    # def before_request_handler_factory():
    #     from run import before_request_handler as brh # TEMPORARY
    #     return brh() # This will fail if brh uses global app

    # @app.teardown_appcontext
    # def teardown_connection_factory(exception):
    #    from run import teardown_connection as tc # TEMPORARY
    #    return tc(exception)


    # --- Register Blueprints ---
    # This will be done in subsequent steps. Example:
    # from .auth import auth_bp
    # app.register_blueprint(auth_bp)
    # from .users import users_api_bp
    # app.register_blueprint(users_api_bp) # url_prefix is already in blueprint
    # from .profiles import profiles_api_bp
    # app.register_blueprint(profiles_api_bp)

    app.logger.info(f"Flask app '{app.name}' created successfully by factory.")
    return app
