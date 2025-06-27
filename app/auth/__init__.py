from flask import Blueprint

auth_bp = Blueprint('auth', __name__, template_folder='../templates', static_folder='../static')
# The template_folder and static_folder might need adjustment depending on how Flask handles it
# with blueprints in a sub-package. Often, templates are discovered automatically if in app/templates.
# For static, it might be app.static_folder.
# Let's assume for now Flask's default discovery might work or we adjust later.

from . import routes # Import routes after blueprint creation to avoid circular imports
