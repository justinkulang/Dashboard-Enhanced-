from flask import Blueprint

# url_prefix for API blueprints is a common practice
users_api_bp = Blueprint('users_api', __name__, url_prefix='/api/users')

from . import routes
