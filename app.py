"""Mikrotik Hotspot User Management Backend - v2
Major overhaul with a redesigned UI, profile management, filtered exports, QR codes, and more."""
from flask import Flask, render_template, request, jsonify, send_from_directory, g, redirect, url_for, session # Add session
from flask_cors import CORS
from flask_babel import Babel, get_locale, _ # Re-add get_locale
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf # Import CSRFProtect and generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
import librouteros
from librouteros.exceptions import TrapError
import socket
import json
import os
import sys
import logging
import random
import string
import re
import math
import io
import csv
from flask import Response
import base64

# Configure logging
# logging.basicConfig(level=logging.INFO) # Will be replaced by more detailed config

# --- Logging Configuration ---
logger = logging.getLogger(__name__) # Get logger for the app
# Note: Actual handler configuration will be done after app_config is loaded.

# --- Graceful Dependency Handling ---
# Attempt to import WeasyPrint for PDF export
try:
    from weasyprint import HTML as WeasyHTML
    WEASYPRINT_AVAILABLE = True
    logger.info("WeasyPrint library loaded successfully. PDF export is enabled.")
except (ImportError, OSError) as e:
    WEASYPRINT_AVAILABLE = False
    logger.warning("="*50)
    logger.warning("WeasyPrint could not be loaded. PDF export will be disabled.")
    logger.warning(f"Error: {e}")
    logger.warning("This is likely due to missing GTK+ system dependencies.")
    logger.warning("Please follow the installation steps for your OS:")
    logger.warning("https://doc.weasyprint.org/stable/first_steps.html#installation")
    logger.warning("="*50)


# Attempt to import qrcode for QR generation

babel = Babel() # Define Babel instance here

try:
    import qrcode
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    logger.warning("qrcode library not found. QR codes on vouchers will be disabled.")
    logger.warning("To enable this feature, please install it: pip install qrcode[pil]")


app = Flask(__name__)
CORS(app)

# Session management
SECRET_KEY_FALLBACK = "a_very_secret_and_stable_key_for_development_do_not_use_in_prod"
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', SECRET_KEY_FALLBACK)
if app.config['SECRET_KEY'] == SECRET_KEY_FALLBACK:
    logger.warning("WARNING: FLASK_SECRET_KEY environment variable not set. Using a default, insecure key for development. SET THIS VARIABLE IN PRODUCTION!")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) # Example: 30 minutes timeout

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page' # Redirect to login_page if @login_required fails
login_manager.session_protection = "strong"

# Initialize CSRF Protection
csrf = CSRFProtect()
csrf.init_app(app)
app.config["WTF_CSRF_HEADER_NAME"] = "X-CSRFToken" # Tell Flask-WTF to look for token in this header for AJAX

# Language configuration
app.config['LANGUAGES'] = ['en', 'ar', 'fr']
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

babel.init_app(app) # Initialize Babel with app context here

# @babel.localeselector
# def get_locale_func():
#     # Try to get the language from the user's browser settings
#     # Ensure request context is available or handle appropriately if called outside request
#     if request:
#         return request.accept_languages.best_match(app.config['LANGUAGES'])
#     return app.config['BABEL_DEFAULT_LOCALE'] # Fallback

def get_base_path():
    """ Get base path for PyInstaller bundled app or normal script """
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.abspath(os.path.dirname(__file__))

class ConfigLoader:
    """Handles loading and managing application configuration."""
    def __init__(self, config_file='config.json'):
        self.config_file = os.path.join(get_base_path(), config_file)
        self.config = self._load_config()

    def _load_config(self):
        """Load configuration from config.json or create default if not exists.
        Environment variables take precedence over config.json values for sensitive data."""

        # Define default structure (especially for non-sensitive parts or fallbacks)
        cfg = {
            "mikrotik": {
                "host": "192.168.88.1",
                "port": 8728,
                "username": "admin",
                "password": "",  # Sensitive, prioritize ENV
                "use_ssl": False,
                "hotspot_login_url": "http://hotspot.setup/login"
            },
            "server": {
                "host": "0.0.0.0",
                "port": 5000,
                "debug": False,
                "log_file": "mikrotik_dashboard.log",
                "log_level_console": "INFO",
                "log_level_file": "INFO"
            },
            "app_admin": {
                "username": "admin", # Sensitive, prioritize ENV
                "password_hash": "pbkdf2:sha256:600000$zR0gQY0gV0gY0gV0$c2df639e9e31b0cf9352d789a8f074d2f6a603cf8bd77a9a20addf32089e11f9"  # Sensitive, prioritize ENV
            }
        }

        # Load from config.json if it exists
        json_config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    json_config = json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON from {self.config_file}. Using defaults and environment variables.", exc_info=True)
        else:
            # If config file doesn't exist, write the default structure (values might be overridden by ENV)
            try:
                with open(self.config_file, 'w') as f:
                    json.dump(cfg, f, indent=4) # Write the initial default structure
                logger.info(f"Default configuration file created at {self.config_file}")
            except IOError:
                logger.error(f"Could not write default config file to {self.config_file}", exc_info=True)


        # Merge json_config into cfg (json_config takes precedence over hardcoded defaults here)
        if json_config.get('mikrotik'):
            cfg['mikrotik'].update(json_config['mikrotik'])
        if json_config.get('server'):
            cfg['server'].update(json_config['server'])
        if json_config.get('app_admin'):
            cfg['app_admin'].update(json_config['app_admin'])

        # Environment variable overrides for Mikrotik
        cfg['mikrotik']['host'] = os.environ.get('MIKROTIK_HOST', cfg['mikrotik']['host'])
        cfg['mikrotik']['port'] = int(os.environ.get('MIKROTIK_PORT', cfg['mikrotik']['port']))
        cfg['mikrotik']['username'] = os.environ.get('MIKROTIK_USERNAME', cfg['mikrotik']['username'])
        mikrotik_password_env = os.environ.get('MIKROTIK_PASSWORD')
        if mikrotik_password_env is not None:
            cfg['mikrotik']['password'] = mikrotik_password_env
            logger.info("Mikrotik password loaded from MIKROTIK_PASSWORD environment variable.")
        elif not cfg['server'].get('debug') and cfg['mikrotik']['password']:
             logger.warning("MIKROTIK_PASSWORD environment variable not set. Loading Mikrotik password from config.json. This is not recommended for production.")


        mikrotik_use_ssl_env = os.environ.get('MIKROTIK_USE_SSL')
        if mikrotik_use_ssl_env is not None:
            cfg['mikrotik']['use_ssl'] = mikrotik_use_ssl_env.lower() in ['true', '1', 'yes']
        cfg['mikrotik']['hotspot_login_url'] = os.environ.get('MIKROTIK_HOTSPOT_LOGIN_URL', cfg['mikrotik']['hotspot_login_url'])

        # Environment variable overrides for App Admin
        cfg['app_admin']['username'] = os.environ.get('APP_ADMIN_USERNAME', cfg['app_admin']['username'])
        app_admin_password_hash_env = os.environ.get('APP_ADMIN_PASSWORD_HASH')
        if app_admin_password_hash_env:
            cfg['app_admin']['password_hash'] = app_admin_password_hash_env
            logger.info("App admin password hash loaded from APP_ADMIN_PASSWORD_HASH environment variable.")
        elif not cfg['server'].get('debug') and cfg['app_admin']['password_hash']:
            logger.warning("APP_ADMIN_PASSWORD_HASH environment variable not set. Loading app admin password hash from config.json. This is not recommended for production.")

        # Environment variable overrides for Server (optional, less critical but good for flexibility)
        cfg['server']['host'] = os.environ.get('SERVER_HOST', cfg['server']['host'])
        cfg['server']['port'] = int(os.environ.get('SERVER_PORT', cfg['server']['port']))
        server_debug_env = os.environ.get('FLASK_DEBUG') # Common env var for Flask debug
        if server_debug_env is not None:
             cfg['server']['debug'] = server_debug_env.lower() in ['true', '1', 'yes']
        elif os.environ.get('APP_ENV', 'development').lower() == 'production': # Another common pattern
            cfg['server']['debug'] = False


        # Log which source was used for sensitive data if debug is false
        if not cfg['server'].get('debug'):
            if mikrotik_password_env:
                logger.info("Using Mikrotik password from environment variable.")
            elif cfg['mikrotik']['password']: # Only log if a password was actually found in config
                logger.warning("SECURITY WARNING: Using Mikrotik password from config.json. Set MIKROTIK_PASSWORD environment variable for production.")

            if app_admin_password_hash_env:
                logger.info("Using App Admin password hash from environment variable.")
            elif cfg['app_admin']['password_hash'] != "pbkdf2:sha256:600000$zR0gQY0gV0gY0gV0$c2df639e9e31b0cf9352d789a8f074d2f6a603cf8bd77a9a20addf32089e11f9": # Default for "changeme"
                 logger.warning("SECURITY WARNING: Using App Admin password hash from config.json. Set APP_ADMIN_PASSWORD_HASH environment variable for production.")

        # Debug log for server host/port/debug status
        logger.info(f"Server configured to run on {cfg['server']['host']}:{cfg['server']['port']} with debug mode: {cfg['server']['debug']}")

        return cfg

    def get_config(self):
        return self.config

    def update_config(self, new_config_data):
        """Updates specified parts of the configuration and saves to config.json.
        Does NOT update values that are primarily sourced from environment variables
        (like passwords, admin username/hash if they were set by env vars).
        This method is mainly for settings like Mikrotik host/port (if not set by env),
        server settings, or hotspot_login_url.
        """
        changes_made = False

        # Update Mikrotik settings (excluding password if it was from ENV)
        if 'mikrotik' in new_config_data:
            mk_changes = new_config_data['mikrotik']
            # Only update if not overridden by ENV. This logic gets complex.
            # Simpler: allow update, but ENV will override on next load.
            # Or, prevent updating fields managed by ENV.
            # For now, let's allow updates to config.json, ENV will always win on load.
            self.config['mikrotik'].update(mk_changes)
            changes_made = True
            # Specific check: do not overwrite password in config if it came from ENV
            if os.environ.get('MIKROTIK_PASSWORD') and 'password' in mk_changes:
                 logger.warning("Attempted to update Mikrotik password in config.json while MIKROTIK_PASSWORD env var is set. Config.json change will be ignored on next load if env var persists.")


        if 'server' in new_config_data:
            self.config['server'].update(new_config_data['server'])
            changes_made = True

        # App admin username/hash updates should go through a dedicated mechanism, not this generic update.
        # However, if other app_admin settings were to exist, they could be updated here.
        # For now, we prevent app_admin changes through this generic route.
        if 'app_admin' in new_config_data:
            logger.warning("Attempt to update 'app_admin' through generic config update. This is generally not allowed for password hash. No changes made to app_admin section via this method.")
            # self.config['app_admin'].update(new_config_data.get('app_admin', {})) # Example if we wanted to allow some app_admin changes

        if changes_made:
            try:
                with open(self.config_file, 'w') as f:
                    json.dump(self.config, f, indent=4)
                logger.info(f"Configuration updated in {self.config_file}")
            except IOError:
                logger.error(f"Could not write configuration to {self.config_file}", exc_info=True)
        else:
            logger.info("No changes applied to configuration file via update_config.")


    def update_admin_password_hash(self, new_password_hash: str) -> bool:
        """Specifically updates the app_admin password_hash in config.json.
        Returns True if successful, False otherwise.
        This should only be called if the hash is NOT being sourced from an ENV var."""
        if os.environ.get('APP_ADMIN_PASSWORD_HASH'):
            logger.error("Cannot update admin password hash in config.json because APP_ADMIN_PASSWORD_HASH environment variable is set.")
            return False

        self.config['app_admin']['password_hash'] = new_password_hash
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.info(f"Admin password hash updated in {self.config_file}")
            return True
        except IOError:
            logger.error(f"Could not write admin password hash to {self.config_file}", exc_info=True)
            return False

    def reset_mikrotik_config_to_defaults(self):
        """Resets the Mikrotik part of the configuration to its original defaults,
        respecting that environment variables will still take precedence on next load."""
        # Get the original default settings as defined in _load_config
        # This is a bit indirect; _load_config itself returns a merged config.
        # For true defaults, we define it here or access a pristine default structure.
        # Let's re-fetch default structure as defined in _load_config's initial state.
        original_default_settings = { # Replicating the default structure from _load_config
            "host": "192.168.88.1",
            "port": 8728,
            "username": "admin",
            "password": "",
            "use_ssl": False,
            "hotspot_login_url": "http://hotspot.setup/login"
        }
        # The server part of the config should remain untouched by this.
        current_server_config = self.config.get('server', {}) 
        
        update_payload = {
            'mikrotik': original_default_settings,
            'server': current_server_config # Ensure server settings are preserved
        }
        # Instead of self.update_config which merges, we want to overwrite mikrotik section
        # and keep server section. So, construct the full new config.
        self.config['mikrotik'] = original_default_settings
        # self.config['server'] is already what it should be.
        
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)
        logger.info("Mikrotik configuration has been reset to defaults.")


