from flask import Blueprint

profiles_api_bp = Blueprint('profiles_api', __name__, url_prefix='/api/profiles')

from . import routes
