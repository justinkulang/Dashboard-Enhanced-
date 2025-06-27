import pytest
import os
import tempfile
import json

# Import the create_app function or your Flask app instance
# If your app.py has a create_app() factory:
# from app import create_app
# If app.py directly creates an 'app' instance:
from app import app as main_app_instance
from app import ConfigLoader # For test config manipulation

@pytest.fixture(scope='session')
def app():
    """
    Session-wide test `app` fixture.
    Creates a new Flask app instance for each test session.
    """

    # Create a temporary config file for testing
    # This ensures tests don't interfere with the actual config.json
    # and allows us to set predictable values for tests.
    temp_config_fd, temp_config_path = tempfile.mkstemp(suffix='.json')

    test_config_data = {
        "mikrotik": {
            "host": "127.0.0.1", # Test-specific
            "port": 8728,
            "username": "testadmin",
            "password": "testpassword",
            "use_ssl": False,
            "hotspot_login_url": "http://testhotspot.local/login"
        },
        "server": {
            "host": "127.0.0.1",
            "port": 5001, # Different from default to avoid conflict
            "debug": False, # Keep False for testing, TESTING flag handles behavior
            "log_file": "test_dashboard.log",
            "log_level_console": "ERROR", # Reduce noise during tests
            "log_level_file": "ERROR"
        },
        "app_admin": {
            "username": "testadmin",
            # Hash for "testpassword" using pbkdf2:sha256:600000 (same as default "changeme" in app)
            # from werkzeug.security import generate_password_hash
            # generate_password_hash("testpassword", method="pbkdf2:sha256:600000")
            "password_hash": "pbkdf2:sha256:600000$W0gSLfT3s0qGfNfE$9f845429a73d780dd696890507cf1d28d2824062c5a8938a8825238659eb7040"
        }
    }
    with os.fdopen(temp_config_fd, 'w') as tmp:
        json.dump(test_config_data, tmp, indent=4)

    # Point ConfigLoader to use this temporary config for the test app session
    # We need to ensure the app instance used for testing loads this config.
    # This is tricky if 'main_app_instance' is imported directly as it loads config on import.
    # A create_app factory pattern is generally better for testing.
    # For now, we'll try to re-initialize its config loader if possible, or override config directly.

    # Option 1: If you can re-initialize or make ConfigLoader use a different path
    # This requires ConfigLoader to be flexible or the app to be created via a factory.
    # For simplicity here, we will directly modify the config of the imported main_app_instance.
    # This is not ideal for true isolation if tests run in parallel or modify global state,
    # but for sequential tests, it can work.

    main_app_instance.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,  # Disable CSRF forms for testing API endpoints
        "LOGIN_DISABLED": False,    # Ensure login is not globally disabled unless a test needs it
        # Override specific config values that ConfigLoader would set
        # This makes tests independent of environment variables being set on the test runner
        "SECRET_KEY": "test_secret_key" # Use a fixed secret key for tests
    })

    # Override the app_config that parts of the app might use directly
    # This simulates ConfigLoader loading our test_config_data
    # Note: This assumes `app_config` in `app.py` is a global that can be repointed.
    # Ideally, `app.app_config` should be accessed via `current_app.config` or `app.config`
    # For now, we'll patch where it's used or ensure the app fixture provides this.

    # The ConfigLoader instance is created at module level in app.py.
    # We'll replace its loaded config with our test config.
    # This is a bit of a hack due to the current app structure.
    original_config_loader_instance = main_app_instance.extensions['config_loader'] # Assuming we store it

    # Create a new ConfigLoader instance pointing to our temp file for this app context
    # This is tricky because the global `config_loader` and `app_config` in app.py are set at import time.
    # The most robust way is using an app factory.
    # Short of that, we can try to directly set the config values the app uses.

    # Directly update the main_app_instance's config dictionary with values from test_config_data
    # This bypasses the ConfigLoader's ENV var loading for tests, making them more deterministic.
    main_app_instance.config['MIKROTIK_CONFIG'] = test_config_data['mikrotik']
    main_app_instance.config['SERVER_CONFIG'] = test_config_data['server']
    main_app_instance.config['APP_ADMIN_CONFIG'] = test_config_data['app_admin']

    # Make the global app_config in app.py use these test values.
    # This requires app.py to be structured to allow this or an app factory.
    # For now, we assume that routes and logic use current_app.config or app.config.
    # If app.app_config is used directly, tests might need to patch it.

    # A simple way to ensure app.app_config is updated is to re-assign it if it's accessible
    # For example, if app.py had:
    # app_config = None
    # def create_app_for_real():
    #    global app_config
    #    ...
    #    config_loader = ConfigLoader(...)
    #    app_config = config_loader.get_config()
    #    return app
    # Then in tests:
    # test_app = create_app_for_real(config_path=temp_config_path)

    # Given the current structure, we will rely on main_app_instance.config being updated
    # and hope that most code uses current_app.config or similar.
    # The ConfigLoader in app.py will have already run with the original config.json.
    # The most critical part is that routes using `app_config` directly get the test values.
    # Let's assume for now that `app_config` in `app.py` can be "reloaded" or is mostly
    # used to set `main_app_instance.config` initially.

    # To make tests truly isolated with the current app structure, we'd have to reload app.py
    # or use more complex patching.
    # A pragmatic approach for now:
    # The `ConfigLoader` in app.py is instantiated as `config_loader`.
    # Its `self.config` is what `app_config` gets. We can try to replace that.

    # Backup original config
    # original_app_py_app_config = main_app_instance.config_loader.config # if ConfigLoader was an attribute

    # Temporarily replace the config in the global config_loader instance used by app.py
    # This is very direct manipulation.
    from app import config_loader as global_config_loader_in_app_py
    original_loaded_config = global_config_loader_in_app_py.config
    global_config_loader_in_app_py.config = test_config_data

    # Also update the global app_config in app.py directly.
    import app as app_module
    original_app_module_app_config = app_module.app_config
    app_module.app_config = test_config_data


    # Application context for tests
    with main_app_instance.app_context():
        yield main_app_instance # Provide the app instance to tests

    # Teardown: clean up the temporary config file and restore original config
    os.close(temp_config_fd)
    os.unlink(temp_config_path)
    global_config_loader_in_app_py.config = original_loaded_config # Restore
    app_module.app_config = original_app_module_app_config # Restore


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test CLI runner for the app."""
    return app.test_cli_runner()

# Fixture to mock logged-in user if needed for specific tests
@pytest.fixture
def logged_in_client(client, app):
    # Log in the test admin user
    # Assumes 'testadmin' and 'testpassword' from the test_config_data
    with client: # Open a test client context
        client.post('/app-login', data={
            'app_username': app.config['APP_ADMIN_CONFIG']['username'],
            'app_password': 'testpassword' # The actual password, not the hash
        }, follow_redirects=True)
        # The session should now be set for subsequent requests with this client
        yield client
        # Logout after test (optional, as client is fresh per test using it)
        # client.post('/api/logout', follow_redirects=True)