# Initialize ConfigLoader
config_loader = ConfigLoader()
app_config = config_loader.get_config()


# --- Setup Logging Handlers (after app_config is available) ---
def setup_logging(app_config_instance):
    _logger = logging.getLogger(__name__) # Use module-level logger
    _logger.setLevel(logging.INFO) # Default log level

    # Clear existing handlers if any (to avoid duplicate logs on reloads in dev)
    if _logger.hasHandlers():
        _logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Console Handler
    ch = logging.StreamHandler()
    # Use log_level_console from server config, or default to INFO
    console_log_level_str = app_config_instance.get('server', {}).get('log_level_console', 'INFO').upper()
    console_log_level = getattr(logging, console_log_level_str, logging.INFO)
    ch.setLevel(console_log_level)
    ch.setFormatter(formatter)
    _logger.addHandler(ch)
    _logger.info(f"Console logging configured with level: {logging.getLevelName(ch.level)}") # Use ch.level for accuracy

    # File Handler
    try:
        log_file_path = app_config_instance.get('server', {}).get('log_file', 'mikrotik_dashboard.log')
        log_dir = os.path.dirname(log_file_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        fh = logging.FileHandler(log_file_path)
        file_log_level_str = app_config_instance.get('server', {}).get('log_level_file', 'INFO').upper()
        file_log_level = getattr(logging, file_log_level_str, logging.INFO) # Default to INFO if invalid
        fh.setLevel(file_log_level)
        fh.setFormatter(formatter)
        _logger.addHandler(fh)
        _logger.info(f"File logging configured to: {log_file_path} with level: {file_log_level_str}")
    except Exception as e:
        _logger.error(f"Failed to configure file logging: {e}", exc_info=True)

setup_logging(app_config) # Call the setup function with the loaded app_config


# --- User Class for Flask-Login ---
class User(UserMixin):
    def __init__(self, id):
        self.id = id

    @staticmethod
    def get(user_id):
        admin_username = app_config.get('app_admin', {}).get('username')
        if user_id == admin_username:
            return User(user_id)
        return None

@login_manager.user_loader
def load_user(user_id):
    user = User.get(user_id)
    return user

# Define exempt endpoints that do not require a Mikrotik connection OR app login initially
MIKROTIK_EXEMPT_ENDPOINTS = {'login_page', 'app_login_route', 'initial_connect', 'static', 'get_translations'}
# CSRF protection will be enabled by default for all POST/PUT/DELETE requests.
# We might need to exempt specific routes if they are called from external systems not using our CSRF flow.
# For now, all internal POSTs should be protected. login_page and app_login are POST but are handled.

@app.before_request
def before_request_handler():
    logger.debug(f"before_request: endpoint='{request.endpoint}', path='{request.path}'")

    # 1. Flask-Login Authentication Check
    login_exempt_for_auth = request.endpoint in ['login_page', 'app_login_route', 'static', 'get_translations']
    
    # Removed temporary debug logging from here

    if not login_exempt_for_auth and not current_user.is_authenticated:
        logger.info(f"User not authenticated for endpoint '{request.endpoint}'. Redirecting to login page.")
        return redirect(url_for('login_page'))

    # 2. Mikrotik Connection Initialization (for authenticated users on non-exempt routes)
    # This step ensures g.mikrotik_api is populated if a connection exists,
    # but does NOT redirect if the connection is down for dashboard/API pages.
    # The frontend UI will handle the disconnected state for these pages.
    if current_user.is_authenticated and request.endpoint not in MIKROTIK_EXEMPT_ENDPOINTS:
        logger.debug(f"User authenticated. Endpoint '{request.endpoint}' is not Mikrotik exempt. Initializing Mikrotik API for 'g'.")
        get_mikrotik_api() # This will set g.mikrotik_api or g.mikrotik_api = None
        # No redirect here if api is None. Frontend will handle UI based on connection status.
        # Specific routes that absolutely cannot function without an API connection
        # (and where frontend cannot gracefully degrade) would need to check g.mikrotik_api themselves.
        # However, the goal is for the dashboard to be accessible.
    elif request.endpoint in MIKROTIK_EXEMPT_ENDPOINTS:
         logger.debug(f"Endpoint '{request.endpoint}' is exempt from Mikrotik connection logic in before_request.")
    # else: User not authenticated but endpoint is exempt from auth (e.g. /login), or other cases.

    return # Allow request


@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    global app_config
    logger.info("Processing logout request.")

    # Logout from Flask-Login session
    logout_user()
    logger.info("Flask-Login session ended.")

    # Reset Mikrotik configuration (original functionality)
    config_loader.reset_mikrotik_config_to_defaults()
    app_config = config_loader.get_config() # Reload global app_config

    if 'mikrotik_api' in g:
        g.pop('mikrotik_api', None)
    if 'mikrotik_connection' in g:
        conn_to_close = g.pop('mikrotik_connection', None)
        if conn_to_close and hasattr(conn_to_close, 'close'):
            try:
                conn_to_close.close()
                logger.info("Closed active Mikrotik connection from 'g' during logout.")
            except Exception as e:
                logger.error(f"Error closing connection from 'g' during logout: {e}")

    logger.info("User logged out from web app, Mikrotik configuration reset to defaults.")
    return jsonify({'success': True, 'message': _('Logged out successfully from web app and Mikrotik.')})

def _generate_vouchers_page_html(vouchers: list, hotspot_login_url: str, include_print_button: bool = True) -> str:
    # Read the logo file and encode it as Base64
    logo_path = os.path.join(get_base_path(), 'static', 'images', 'The IT Dad new logo.png')
    logo_base64 = ""
    try:
        with open(logo_path, "rb") as image_file:
            logo_base64 = base64.b64encode(image_file.read()).decode('utf-8')
        logo_mime_type = "image/png" # Assuming PNG, adjust if it could be other types
        logo_data_url = f"data:{logo_mime_type};base64,{logo_base64}"
    except FileNotFoundError:
        logger.warning(f"Logo file not found at {logo_path} for voucher generation.")
        logo_data_url = "" # Fallback or handle error

    html_parts = ["""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Hotspot Vouchers</title>
        <style>
            @page {
                size: A4 portrait;
                margin: 5mm;
            }
            body {
                margin: 0;
                padding: 0;
                font-family: 'Segoe UI', Arial, sans-serif;
                background-color: #f4f4f9;
                color: #333333;
                -webkit-print-color-adjust: exact; 
            }
            .print-button-container {
                text-align: center;
                padding: 20px;
            }
            .print-button {
                padding: 12px 25px;
                background-color: #007bff;
                color: #fff;
                border: none;
                border-radius: 5px;
                font-size: 16px;
                cursor: pointer;
                transition: background-color 0.2s;
            }
            .print-button:hover {
                background-color: #0056b3;
            }
            .voucher-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, 70mm); /* Updated width */
                gap: 8mm; /* Updated gap */
                padding: 10mm; /* Keep padding or adjust if needed */
                justify-content: center;
            }
            .voucher {
                width: 70mm; /* Updated width */
                height: 50mm; /* Updated height */
                background-color: #fff;
                border: 1px solid #ddd;
                border-radius: 8px;
                box-sizing: border-box;
                display: flex;
                flex-direction: column; 
                page-break-inside: avoid;
                overflow: hidden;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            }
            .voucher-header {
                background-color: #fff;
                color: #2A7ABF; /* Updated to Bright Blue from logo */
                border-bottom: 1.5px solid #2A7ABF; /* Updated to Bright Blue */
                padding: 5px 8px;
                text-align: center;
                font-weight: bold;
                font-size: 1.1em;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
            }
            .voucher-content {
                display: flex;
                flex-grow: 1; 
                padding: 5px;
                justify-content: space-between;
                align-items: center;
            }
            .voucher-qr {
                width: 24mm;
                height: 24mm;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 4px; 
            }
            .voucher-qr img {
                max-width: 100%;
                max-height: 100%;
                border-radius: 4px;
            }
            .voucher-details {
                flex-grow: 1;
                font-size: 0.9em; 
                color: #000000;
                display: flex;
                flex-direction: column;
                justify-content: center; 
                gap: 4px;
                padding-left: 8px;
            }
            .voucher-details p {
                margin: 0;
            }
            .voucher-details strong { 
                color: #333;
                font-weight: 500;
            }
            .voucher-details span { 
                font-family: 'Courier New', monospace;
                 color: #2A7ABF; /* Updated to Bright Blue */
                background-color: #f0f2f5;
                padding: 2px 5px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 1.1em; 
                word-break: break-all; 
            }
            .voucher-footer { 
                font-size: 7.5pt; 
                color: #555; 
                text-align: center;
                padding: 4px 5px;
                border-top: 1px solid #eee;
            }

            @media print {
                body { 
                    margin: 0; 
                    padding: 0; 
                    background-color: #fff;
                }
                .print-button-container { 
                    display: none; 
                }
                .voucher-grid {
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: flex-start;
                    align-content: flex-start;
                    gap: 0; /* No gap, use margins for spacing */
                    width: 100%;
                    padding: 0;
                }
                .voucher {
                    border: 1px dashed #999; /* Cutting guides */
                    box-shadow: none;
                    border-radius: 0;
                    margin: 2mm; /* Space out vouchers for cutting */
                }
            }
        </style>
    </head>
    <body>
    """]

    if include_print_button:
        html_parts.append("""
        <div class="print-button-container">
            <button class="print-button" onclick="window.print();">🖨️ Print Vouchers</button>
        </div>
        """)

    html_parts.append('<div class="voucher-grid">')

    for voucher in vouchers:
        username = voucher.get('username', 'N/A')
        password = voucher.get('password', 'N/A')
        limit_uptime = voucher.get('limit-uptime', '') # Get limit-uptime
        profile_name = voucher.get('profile', '') # Get profile, though not currently displayed

        time_limit_display = "Unlimited"
        if limit_uptime and limit_uptime != '0s':
            time_limit_display = limit_uptime
        
        qr_code_b64 = None

        if QRCODE_AVAILABLE and hotspot_login_url:
            try:
                # Use a smaller box size for the compact voucher design
                qr_code_b64 = generate_qr_code_base64(hotspot_login_url, username, password)
            except Exception as e:
                logger.warning(f"QR generation failed for {username}: {e}")

        html_parts.append(f"""
        <div class="voucher">
            <div class="voucher-header">""")
        if logo_data_url:
            html_parts.append(f"""<img src="{logo_data_url}" alt="Logo" style="max-height: 16px; margin-right: 8px; vertical-align: middle;">""") # Reduced max-height
        html_parts.append("""Hotspot Voucher</div>
            <div class="voucher-content">
                <div class="voucher-qr">
        """)

        if qr_code_b64:
            html_parts.append(f'<img src="data:image/png;base64,{qr_code_b64}" alt="QR Code for {username}">')
        else:
            html_parts.append('<div style="font-size:0.8em; color:#aaa; text-align:center;">QR Not Available</div>')

        html_parts.append(f"""
                </div>
                <div class="voucher-details">
                    <p><strong>Username:</strong></p>
                    <p><span>{username}</span></p>
                    <p><strong>Password:</strong></p>
                    <p><span>{password}</span></p>
                    <p><strong>Time Limit:</strong></p>
                    <p><span>{time_limit_display}</span></p>
                </div>
            </div>
            <div class="voucher-footer">📞 +211 923 616 820 | ✉️ justinkulang@gmail.com</div>
        </div>
        """)

    html_parts.append("</div></body></html>")
    return ''.join(html_parts)
@app.route('/api/vouchers/view_batch_html', methods=['POST'])
def view_batch_vouchers_html():
    try:
        vouchers_json = request.form.get('vouchers_json', '[]')
        hotspot_login_url = request.form.get('hotspot_login_url', '')
        vouchers = json.loads(vouchers_json)

        if not vouchers:
            return Response("No voucher data provided.", mimetype='text/html', status=400)
        
        html_content = _generate_vouchers_page_html(vouchers, hotspot_login_url, include_print_button=True)
        return Response(html_content, mimetype='text/html')

    except json.JSONDecodeError:
        logger.error("Failed to decode vouchers_json from form data.")
        return Response("Invalid voucher data provided.", mimetype='text/html', status=400)
    except Exception as e:
        logger.error(f"Error generating voucher HTML view: {e}")
        return Response(f"An error occurred while generating vouchers: {e}", mimetype='text/html', status=500)

@app.route('/api/vouchers/download_batch_pdf', methods=['POST'])
def download_batch_vouchers_pdf():
    if not WEASYPRINT_AVAILABLE:
        logger.warning("PDF export attempted but WeasyPrint is not available.")
        return jsonify({'success': False, 'message': 'PDF generation library not available on the server.'}), 501

    try:
        vouchers_json = request.form.get('vouchers_json', '[]')
        hotspot_login_url = request.form.get('hotspot_login_url', '')
        vouchers = json.loads(vouchers_json)

        if not vouchers:
            return jsonify({'success': False, 'message': 'No voucher data provided.'}), 400
        
        # Generate HTML without the print button for PDF rendering
        html_content = _generate_vouchers_page_html(vouchers, hotspot_login_url, include_print_button=False)
        
        pdf_file = WeasyHTML(string=html_content).write_pdf()
        
        return Response(
            pdf_file,
            mimetype="application/pdf",
            headers={"Content-disposition": "attachment; filename=vouchers_batch.pdf"}
        )
    except json.JSONDecodeError:
        logger.error("Failed to decode vouchers_json for PDF export.")
        return jsonify({'success': False, 'message': 'Invalid voucher data provided for PDF export.'}), 400
    except Exception as e:
        logger.error(f"Error generating voucher PDF: {e}")
        # Check if it's a WeasyPrint specific error that might hint at system dependencies
        if "No X11 connection" in str(e) or "GTK" in str(e):
             logger.error("WeasyPrint PDF generation failed, possibly due to missing X11/GTK dependencies on the server.")
             return jsonify({'success': False, 'message': 'PDF generation failed on server due to missing dependencies. Please check server logs.'}), 500
        return jsonify({'success': False, 'message': f'An unexpected error occurred during PDF generation: {str(e)}'}), 500

def get_mikrotik_api():
    """Establishes and returns a single Mikrotik API connection per request."""
    logger.debug(f"get_mikrotik_api: Current Mikrotik config host from module-level app_config: {app_config['mikrotik'].get('host')}")
    if 'mikrotik_api' not in g:
        logger.debug("get_mikrotik_api: 'mikrotik_api' not in g. Attempting new connection.")
        # Fetch the latest config directly from the loader instance for new connections
        current_loaded_config = config_loader.get_config() 
        mikrotik_config = current_loaded_config['mikrotik']
        logger.debug(f"get_mikrotik_api: Using host from config_loader.get_config(): {mikrotik_config.get('host')}")
        
        host, port, username, password, use_ssl = (
            mikrotik_config['host'], mikrotik_config['port'],
            mikrotik_config['username'], mikrotik_config['password'],
            mikrotik_config.get('use_ssl', False)
        )
        # Basic check for placeholder/default config before attempting connection
        if host == "192.168.88.1" and username == "admin" and password == "" and not os.path.exists(config_loader.config_file):
             logger.warning("get_mikrotik_api: Attempting to connect with default placeholder config and no config file saved yet. Connection will likely fail or use defaults.")
        
        logger.info(f"Attempting to connect to Mikrotik: {host}:{port} (SSL: {use_ssl})")
        api_connection_object = None  # Temporary holder for the connection object
        try:
            api_connection_object = librouteros.connect(
                host=host, username=username, password=password, port=port, ssl=use_ssl
            )
            # If connect succeeds, then assign to g
            g.mikrotik_connection = api_connection_object
            g.mikrotik_api = api_connection_object # In librouteros, connect() returns the api object directly
            logger.info("Mikrotik connection established successfully in get_mikrotik_api.")
        except (librouteros.exceptions.LibRouterosError, TrapError, socket.error, ConnectionRefusedError, OSError) as e:
            logger.error(f"Mikrotik connection failed in get_mikrotik_api: {type(e).__name__} - {e}")
            if api_connection_object: # If connect() returned an object before erroring or during partial setup
                try:
                    logger.debug("Attempting to close potentially partial Mikrotik connection object after failure.")
                    api_connection_object.close()
                except Exception as close_e:
                    logger.error(f"Error closing partial Mikrotik connection object: {close_e}")
            g.mikrotik_api = None
            g.pop('mikrotik_connection', None) # Ensure it's removed from g
        except Exception as e: # Catch any other unexpected error during connection
            logger.error(f"Unexpected generic error during Mikrotik connection in get_mikrotik_api: {type(e).__name__} - {e}")
            if api_connection_object: # If connect() returned an object before erroring
                try:
                    logger.debug("Attempting to close potentially partial Mikrotik connection (generic exception).")
                    api_connection_object.close()
                except Exception as close_e:
                    logger.error(f"Error closing partial Mikrotik connection (generic exception): {close_e}")
            g.mikrotik_api = None
            g.pop('mikrotik_connection', None) # Ensure it's removed from g
    else:
        # This 'else' case should ideally not be hit frequently if teardown_connection runs after each request.
        # If it is hit, it implies g.mikrotik_api persisted, which means teardown might not have run.
        # For safety, we could add a check here too, but the primary model is new connection per request.
        logger.warning("get_mikrotik_api: Reusing existing Mikrotik API from 'g'. This is unexpected with current teardown logic.")
        # Potentially add a health check for existing g.mikrotik_api here if this path becomes common.
        # For now, assume teardown works and this path is rare.
    
    api_to_return = g.get('mikrotik_api', None)
    logger.debug(f"get_mikrotik_api: Returning API object: {'Exists' if api_to_return else 'None'}")
    return api_to_return

@app.teardown_appcontext
def teardown_connection(exception):
    """Closes the Mikrotik connection after each request."""
    mikrotik_connection = g.pop('mikrotik_connection', None)
    if mikrotik_connection:
        mikrotik_connection.close()
        logger.info("Mikrotik connection closed.")


class RouterOSService:
    """Service class for all Mikrotik RouterOS interactions."""
    def __init__(self):
        pass # Connection is managed globally via get_mikrotik_api

    def test_connection(self) -> tuple[bool, str]:
        """Test connection to Mikrotik router."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Connection failed: Could not establish API session. Check config and router status."
            identity_records = list(api.path('system', 'identity').select('name'))

            router_name = 'Mikrotik Router'
            if identity_records:
                router_name = identity_records[0].get('name', 'Mikrotik Router')

            return True, f"Connected successfully to {router_name}"
        except ConnectionError as e:
            logger.error(f"Connection test failed: {e}")
            return False, f"Connection failed: {e}"
        except Exception as e:
            logger.error(f"Unexpected error during connection test: {str(e)}")
            return False, f"Unexpected error during connection test: {str(e)}"

    def get_hotspot_users(self) -> list:
        """Get all hotspot users."""
        try:
            api = get_mikrotik_api()
            if api is None:
                logger.error("Error getting users: Mikrotik API not available.")
                return []
            users = list(api.path('ip', 'hotspot', 'user').select(
                '.id', 'name', 'password', 'profile', 'disabled', 'limit-uptime', 'limit-bytes-total',
                'uptime', 'bytes-in', 'bytes-out', 'comment', 'limit-bytes-in', 'limit-bytes-out'
            ))
            return users
        except Exception as e:
            logger.error(f"Error getting users: {str(e)}")
            return []

    def create_hotspot_user(self, user_data: dict) -> tuple[bool, str]:
        """Create new hotspot user."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            # Clean up potential None values before sending to router
            valid_user_data = {k: v for k, v in user_data.items() if v is not None}
            api.path('ip', 'hotspot', 'user').add(**valid_user_data)
            return True, "User created successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error creating user: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def edit_hotspot_user(self, username: str, new_data: dict) -> tuple[bool, str]:
        """Edit existing hotspot user."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            users = list(api.path('ip', 'hotspot', 'user').select('.id').where(name=username))
            if not users:
                return False, "User not found"
            
            user_id = users[0]['.id']
            api.path('ip', 'hotspot', 'user').set(**new_data, **{'.id': user_id})
            return True, "User updated successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error editing user '{username}': {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def delete_hotspot_user(self, username: str) -> tuple[bool, str]:
        """Delete hotspot user."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            users = list(api.path('ip', 'hotspot', 'user').select('.id').where(name=username))
            if not users:
                return False, "User not found"

            user_id = users[0]['.id']
            api.path('ip', 'hotspot', 'user').remove(user_id)
            return True, "User deleted successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error deleting user '{username}': {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"
    
    def get_active_sessions(self) -> list:
        """Get active hotspot sessions."""
        try:
            api = get_mikrotik_api()
            if api is None:
                logger.error("Error getting active sessions: Mikrotik API not available.")
                return []
            sessions = list(api.path('ip', 'hotspot', 'active').select(
                'user', 'address', 'mac-address', 'uptime', 'bytes-in', 'bytes-out',
                'session-time-left', 'idle-time', '.id'
            ))
            return sessions
        except Exception as e:
            logger.error(f"Error getting active sessions: {str(e)}")
            return []

    def disconnect_user(self, active_id: str) -> tuple[bool, str]:
        """Disconnect active user session by its .id."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            api.path('ip', 'hotspot', 'active').remove(active_id)
            return True, "User disconnected successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error disconnecting user: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def get_user_profiles(self) -> list:
        """Get hotspot user profiles."""
        try:
            api = get_mikrotik_api()
            if api is None:
                logger.error("Error getting profiles: Mikrotik API not available.")
                return []
            profiles = list(api.path('ip', 'hotspot', 'user', 'profile').select(
                '.id', 'name', 'rate-limit', 'session-timeout', 'shared-users',
                'mac-cookie-timeout', 'keepalive-timeout'
            ))
            return profiles
        except Exception as e:
            logger.error(f"Error getting profiles: {str(e)}")
            return []
    
    def create_hotspot_profile(self, profile_data: dict) -> tuple[bool, str]:
        """Creates a new hotspot user profile."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            data_to_add = {k: v for k, v in profile_data.items() if v}
            api.path('ip', 'hotspot', 'user', 'profile').add(**data_to_add)
            return True, f"Profile '{profile_data['name']}' created successfully."
        except (TrapError, Exception) as e:
            logger.error(f"Error creating profile: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def edit_hotspot_profile(self, profile_id: str, new_data: dict) -> tuple[bool, str]:
        """Edits an existing hotspot user profile."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            api.path('ip', 'hotspot', 'user', 'profile').set(**new_data, **{'.id': profile_id})
            return True, "Profile updated successfully."
        except (TrapError, Exception) as e:
            logger.error(f"Error editing profile: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def delete_hotspot_profile(self, profile_id: str) -> tuple[bool, str]:
        """Deletes a hotspot user profile."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            api.path('ip', 'hotspot', 'user', 'profile').remove(profile_id)
            return True, "Profile deleted successfully."
        except (TrapError, Exception) as e:
            logger.error(f"Error deleting profile: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"
    
    def _parse_ros_time(self, time_str: str) -> int:
        """Parses RouterOS time string (e.g., 1w2d3h4m5s) into seconds."""
        if not time_str:
            return 0
        total_seconds = 0
        matches = re.findall(r'(\d+)([wdhms])', time_str)
        for value, unit in matches:
            value = int(value)
            if unit == 'w': total_seconds += value * 604800
            elif unit == 'd': total_seconds += value * 86400
            elif unit == 'h': total_seconds += value * 3600
            elif unit == 'm': total_seconds += value * 60
            elif unit == 's': total_seconds += value
        return total_seconds

    def find_and_delete_expired_users(self) -> tuple[bool, str, int]:
        """Finds and deletes users who have exceeded their time or data limits."""
        try:
            api = get_mikrotik_api()
            if api is None: # Check if API connection failed initially
                return False, "Mikrotik connection not available", 0
            
            users = self.get_hotspot_users() 
            # get_hotspot_users itself will return [] if api was None, so this is safe.
            # However, if api was None for this call but not for the initial api check,
            # we might want to re-check. But the current pattern is one api per request.
            if not users and api is None: # If users list is empty because api became None
                 return False, "Mikrotik connection not available (users fetch failed)", 0

            deleted_count = 0
            errors = []

            for user in users:
                is_expired = False
                # Check time limit
                if user.get('limit-uptime') and user['limit-uptime'] != '0s':
                    limit_sec = self._parse_ros_time(user['limit-uptime'])
                    usage_sec = self._parse_ros_time(user.get('uptime', '0s'))
                    if limit_sec > 0 and usage_sec >= limit_sec:
                        is_expired = True

                # Check total data limit
                if not is_expired and user.get('limit-bytes-total') and int(user['limit-bytes-total']) > 0:
                    limit_bytes = int(user['limit-bytes-total'])
                    usage_bytes = int(user.get('bytes-in', 0)) + int(user.get('bytes-out', 0))
                    if usage_bytes >= limit_bytes:
                        is_expired = True
                
                if is_expired:
                    try:
                        api.path('ip', 'hotspot', 'user').remove(user['.id'])
                        deleted_count += 1
                        logger.info(f"Deleted expired user '{user['name']}'")
                    except Exception as e:
                        errors.append(user['name'])
                        logger.error(f"Failed to delete expired user '{user['name']}': {e}")
            
            message = f"Successfully deleted {deleted_count} expired user(s)."
            if errors:
                message += f" Failed to delete: {', '.join(errors)}."
            
            return True, message, deleted_count
        except Exception as e:
            logger.error(f"Error during expired user cleanup: {str(e)}")
            return False, f"An unexpected error occurred: {str(e)}", 0

    def get_basic_bandwidth_analytics(self) -> dict:
        """Calculates basic bandwidth analytics from hotspot user data."""
        users = self.get_hotspot_users() # This already handles API non-availability by returning []
        
        default_analytics = {
            'total_data_all_users': 0,
            'all_users_sorted_by_data': [],
            'data_usage_by_profile': {}
        }

        if not users: # Covers API failure or no users
            return default_analytics

        total_data_all_users = 0
        users_with_total_data = []
        data_by_profile = {}

        for user in users:
            try:
                # Ensure bytes are treated as numbers, default to 0 if not present or not convertible
                bytes_in = int(user.get('bytes-in', 0) or 0)
                bytes_out = int(user.get('bytes-out', 0) or 0)
            except ValueError: # Handle case where byte counts are not valid integers
                logger.warning(f"User '{user.get('name', 'Unknown')}' has invalid byte count, treating as 0.")
                bytes_in = 0
                bytes_out = 0
                
            user_total_data = bytes_in + bytes_out
            total_data_all_users += user_total_data

            users_with_total_data.append({
                'name': user.get('name'),
                'profile': user.get('profile'),
                'bytes_in': bytes_in,
                'bytes_out': bytes_out,
                'total_data': user_total_data,
                'comment': user.get('comment') 
            })

            profile_name = user.get('profile', 'N/A')
            data_by_profile[profile_name] = data_by_profile.get(profile_name, 0) + user_total_data
            
        sorted_users = sorted(users_with_total_data, key=lambda u: u['total_data'], reverse=True)

        return {
            'total_data_all_users': total_data_all_users,
            'all_users_sorted_by_data': sorted_users,
            'data_usage_by_profile': data_by_profile
        }

    def delete_users_by_profile(self, profile_name: str) -> tuple[bool, str, int]:
        """Deletes hotspot users belonging to a specific profile."""
        api = get_mikrotik_api()
        if api is None:
            return False, "Mikrotik connection not available", 0

        users = self.get_hotspot_users()
        if not users and get_mikrotik_api() is None: # Re-check API status if user list is empty
            return False, "Mikrotik connection not available (users fetch failed)", 0

        deleted_count = 0
        failed_count = 0
        users_to_delete_ids = []

        for user in users:
            if user.get('profile') == profile_name:
                users_to_delete_ids.append(user['.id'])

        if not users_to_delete_ids:
            return True, f"No users found for profile '{profile_name}'. Nothing to delete.", 0

        for user_id in users_to_delete_ids:
            try:
                api.path('ip', 'hotspot', 'user').remove(user_id)
                deleted_count += 1
            except (TrapError, Exception) as e:
                logger.error(f"Failed to delete user with ID '{user_id}' from profile '{profile_name}': {e}")
                failed_count += 1
        
        message = f"Successfully deleted {deleted_count} user(s) from profile '{profile_name}'."
        if failed_count > 0:
            message += f" Failed to delete {failed_count} user(s)."
        
        return True, message, deleted_count

    def delete_users_by_active_status(self, is_disabled: bool) -> tuple[bool, str, int]:
        """Deletes hotspot users based on their active (enabled/disabled) status."""
        api = get_mikrotik_api()
        if api is None:
            return False, "Mikrotik connection not available", 0

        users = self.get_hotspot_users()
        if not users and get_mikrotik_api() is None: # Re-check API status if user list is empty
            return False, "Mikrotik connection not available (users fetch failed)", 0

        deleted_count = 0
        failed_count = 0
        target_status_str = 'true' if is_disabled else 'false'
        users_to_delete_ids = []

        for user in users:
            if user.get('disabled') == target_status_str:
                users_to_delete_ids.append(user['.id'])
        
        status_desc = "disabled" if is_disabled else "active (enabled)"
        if not users_to_delete_ids:
            return True, f"No {status_desc} users found. Nothing to delete.", 0

        for user_id in users_to_delete_ids:
            try:
                api.path('ip', 'hotspot', 'user').remove(user_id)
                deleted_count += 1
            except (TrapError, Exception) as e:
                logger.error(f"Failed to delete user with ID '{user_id}' (status: {status_desc}): {e}")
                failed_count += 1
        
        message = f"Successfully deleted {deleted_count} {status_desc} user(s)."
        if failed_count > 0:
            message += f" Failed to delete {failed_count} user(s)."
            
        return True, message, deleted_count

router_os_service = RouterOSService()

# --- Helper Functions ---
def format_bytes_for_export(bytes_val):
    if not bytes_val or bytes_val == '0' or bytes_val == '': return "Unlimited"
    try:
        numeric_bytes = float(bytes_val)
        if numeric_bytes == 0: return "Unlimited"
        k = 1024
        sizes = ['B', 'KB', 'MB', 'GB', 'TB']
        if numeric_bytes < 1: return f"{numeric_bytes:.0f} B"
        i = min(len(sizes) - 1, int(math.floor(math.log(numeric_bytes) / math.log(k))))
        return f"{numeric_bytes / math.pow(k, i):.2f} {sizes[i]}"
    except (ValueError, TypeError):
        return str(bytes_val)

def generate_qr_code_base64(login_url, username, password):
    """Generates a QR code for login and returns a Base64 encoded string."""
    if not QRCODE_AVAILABLE: return None
    
    full_url = f"{login_url}?username={username}&password={password}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(full_url)
    qr.make(fit=True)
    
    img = qr.make_image(image_factory=StyledPilImage, module_drawer=RoundedModuleDrawer())
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# --- Flask Routes ---
@app.route('/')
def login_page():
    """Serves the login page. If already logged into the app, redirects to dashboard."""
    if current_user.is_authenticated:
        api = get_mikrotik_api()
        if api:
            return redirect(url_for('index'))
    # For login page, generate and pass CSRF token if not using WTForms directly in template
    # However, login.html uses JS fetch, so token needs to be available to JS
    # One way is to render it in a meta tag or a script variable in login.html itself.
    # The dashboard route already does this for mikrotik_userman_dashboard.html
    # For login.html, we can add a similar mechanism or rely on a global JS var if set.
    # Let's ensure login.html can also get a CSRF token.
    # A simple way for login.html, since it's served by Flask, is to inject it.
    # This is typically done if the form is generated by Flask-WTF.
    # Since forms in login.html are custom, we'll handle token in JS.
    # The CSRF token is implicitly available via csrf_token() in templates,
    # or can be generated via generate_csrf() and passed to render_template.
    # For now, we assume JS will fetch it or have it available (see login.html modifications).
    return render_template('login.html')


@app.route('/app-login', methods=['POST'])
# This route is already protected by default by Flask-WTF's CSRF protection for POST requests.
# No need to add @csrf.exempt if we intend to protect it.
def app_login_route():
    """Handles web application login."""
    data = request.form
    username = data.get('app_username')
    password = data.get('app_password')

    admin_config = app_config.get('app_admin', {})
    admin_username = admin_config.get('username')
    admin_password_hashed = admin_config.get('password_hash')

    if not admin_username or not admin_password_hashed:
        logger.error("App admin username or password hash not configured in config.json.")
        return jsonify({'success': False, 'message': _('App login not configured on server.')}), 500

    if username == admin_username and check_password_hash(admin_password_hashed, password):
        user = User.get(username)
        if user:
            login_user(user, remember=True, duration=app.config['PERMANENT_SESSION_LIFETIME'])
            logger.info(f"User '{username}' logged in successfully to the web application.")
            return jsonify({'success': True, 'message': _('Web app login successful.')})
        else: # Should not happen if User.get is consistent
            logger.error(f"User.get failed for '{username}' after successful credential check.")
            return jsonify({'success': False, 'message': _('Login failed. User object could not be created.')}), 500
    else:
        logger.warning(f"Failed login attempt for app user '{username}'.")
        return jsonify({'success': False, 'message': _('Invalid web app username or password.')}), 401


@app.route('/dashboard')
@login_required # Protect this route
def index():
    """Serves the main dashboard page."""
    return render_template('mikrotik_userman_dashboard.html')

@app.route('/api/initial-connect', methods=['POST'])
# No @login_required here, as it's for the Mikrotik connection setup,
# but it should only be callable after app login.
# The before_request_handler already protects it if user is not authenticated.
def initial_connect():
    global app_config # Ensure we're updating the global app_config
    data = request.json
    errors = {}

    host = data.get('host')
    port_str = data.get('port') # Port comes as string or number from JSON
    username = data.get('username')
    password = data.get('password') # Password can be empty, so no direct validation other than type if needed

    if not host:
        errors['host'] = _('Host IP address or hostname is required.')
    elif len(host) > 255: # General length limit for hostnames/IPs
        errors['host'] = _('Host is too long.')
    # Basic regex for IP or hostname (can be improved for stricter validation)
    # elif not re.match(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$|^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$", host):
    #     errors['host'] = _('Invalid host format. Must be a valid IP address or hostname.')


    port = None
    if port_str is None: # Check if port is provided at all
        errors['port'] = _('Port is required.')
    else:
        try:
            port = int(port_str)
            if not (1 <= port <= 65535): # API ports are typically 1-65535
                errors['port'] = _('Port must be a number between 1 and 65535.')
        except ValueError:
            errors['port'] = _('Port must be a valid number.')

    if not username:
        errors['username'] = _('Username is required.')
    elif len(username) > 64:
         errors['username'] = _('Username must be 64 characters or less.')

    # Password can be empty for some Mikrotik setups, so only length validation if not empty
    if password and len(password) > 128: # Arbitrary reasonable max length
        errors['password'] = _('Password must be 128 characters or less.')


    if errors:
        return jsonify({'success': False, 'message': _('Validation failed.'), 'errors': errors}), 400

    # Proceed with connection attempt if validation passed
    # Port is already an int here if validation passed
    logger.info(f"Attempting initial connection to Mikrotik: {host}:{port} with user: {username}")
    try:
        # Attempt connection
        temp_conn = librouteros.connect(
            host=host,
            username=username,
            password=password,
            port=port,
            ssl=app_config['mikrotik'].get('use_ssl', False) # Use current SSL setting or default
        )
        temp_conn.close() # Close if successful, we just tested it.
        logger.info("Initial connection test successful.")

        # Update config.json
        new_mikrotik_config = {
            "host": host,
            "port": port,
            "username": username,
            "password": password, # Save the password
            "use_ssl": app_config['mikrotik'].get('use_ssl', False), # Preserve existing SSL setting
            "hotspot_login_url": app_config['mikrotik'].get('hotspot_login_url', '') # Preserve existing
        }
        config_loader.update_config({'mikrotik': new_mikrotik_config})
        app_config = config_loader.get_config() # Reload app_config to reflect changes

        return jsonify({'success': True, 'message': 'Successfully connected and configuration saved.'})

    except (librouteros.exceptions.LibRouterosError, TrapError, socket.error, ConnectionRefusedError, OSError) as e:
        logger.error(f"Initial connection failed: {e}")
        # Sanitize error message for user
        error_message = str(e)
        if "authentication failed" in error_message.lower():
            return jsonify({'success': False, 'message': 'Authentication failed. Please check username and password.'}), 401
        elif "connection refused" in error_message.lower() or "timed out" in error_message.lower() or "no route to host" in error_message.lower():
            return jsonify({'success': False, 'message': 'Connection refused or timed out. Check IP address, port, and router firewall.'}), 400
        return jsonify({'success': False, 'message': f'Connection failed: {e}.'}), 400
    except Exception as e:
        logger.error(f"Unexpected error during initial connection: {e}")
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {e}.'}), 500


@app.route('/api/test-connection', methods=['POST'])
@login_required
def test_connection():
    success, message = router_os_service.test_connection()
    return jsonify({'success': success, 'message': message})

@app.route('/api/config', methods=['GET'])
@login_required
def get_config_route():
    cfg = config_loader.get_config()
    # Add status of optional features
    cfg['features'] = {
        'pdf_export': WEASYPRINT_AVAILABLE,
        'qr_codes': QRCODE_AVAILABLE
    }
    # Add app_admin section but without password for security
    app_admin_secure = cfg.get('app_admin', {}).copy()
    app_admin_secure.pop('password_hash', None) # Remove password hash
    cfg['app_admin_display'] = app_admin_secure

    return jsonify(cfg)

@app.route('/api/config', methods=['POST'])
@login_required
def update_config_route():
    data = request.json
    # Prevent app_admin password_hash from being updated directly via this generic route
    # It should be handled by a dedicated password change route (not in scope for this subtask)
    if 'app_admin' in data:
        # If 'app_admin' is present, make sure it doesn't try to wipe/change password_hash
        # Best is to pop it and instruct user to use a dedicated mechanism if they want to change app user details
        data.pop('app_admin', None)
        # Or, more carefully, preserve existing password if username is updated
        # current_admin_config = config_loader.get_config().get('app_admin', {})
        # if 'username' in data.get('app_admin', {}): # if new username is provided
        #    data['app_admin']['password_hash'] = current_admin_config.get('password_hash')

    # Filter out any attempt to update sensitive fields that should be managed by env vars or dedicated routes
    if 'mikrotik' in data and 'password' in data['mikrotik'] and os.environ.get('MIKROTIK_PASSWORD'):
        logger.warning("Attempt to update Mikrotik password via general config update while MIKROTIK_PASSWORD env var is set. Password update ignored.")
        del data['mikrotik']['password']
        if not data['mikrotik']: # if password was the only key
            del data['mikrotik']


    config_loader.update_config(data)
    # Reload app_config in case server settings like port/host were changed,
    # though these typically require a server restart to take effect.
    global app_config
    app_config = config_loader.get_config()
    return jsonify({'success': True, 'message': _('Configuration updated and saved. Some changes may require a server restart.')})

@app.route('/api/admin/change-password', methods=['POST'])
@login_required
def change_admin_password():
    global app_config
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_new_password = data.get('confirm_new_password')

    if not all([current_password, new_password, confirm_new_password]):
        return jsonify({'success': False, 'message': _('All password fields are required.')}), 400

    if new_password != confirm_new_password:
        return jsonify({'success': False, 'message': _('New passwords do not match.')}), 400

    # Basic password policy (example: min 8 chars)
    if len(new_password) < 8:
        return jsonify({'success': False, 'message': _('New password must be at least 8 characters long.')}), 400
    # Add more complexity checks if desired (e.g., uppercase, lowercase, number, symbol)
    # For example:
    # if not re.search(r"[A-Z]", new_password) or \
    #    not re.search(r"[a-z]", new_password) or \
    #    not re.search(r"\d", new_password) or \
    #    not re.search(r"[!@#$%^&*(),.?\":{}|<>]", new_password):
    #     return jsonify({'success': False, 'message': _('New password must include uppercase, lowercase, number, and symbol.')}), 400


    admin_username = app_config.get('app_admin', {}).get('username')
    current_hash = app_config.get('app_admin', {}).get('password_hash')

    if not current_user.is_authenticated or current_user.get_id() != admin_username:
        # Should not happen if @login_required works correctly and only one admin user
        return jsonify({'success': False, 'message': _('Unauthorized.')}), 401

    if not check_password_hash(current_hash, current_password):
        return jsonify({'success': False, 'message': _('Incorrect current password.')}), 400

    # Check if password hash is managed by environment variable
    if os.environ.get('APP_ADMIN_PASSWORD_HASH'):
        logger.warning(f"Admin user '{admin_username}' attempted to change password via UI, but password hash is managed by APP_ADMIN_PASSWORD_HASH environment variable.")
        return jsonify({
            'success': False,
            'message': _('Password change via UI is disabled because the admin password is managed by an environment variable. Please update the environment variable and restart the application.')
        }), 403 # Forbidden

    new_hash = generate_password_hash(new_password)
    if config_loader.update_admin_password_hash(new_hash):
        app_config = config_loader.get_config() # Reload config
        logger.info(f"Admin user '{admin_username}' password changed successfully via UI.")
        # Optionally, force logout other sessions for this user if that becomes relevant
        return jsonify({'success': True, 'message': _('Admin password updated successfully.')})
    else:
        logger.error(f"Failed to save new admin password hash to config file for user '{admin_username}'.")
        return jsonify({'success': False, 'message': _('Failed to update password. Check server logs.')}), 500


@app.route('/api/dashboard-stats', methods=['GET'])
@login_required
def get_dashboard_stats():
    users = router_os_service.get_hotspot_users()
    sessions = router_os_service.get_active_sessions()
    total_users = len(users)
    active_sessions = len(sessions)
    return jsonify({'total_users': total_users, 'active_sessions': active_sessions})

@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    users = router_os_service.get_hotspot_users()
    return jsonify({'users': users})

@app.route('/api/users', methods=['POST'])
@login_required
def create_user():
    data = request.json

    # --- Input Validation for Create User ---
    errors = {}
    username = data.get('name')
    password = data.get('password')
    profile = data.get('profile') # Profile is also crucial

    if not username:
        errors['name'] = _('Username is required.')
    elif not (3 <= len(username) <= 64): # Example length constraints
        errors['name'] = _('Username must be between 3 and 64 characters.')
    # Add regex for allowed characters in username if necessary, e.g.,
    # elif not re.match(r"^[a-zA-Z0-9_-]+$", username):
    #     errors['name'] = _('Username can only contain letters, numbers, underscore, and hyphen.')


    if not password:
        errors['password'] = _('Password is required.')
    elif not (6 <= len(password) <= 64): # Example length constraints
        errors['password'] = _('Password must be between 6 and 64 characters.')

    if not profile: # Assuming profile name is sent and is required
        errors['profile'] = _('Profile is required.')
    
    # Optional fields validation (example for comment)
    comment = data.get('comment')
    if comment and len(comment) > 128: # Max length for comment
        errors['comment'] = _('Comment cannot exceed 128 characters.')

    # Validate time limit format (basic example, can be more complex)
    limit_uptime = data.get('limit-uptime')
    if limit_uptime and not re.match(r"^((\d+[wdhms])+)?$", limit_uptime):
        errors['limit-uptime'] = _('Invalid time limit format. Use units like 1d, 2h30m, etc.')

    # Validate data limit (must be a number if provided)
    limit_bytes_total_mb = data.get('limit-bytes-total') # Assuming this is still passed as MB string from UI
    if limit_bytes_total_mb:
        try:
            # The field name in API is 'limit-bytes-total' for the RouterOSService,
            # but the form in HTML passes 'dataLimit' which is then converted.
            # Assuming 'data' here contains 'limit-bytes-total' after potential conversion.
            # If it's passed as 'dataLimit' (MB string) from JS, it's converted before user_data.
            # Let's assume `data` here is the raw JSON from request.
            # The actual conversion to bytes happens later in the original code.
            # For validation, we check if it's a number.
            # The `create_hotspot_user` expects `limit-bytes-total` as integer bytes or null.
            # The original UI sends `dataLimit` as MB.
            # This part of validation might need adjustment based on how `data` is structured for this route.
            # For now, let's assume `data.get('limit-bytes-total')` is the numeric value in MB from UI.
            # The transformation to bytes (value * 1024 * 1024) is done before calling router_os_service.
            # So, data['limit-bytes-total'] in the payload to router_os_service will be bytes.
            # Let's validate the 'dataLimit' field if it's coming directly from UI as 'dataLimit' in MB.
            # Assuming the 'data' dict for this route uses 'name', 'password', 'profile', 'limit-uptime', 'dataLimit', 'comment'
            # And then it's transformed before calling `create_hotspot_user`.
            # The current `createUserForm` in HTML uses `id="dataLimit"`.
            # Let's adjust the payload construction:

            # The existing code for createUser route is:
            # payload = { name: ..., password: ..., profile: ..., 'limit-uptime': ...,
            #             'limit-bytes-total': data.get('dataLimit') ? parseInt(data.get('dataLimit')) * 1024 * 1024 : null, ... }
            # So the `data` here is the direct JSON from the request.
            # We should validate `data.get('dataLimit')`
            data_limit_mb_str = data.get('dataLimit') # This comes from the form with id="dataLimit"
            if data_limit_mb_str: # If it's provided
                if not data_limit_mb_str.isdigit() or int(data_limit_mb_str) < 0:
                    errors['dataLimit'] = _('Data limit must be a non-negative number (MB).')
        except ValueError: # Should be caught by isdigit
             errors['dataLimit'] = _('Invalid data limit. Must be a number (MB).')


    if errors:
        return jsonify({'success': False, 'message': _('Validation failed.'), 'errors': errors}), 400
    # --- End Input Validation ---

    # Prepare payload for RouterOSService (as it was originally structured)
    # This transformation should ideally happen AFTER validation of raw inputs
    payload_for_service = {
        'name': username,
        'password': password,
        'profile': profile,
        'comment': comment,
        'limit-uptime': limit_uptime if limit_uptime else None, # Send None if empty for router
        'limit-bytes-total': int(data.get('dataLimit')) * 1024 * 1024 if data.get('dataLimit') and data.get('dataLimit').isdigit() else None
    }
    # Remove None values before sending to service, as original code did for create_hotspot_user
    payload_for_service = {k: v for k, v in payload_for_service.items() if v is not None}


    success, message = router_os_service.create_hotspot_user(payload_for_service)
    return jsonify({'success': success, 'message': message})

@app.route('/api/bulk-create-users', methods=['POST'])
@login_required
def bulk_create_users():
    data = request.json
    errors = {}

    # --- Input Validation for Bulk Create Users ---
    # Define character sets early for validation
    safe_symbols = '!@#$%^&*-=+'
    VALID_CHARSETS = {
        'alphanumeric': string.ascii_letters + string.digits,
        'alphanumeric_upper': string.ascii_uppercase + string.digits,
        'alphanumeric_lower': string.ascii_lowercase + string.digits,
        'numeric': string.digits,
        'alpha_upper': string.ascii_uppercase,
        'alpha_lower': string.ascii_lowercase,
        'alphanumeric_symbols': string.ascii_letters + string.digits + safe_symbols
    }

    try:
        number_of_users = int(data.get('number_of_users', 0))
        if not (1 <= number_of_users <= 1000): # Example: Max 1000 users at a time
            errors['number_of_users'] = _('Number of users must be between 1 and 1000.')
    except (ValueError, TypeError):
        errors['number_of_users'] = _('Number of users must be a valid integer.')

    profile = data.get('profile')
    if not profile:
        errors['profile'] = _('Profile is required.')
    elif len(profile) > 64:
        errors['profile'] = _('Profile name cannot exceed 64 characters.')

    try:
        username_length = int(data.get('username_length', 6))
        if not (3 <= username_length <= 16):
            errors['username_length'] = _('Username length must be between 3 and 16.')
    except (ValueError, TypeError):
        errors['username_length'] = _('Username length must be a valid integer.')

    try:
        password_length = int(data.get('password_length', 8))
        if not (6 <= password_length <= 16):
            errors['password_length'] = _('Password length must be between 6 and 16.')
    except (ValueError, TypeError):
        errors['password_length'] = _('Password length must be a valid integer.')

    username_prefix = data.get('username_prefix', '')
    if len(username_prefix) > 16:
        errors['username_prefix'] = _('Username prefix cannot exceed 16 characters.')

    username_charset_key = data.get('username_charset', 'alphanumeric')
    if username_charset_key not in VALID_CHARSETS:
        errors['username_charset'] = _('Invalid username character set selected.')

    password_charset_key = data.get('password_charset', 'alphanumeric_symbols')
    if password_charset_key not in VALID_CHARSETS:
        errors['password_charset'] = _('Invalid password character set selected.')

    comment_for_batch = data.get('comment_prefix', '') # This is the batch name/comment
    if len(comment_for_batch) > 128:
        errors['comment_prefix'] = _('Batch name/comment cannot exceed 128 characters.')

    limit_uptime = data.get('limit-uptime') # Optional
    if limit_uptime and not re.match(r"^((\d+[wdhms])+)?$", limit_uptime):
        errors['limit-uptime'] = _('Invalid time limit format. Use units like 1d, 2h30m, etc.')

    # Key from UI is 'bulkDataLimit' for this form
    bulk_data_limit_mb_str = data.get('bulkDataLimit') # Optional, in MB
    limit_bytes_total_for_service = None
    if bulk_data_limit_mb_str: # If provided
        if not bulk_data_limit_mb_str.isdigit() or int(bulk_data_limit_mb_str) < 0:
            errors['bulkDataLimit'] = _('Bulk data limit must be a non-negative number (MB).')
        else:
            limit_bytes_total_for_service = int(bulk_data_limit_mb_str) * 1024 * 1024

    if errors:
        return jsonify({'success': False, 'message': _('Validation failed.'), 'errors': errors}), 400
    # --- End Input Validation ---

    username_chars = VALID_CHARSETS.get(username_charset_key) # Already validated
    password_chars = VALID_CHARSETS.get(password_charset_key) # Already validated

    # Prepare base data for each user, similar to original logic but using validated/processed inputs
    base_user_data = {'profile': profile}
    if limit_uptime:
        base_user_data['limit-uptime'] = limit_uptime
    if limit_bytes_total_for_service is not None: # Can be 0
        base_user_data['limit-bytes-total'] = limit_bytes_total_for_service
    # 'server' was in original base_user_data_keys, but not used for user creation attributes. Removed.
    # if data.get('server'): # This field is not typically part of user creation data.
    #     base_user_data['server'] = data.get('server')


    created_credentials = []
    errors = []
    
    for i in range(int(number_of_users)): # Changed loop variable from _ to i
        random_username_part = ''.join(random.choices(username_chars, k=username_length))
        username = username_prefix + random_username_part
        password = ''.join(random.choices(password_chars, k=password_length))
        
        user_data = base_user_data.copy()
        user_data['name'] = username
        user_data['password'] = password
        
        if comment_for_batch: # Use the batch comment if provided
            user_data['comment'] = comment_for_batch
        # else, no comment is set for the user

        success, msg = router_os_service.create_hotspot_user(user_data)
        if success:
            created_credentials.append({
                'username': username,
                'password': password,
                'limit-uptime': user_data.get('limit-uptime', 'Unlimited'), # Get from user_data used for creation
                'profile': user_data.get('profile', '') # Get profile from user_data
            })
        else:
            errors.append({'username': username, 'error': msg})

    return jsonify({
        'success': len(errors) == 0,
        'message': _("Created {0} users. Failed: {1}.").format(len(created_credentials), len(errors)),
        'created_credentials': created_credentials,
        'errors': errors
    })

@app.route('/api/users/<username>', methods=['PUT'])
@login_required
def edit_user(username: str):
    raw_data = request.json
    errors = {}

    # --- Input Validation for Edit User ---
    # For editing, all fields are optional in the request, but if provided, they must be valid.

    new_password = raw_data.get('password')
    if new_password is not None: # Only validate if password is being changed
        if not (6 <= len(new_password) <= 64):
            errors['password'] = _('New password must be between 6 and 64 characters.')

    profile = raw_data.get('profile')
    if profile is not None and not profile: # If key is present but value is empty string
        errors['profile'] = _('Profile cannot be empty if provided.')
    elif profile is not None and len(profile) > 64: # Max length for profile name
        errors['profile'] = _('Profile name cannot exceed 64 characters.')

    limit_uptime = raw_data.get('limit-uptime')
    if limit_uptime is not None and limit_uptime != "" and not re.match(r"^((\d+[wdhms])+)?$", limit_uptime):
        errors['limit-uptime'] = _('Invalid time limit format. Use units like 1d, 2h30m, etc., or leave blank for no change/unlimited based on profile.')

    # dataLimit comes from UI as MB string, needs to be converted to bytes for limit-bytes-total
    # The key in raw_data from the UI form (editUserModal) is 'editDataLimit' for the numeric input.
    # The service expects 'limit-bytes-total'.
    data_limit_mb_str = raw_data.get('dataLimit') # Assuming UI sends 'dataLimit'

    limit_bytes_total_for_service = None # Initialize
    if data_limit_mb_str is not None: # If the key is present
        if data_limit_mb_str == "": # User wants to clear the limit
            limit_bytes_total_for_service = "0" # Send "0" to effectively remove limit or set to 0 bytes
        elif not data_limit_mb_str.isdigit() or int(data_limit_mb_str) < 0:
            errors['dataLimit'] = _('Data limit must be a non-negative number (MB) or empty to clear.')
        else:
            # Valid number, prepare for service
            limit_bytes_total_for_service = int(data_limit_mb_str) * 1024 * 1024

    comment = raw_data.get('comment')
    if comment is not None and len(comment) > 128:
        errors['comment'] = _('Comment cannot exceed 128 characters.')

    disabled_val = raw_data.get('disabled') # Expecting boolean true/false from JSON
    if disabled_val is not None and not isinstance(disabled_val, bool):
        errors['disabled'] = _('Disabled status must be a true/false value.')

    if errors:
        return jsonify({'success': False, 'message': _('Validation failed.'), 'errors': errors}), 400
    # --- End Input Validation ---

    # Construct the payload for the router_os_service, only including fields that were actually sent
    payload_for_service = {}
    if new_password is not None: # Allow empty string to clear password if Mikrotik supports, otherwise service might reject
        payload_for_service['password'] = new_password
    if profile is not None:
        payload_for_service['profile'] = profile
    if limit_uptime is not None: # Allow empty string to potentially clear limit
        payload_for_service['limit-uptime'] = limit_uptime

    if data_limit_mb_str is not None: # This means the dataLimit field was in the request
        if limit_bytes_total_for_service == "0": # Explicitly clearing
             payload_for_service['limit-bytes-total'] = 0 # Set to 0 for Mikrotik
        elif limit_bytes_total_for_service is not None: # Is a number from valid input
             payload_for_service['limit-bytes-total'] = limit_bytes_total_for_service
        # If data_limit_mb_str was None, 'limit-bytes-total' is not added to payload_for_service

    if comment is not None:
        payload_for_service['comment'] = comment
    if disabled_val is not None:
        payload_for_service['disabled'] = 'true' if disabled_val else 'false'

    if not payload_for_service: # Nothing to update
        return jsonify({'success': True, 'message': _('No changes detected to update.')})

    success, message = router_os_service.edit_hotspot_user(username, payload_for_service)
    return jsonify({'success': success, 'message': message})

@app.route('/api/users/<username>', methods=['DELETE'])
@login_required
def delete_user(username: str):
    success, message = router_os_service.delete_hotspot_user(username)
    return jsonify({'success': success, 'message': message})

@app.route('/api/active-sessions', methods=['GET'])
@login_required
def get_active_sessions_route():
    sessions = router_os_service.get_active_sessions()
    return jsonify({'sessions': sessions})

@app.route('/api/disconnect-user/<active_id>', methods=['POST'])
@login_required
def disconnect_user_session(active_id: str):
    success, message = router_os_service.disconnect_user(active_id)
    return jsonify({'success': success, 'message': message})

@app.route('/api/delete-expired-users', methods=['POST'])
@login_required
def delete_expired_users_route():
    success, message, count = router_os_service.find_and_delete_expired_users()
    return jsonify({'success': success, 'message': message, 'deleted_count': count})

@app.route('/api/users/delete-by-profile/<profile_name>', methods=['DELETE'])
@login_required
def delete_users_by_profile_route(profile_name: str):
    try:
        success, message, deleted_count = router_os_service.delete_users_by_profile(profile_name)
        # Assuming message from service is already i18n or generic
        return jsonify({'success': success, 'message': message, 'deleted_count': deleted_count})
    except Exception as e:
        logger.error(f"Error in delete_users_by_profile_route for profile '{profile_name}': {str(e)}")
        user_message = _("An unexpected error occurred while deleting users by profile.")
        return jsonify({'success': False, 'message': user_message, 'deleted_count': 0}), 500

@app.route('/api/users/delete-by-active-status/<status>', methods=['DELETE'])
@login_required
def delete_users_by_active_status_route(status: str):
    is_disabled: bool
    if status.lower() == 'disabled':
        is_disabled = True
    elif status.lower() == 'active':
        is_disabled = False
    else:
        return jsonify({
            'success': False,
            'message': _('Invalid status parameter. Must be "active" or "disabled".'),
            'deleted_count': 0
        }), 400
    try:
        success, message, deleted_count = router_os_service.delete_users_by_active_status(is_disabled)
        return jsonify({'success': success, 'message': message, 'deleted_count': deleted_count})
    except Exception as e:
        status_desc = "disabled" if is_disabled else "active"
        logger.error(f"Error in delete_users_by_active_status_route for {status_desc} users: {str(e)}")
        user_message = _("An unexpected error occurred while deleting users by status.")
        return jsonify({'success': False, 'message': user_message, 'deleted_count': 0}), 500

# --- Profile Management Routes ---
@app.route('/api/profiles', methods=['GET'])
@login_required
def get_profiles_route():
    profiles = router_os_service.get_user_profiles()
    return jsonify({'profiles': profiles})

@app.route('/api/profiles', methods=['POST'])
@login_required
def create_profile_route():
    data = request.json
    errors = {}

    # --- Input Validation for Create Profile ---
    profile_name = data.get('name')
    if not profile_name:
        errors['name'] = _('Profile name is required.')
    elif not (3 <= len(profile_name) <= 64):
        errors['name'] = _('Profile name must be between 3 and 64 characters.')
    # Potential regex for profile name characters (e.g., alphanumeric, hyphen, underscore)
    # elif not re.match(r"^[a-zA-Z0-9_-]+$", profile_name):
    #     errors['name'] = _('Profile name can only contain letters, numbers, underscore, and hyphen.')

    rate_limit = data.get('rate-limit')
    if rate_limit and not re.match(r"^((\d+[kKMGT]?/\d+[kKMGT]?)|(\d+[kKMGT]?))?$", rate_limit):
        errors['rate-limit'] = _('Invalid rate limit format. Example: 512k/2M or 1M.')

    session_timeout = data.get('session-timeout')
    if session_timeout and not re.match(r"^((\d+[wdhms])+|none)?$", session_timeout): # 'none' is often valid for no timeout
        errors['session-timeout'] = _('Invalid session timeout format. Example: 1d, 2h30m, or "none".')

    shared_users_str = data.get('shared-users')
    if shared_users_str:
        try:
            shared_users = int(shared_users_str)
            if shared_users < 0: # 0 might mean unlimited or 1 depending on ROS, but negative is invalid
                errors['shared-users'] = _('Shared users must be a non-negative number.')
        except ValueError:
            errors['shared-users'] = _('Shared users must be a valid number.')

    if errors:
        return jsonify({'success': False, 'message': _('Validation failed.'), 'errors': errors}), 400
    # --- End Input Validation ---

    # Prepare payload for service, ensuring only valid fields are passed
    payload_for_service = {'name': profile_name}
    if rate_limit:
        payload_for_service['rate-limit'] = rate_limit
    if session_timeout:
        payload_for_service['session-timeout'] = session_timeout
    if shared_users_str: # Use the validated integer if it was valid
        payload_for_service['shared-users'] = str(shared_users) # Mikrotik API often expects strings for numbers too

    success, message = router_os_service.create_hotspot_profile(payload_for_service)
    return jsonify({'success': success, 'message': message})

@app.route('/api/profiles/<profile_id>', methods=['PUT'])
@login_required
def edit_profile_route(profile_id: str):
    data = request.json
    errors = {}

    if not data: # No actual data sent
        return jsonify({'success': False, 'message': _('No data provided for update.')}), 400

    # --- Input Validation for Edit Profile ---
    # All fields are optional, but if present, must be valid.
    profile_name = data.get('name')
    if profile_name is not None:
        if not profile_name: # Cannot set to empty
             errors['name'] = _('Profile name cannot be empty.')
        elif not (3 <= len(profile_name) <= 64):
            errors['name'] = _('Profile name must be between 3 and 64 characters.')
        # elif not re.match(r"^[a-zA-Z0-9_-]+$", profile_name):
        #     errors['name'] = _('Profile name can only contain letters, numbers, underscore, and hyphen.')

    rate_limit = data.get('rate-limit')
    if rate_limit is not None and rate_limit != "" and not re.match(r"^((\d+[kKMGT]?/\d+[kKMGT]?)|(\d+[kKMGT]?))?$", rate_limit):
        errors['rate-limit'] = _('Invalid rate limit format. Example: 512k/2M or 1M, or empty to clear.')

    session_timeout = data.get('session-timeout')
    if session_timeout is not None and session_timeout != "" and not re.match(r"^((\d+[wdhms])+|none)?$", session_timeout):
        errors['session-timeout'] = _('Invalid session timeout format. Example: 1d, 2h30m, "none", or empty to clear.')

    shared_users_str = data.get('shared-users')
    shared_users_for_service = None
    if shared_users_str is not None:
        if shared_users_str == "": # User wants to clear/unset
            shared_users_for_service = "" # Send empty string to attempt to clear
        else:
            try:
                shared_users_val = int(shared_users_str)
                if shared_users_val < 0:
                    errors['shared-users'] = _('Shared users must be a non-negative number or empty to clear.')
                else:
                    shared_users_for_service = str(shared_users_val)
            except ValueError:
                errors['shared-users'] = _('Shared users must be a valid number or empty to clear.')

    if errors:
        return jsonify({'success': False, 'message': _('Validation failed.'), 'errors': errors}), 400
    # --- End Input Validation ---

    payload_for_service = {}
    if profile_name is not None:
        payload_for_service['name'] = profile_name
    if rate_limit is not None: # Allow empty string to clear
        payload_for_service['rate-limit'] = rate_limit
    if session_timeout is not None: # Allow empty string to clear
        payload_for_service['session-timeout'] = session_timeout
    if shared_users_for_service is not None: # This means it was provided and validated or explicitly cleared
        payload_for_service['shared-users'] = shared_users_for_service

    if not payload_for_service:
         return jsonify({'success': True, 'message': _('No changes detected to update.')})

    success, message = router_os_service.edit_hotspot_profile(profile_id, payload_for_service)
    return jsonify({'success': success, 'message': message})

@app.route('/api/profiles/<profile_id>', methods=['DELETE'])
@login_required
def delete_profile_route(profile_id: str):
    success, message = router_os_service.delete_hotspot_profile(profile_id)
    return jsonify({'success': success, 'message': message})

# --- UNIFIED EXPORT ROUTE ---
@app.route('/api/export-users', methods=['GET'])
@login_required
def export_users_route():
    export_format = request.args.get('format', 'json').lower()
    profile_filter = request.args.get('profile_filter')

    users = router_os_service.get_hotspot_users()

    if profile_filter:
        users = [user for user in users if user.get('profile') == profile_filter]

    if not users:
        return _("No users found for the selected criteria."), 404 # Ensure this response is handled by client

    if export_format == 'json':
        return jsonify(users)

    elif export_format == 'csv':
        si = io.StringIO()
        cw = csv.writer(si)
        headers = [
            'Username', 'Password', 'Profile', 'Time Limit',
            'Total Data Limit', 'Comment', 'Disabled'
        ]
        cw.writerow(headers)
        for user in users:
            row = [
                user.get('name', ''), user.get('password', ''), user.get('profile', ''),
                user.get('limit-uptime', _('Unlimited')), # Assuming Unlimited is a translated term
                format_bytes_for_export(user.get('limit-bytes-total')),
                user.get('comment', ''), user.get('disabled', 'false')
            ]
            cw.writerow(row)
        output = si.getvalue()
        filename_profile_part = profile_filter if profile_filter and profile_filter != 'All Profiles' else 'all'
        return Response(output, mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=users_{filename_profile_part}.csv"})

    elif export_format == 'html_voucher' or export_format == 'pdf_voucher':
        vouchers_data = [
            {
                'username': u.get('name'),
                'password': u.get('password'),
                'limit-uptime': u.get('limit-uptime', 'Unlimited'),
                'profile': u.get('profile', '')
            } for u in users
        ]
        login_url = app_config['mikrotik'].get('hotspot_login_url', '')
        filename_profile_part = profile_filter if profile_filter and profile_filter != 'All Profiles' else 'all'

        if export_format == 'pdf_voucher':
            if not WEASYPRINT_AVAILABLE:
                return jsonify({"success": False, "message": _("PDF generation is disabled. Please install system dependencies for WeasyPrint and restart the application.")}), 501
            
            html_content = _generate_vouchers_page_html(vouchers_data, login_url, include_print_button=False)
            try:
                pdf_file = WeasyHTML(string=html_content).write_pdf()
                return Response(
                    pdf_file, 
                    mimetype="application/pdf", 
                    headers={"Content-disposition": f"attachment; filename=vouchers_{filename_profile_part}.pdf"}
                )
            except Exception as e:
                 logger.error(f"Failed to generate PDF from export route: {e}")
                 return jsonify({"success": False, "message": _("An unexpected error occurred during PDF generation: {error}").format(error=str(e))}), 500
        else: # html_voucher
            html_content = _generate_vouchers_page_html(vouchers_data, login_url, include_print_button=True)
            return Response(html_content, mimetype="text/html")
    else:
        return jsonify({"success": False, "message": _("Invalid export format.")}), 400

@app.route('/api/analytics/basic_summary', methods=['GET'])
@login_required
def get_basic_analytics_summary_route():
    try:
        logger.info("API: Fetching basic bandwidth analytics.")
        analytics_data = router_os_service.get_basic_bandwidth_analytics()
        return jsonify(analytics_data)
    except Exception as e:
        logger.error(f"API: Error fetching basic analytics: {str(e)}")
        return jsonify({'success': False, 'message': _('A server error occurred while fetching analytics: {error}').format(error=str(e))}), 500

@app.route('/api/translations')
# This route is called by login.html, so it should be accessible without app login.
# Mikrotik connection is not needed for translations.
def get_translations():
    # Define all keys that the JavaScript side will need.
    # Using explicit keys allows for easier management and extraction for .po files.
    translations = {
        # Common alerts & messages
        'Loading...': _('Loading...'),
        'Successfully connected! Redirecting...': _('Successfully connected! Redirecting...'),
        'Connection failed. Please check details and try again.': _('Connection failed. Please check details and try again.'),
        'Network error or server is unreachable.': _('Network error or server is unreachable.'),
        'Operation successful': _('Operation successful'),
        'Operation failed': _('Operation failed'),
        'Are you sure?': _('Are you sure?'),
        'Saved': _('Saved'),
        'Deleted': _('Deleted'),
        'Updated': _('Updated'),
        'Created': _('Created'),
        'Connected': _('Connected'),
        'Disconnected': _('Disconnected'),
        'Connection test failed. Router might be unreachable.': _('Connection test failed. Router might be unreachable.'),
        'Configuration saved! Testing new connection...': _('Configuration saved! Testing new connection...'),
        'User created successfully!': _('User created successfully!'),
        'User updated successfully!': _('User updated successfully!'),
        'Profile updated successfully!': _('Profile updated successfully!'),
        'Profile created successfully!': _('Profile created successfully!'),
        'No users match the criteria.': _('No users match the criteria.'),
        'No active sessions found.': _('No active sessions found.'),
        'Could not load users.': _('Could not load users.'),
        'Could not load sessions.': _('Could not load sessions.'),
        'No profiles found.': _('No profiles found.'),
        'Loading users...': _('Loading users...'),
        'Loading sessions...': _('Loading sessions...'),
        'Loading profiles...': _('Loading profiles...'),
        'Loading analytics data...': _('Loading analytics data...'),
        'Total Data Transferred: Loading...': _('Total Data Transferred: Loading...'),
        'Could not load top user data.': _('Could not load top user data.'),
        'Could not load profile usage data.': _('Could not load profile usage data.'),
        'No user data usage available.': _('No user data usage available.'),
        'No profile usage data available.': _('No profile usage data available.'),
        'Total Data Transferred: Error loading data': _('Total Data Transferred: Error loading data'),
        'Connect': _('Connect'),
        'Connecting...': _('Connecting...'),
        'Refresh': _('Refresh'),
        'Test': _('Test'),
        'Testing...': _('Testing...'),
        'Save': _('Save'),
        'Saving...': _('Saving...'),
        'Delete': _('Delete'),
        'Deleting...': _('Deleting...'),
        'Disconnect': _('Disconnect'),
        'Disconnecting...': _('Disconnecting...'),
        'Add Profile': _('Add Profile'),
        'Edit Profile': _('Edit Profile'),
        'confirmLogout': _('Are you sure you want to logout?'),
        'confirmDeleteUser': _('Are you sure you want to delete user "{0}"?'),
        'confirmDisconnectUser': _('Are you sure you want to disconnect user "{0}"?'),
        'confirmDeleteProfile': _('Are you sure you want to delete profile "{0}"? This cannot be undone.'),
        'confirmDeleteExpiredUsers': _('Are you sure you want to find and delete ALL expired users? This action is permanent.'),
        'No generated voucher data available to view.': _('No generated voucher data available to view.'),
        'Hotspot Login URL is not set in Settings (under the Settings Tab). QR Codes cannot be generated for viewing if this is missing.': _('Hotspot Login URL is not set in Settings (under the Settings Tab). QR Codes cannot be generated for viewing if this is missing.'),
        'No generated voucher data available for PDF export.': _('No generated voucher data available for PDF export.'),
        'Hotspot Login URL is not set in Settings. QR Codes might be omitted in the PDF if this URL is required by the backend for them.': _('Hotspot Login URL is not set in Settings. QR Codes might be omitted in the PDF if this URL is required by the backend for them.'),
        'Unlimited': _('Unlimited'),
        'All Profiles': _('All Profiles'),
        'Select Profile': _('Select Profile'),
        'Disabled': _('Disabled'),
        'Active': _('Active'),
        'Logout failed unexpectedly. Please try again.': _('Logout failed unexpectedly. Please try again.'),
        'Expected JSON response from server for {0}, but received {1}.': _('Expected JSON response from server for {0}, but received {1}.'),
        'Total Data Transferred: {0}': _('Total Data Transferred: {0}'),
        'Edit User: {0}': _('Edit User: {0}'),
        'Edit Profile: {0}': _('Edit Profile: {0}'),
        'Add New Profile': _('Add New Profile'),
        'Profile {0} created successfully!': _('Profile {0} created successfully!'),
        'Profile {0} updated successfully!': _('Profile {0} updated successfully!'),
        'User "{0}" deleted.': _('User "{0}" deleted.'),
        'User disconnected.': _('User disconnected.'),
        'Profile "{0}" deleted.': _('Profile "{0}" deleted.'),
        'HTTP error! status: {0}': _('HTTP error! status: {0}'),
        'Connection failed (Error {0}). Please check details and try again.': _('Connection failed (Error {0}). Please check details and try again.'),

        # New keys for delete features
        'Delete Users by Profile': _('Delete Users by Profile'), # Title and button text
        'Select Profile to Delete Users From:': _('Select Profile to Delete Users From:'),
        'Delete Users by Active Status': _('Delete Users by Active Status'), # Title and button text
        'Select User Status to Delete:': _('Select User Status to Delete:'),
        'Active Users': _('Active Users'), # Option in select
        'Disabled Users': _('Disabled Users'), # Option in select
        '-- Select Profile --': _('-- Select Profile --'), # Default option for profile select
        '-- Select Status --': _('-- Select Status --'), # Default option for status select
        
        # JavaScript alert/confirm messages
        'Please select a profile to delete users from.': _('Please select a profile to delete users from.'),
        'Are you sure you want to delete ALL users from profile "{0}"? This action cannot be undone and is permanent.': _('Are you sure you want to delete ALL users from profile "{0}"? This action cannot be undone and is permanent.'),
        'Please select a user status to delete.': _('Please select a user status to delete.'),
        'Are you sure you want to delete all {0} users? This action cannot be undone and is permanent.': _('Are you sure you want to delete all {0} users? This action cannot be undone and is permanent.'),
        
        # Messages from backend that might be displayed via showAlert if not already translated by Flask
        # These are examples; actual messages from backend routes are already wrapped in _()
        # 'Successfully deleted {0} user(s) from profile "{1}".': _('Successfully deleted {0} user(s) from profile "{1}".'),
        # 'Successfully deleted {0} {1} user(s).': _('Successfully deleted {0} {1} user(s).'),
        # 'Failed to delete users from profile "{0}".': _('Failed to delete users from profile "{0}".'),
        # 'Failed to delete {0} user(s).': _('Failed to delete {0} user(s).'),
        'Operation failed, no users deleted.': _('Operation failed, no users deleted.'),
        'Successfully processed users for profile {0}. Deleted {1} user(s).': _('Successfully processed users for profile {0}. Deleted {1} user(s).'),
        'Failed to delete users from profile {0}.': _('Failed to delete users from profile {0}.'),
        'Successfully processed {0} users. Deleted {1} user(s).': _('Successfully processed {0} users. Deleted {1} user(s).'),
        'Failed to delete {0} users.': _('Failed to delete {0} users.')

    }
    return jsonify(translations)

if __name__ == '__main__':
    server_config = app_config['server']
    print("="*40)
    print(_("  Mikrotik Hotspot Management System v2"))
    print("="*40)
    print(f"\n✅ {_('Dashboard available at:')} http://{server_config['host']}:{server_config['port']}")
    app.run(host=server_config['host'], port=server_config['port'], debug=server_config['debug'])