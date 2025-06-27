import pytest
import os
import json
import tempfile
from app import ConfigLoader  # Assuming ConfigLoader is in app.py

# Helper to create a temporary config file
@pytest.fixture
def temp_config_file_path():
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)  # Close the file descriptor, we'll write to it later
    yield path
    os.unlink(path) # Cleanup

def test_load_config_defaults_when_file_missing(temp_config_file_path, monkeypatch):
    """Test that default values are loaded if config file is missing and no ENV vars are set."""
    # Ensure no relevant env vars are set
    env_vars_to_clear = [
        'MIKROTIK_HOST', 'MIKROTIK_PORT', 'MIKROTIK_USERNAME', 'MIKROTIK_PASSWORD',
        'MIKROTIK_USE_SSL', 'MIKROTIK_HOTSPOT_LOGIN_URL',
        'APP_ADMIN_USERNAME', 'APP_ADMIN_PASSWORD_HASH',
        'SERVER_HOST', 'SERVER_PORT', 'FLASK_DEBUG', 'APP_ENV'
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)

    # Use a non-existent path for the ConfigLoader initially
    non_existent_path = temp_config_file_path + ".nonexistent"
    if os.path.exists(non_existent_path): # Should not exist, but ensure
        os.unlink(non_existent_path)

    # When ConfigLoader is initialized with a non-existent file, it should create one with defaults.
    # Then, when it loads, it should reflect these defaults (or internal hardcoded defaults if creation failed).
    # The current ConfigLoader creates the file with defaults if it doesn't exist.
    loader = ConfigLoader(config_file=non_existent_path)
    config = loader.get_config()

    assert config['mikrotik']['host'] == "192.168.88.1"
    assert config['mikrotik']['port'] == 8728
    assert config['app_admin']['username'] == "admin"
    assert config['server']['debug'] is False # Default debug is False

    # Clean up the created default file
    if os.path.exists(non_existent_path):
        os.unlink(non_existent_path)


def test_load_config_from_file(temp_config_file_path, monkeypatch):
    """Test loading configuration purely from a JSON file, no ENV var overrides."""
    env_vars_to_clear = [
        'MIKROTIK_HOST', 'MIKROTIK_PORT', 'MIKROTIK_USERNAME', 'MIKROTIK_PASSWORD',
        'MIKROTIK_USE_SSL', 'MIKROTIK_HOTSPOT_LOGIN_URL',
        'APP_ADMIN_USERNAME', 'APP_ADMIN_PASSWORD_HASH',
        'SERVER_HOST', 'SERVER_PORT', 'FLASK_DEBUG', 'APP_ENV'
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)

    custom_config_data = {
        "mikrotik": {"host": "10.0.0.1", "port": 8720, "password": "filepassword"},
        "app_admin": {"username": "fileadmin", "password_hash": "filehash"},
        "server": {"debug": True}
    }
    with open(temp_config_file_path, 'w') as f:
        json.dump(custom_config_data, f)

    loader = ConfigLoader(config_file=temp_config_file_path)
    config = loader.get_config()

    assert config['mikrotik']['host'] == "10.0.0.1"
    assert config['mikrotik']['port'] == 8720
    assert config['mikrotik']['password'] == "filepassword" # Loaded from file
    assert config['app_admin']['username'] == "fileadmin"
    assert config['app_admin']['password_hash'] == "filehash" # Loaded from file
    assert config['server']['debug'] is True

def test_env_vars_override_file_config(temp_config_file_path, monkeypatch):
    """Test that environment variables override values from config.json."""
    file_config_data = {
        "mikrotik": {"host": "file.host", "port": 1111, "password": "file_password"},
        "app_admin": {"username": "file_admin", "password_hash": "file_hash"},
        "server": {"debug": True}
    }
    with open(temp_config_file_path, 'w') as f:
        json.dump(file_config_data, f)

    monkeypatch.setenv("MIKROTIK_HOST", "env.host")
    monkeypatch.setenv("MIKROTIK_PORT", "2222")
    monkeypatch.setenv("MIKROTIK_PASSWORD", "env_password")
    monkeypatch.setenv("APP_ADMIN_USERNAME", "env_admin")
    monkeypatch.setenv("APP_ADMIN_PASSWORD_HASH", "env_hash")
    monkeypatch.setenv("FLASK_DEBUG", "false") # Server debug

    loader = ConfigLoader(config_file=temp_config_file_path)
    config = loader.get_config()

    assert config['mikrotik']['host'] == "env.host"
    assert config['mikrotik']['port'] == 2222
    assert config['mikrotik']['password'] == "env_password"
    assert config['app_admin']['username'] == "env_admin"
    assert config['app_admin']['password_hash'] == "env_hash"
    assert config['server']['debug'] is False # Overridden by FLASK_DEBUG

def test_env_vars_partial_override(temp_config_file_path, monkeypatch):
    """Test partial override: some from ENV, some from file."""
    file_config_data = {
        "mikrotik": {
            "host": "file.host",
            "port": 1111,
            "username": "file_user_mk", # This should persist
            "password": "file_password"
        },
        "app_admin": {
            "username": "file_admin_user", # This should persist
            "password_hash": "file_hash"
        },
         "server": {"debug": True, "log_file": "file_log.log"} # log_file should persist
    }
    with open(temp_config_file_path, 'w') as f:
        json.dump(file_config_data, f)

    monkeypatch.setenv("MIKROTIK_HOST", "env.host.partial") # Override host
    monkeypatch.setenv("APP_ADMIN_PASSWORD_HASH", "env_hash_partial") # Override hash
    # MIKROTIK_PORT, MIKROTIK_USERNAME, MIKROTIK_PASSWORD, APP_ADMIN_USERNAME, FLASK_DEBUG not set via ENV

    loader = ConfigLoader(config_file=temp_config_file_path)
    config = loader.get_config()

    assert config['mikrotik']['host'] == "env.host.partial" # From ENV
    assert config['mikrotik']['port'] == 1111 # From file
    assert config['mikrotik']['username'] == "file_user_mk" # From file
    assert config['mikrotik']['password'] == "file_password" # From file (as MIKROTIK_PASSWORD env not set)

    assert config['app_admin']['username'] == "file_admin_user" # From file
    assert config['app_admin']['password_hash'] == "env_hash_partial" # From ENV

    assert config['server']['debug'] is True # From file
    assert config['server']['log_file'] == "file_log.log" # From file


def test_mikrotik_use_ssl_env_override(temp_config_file_path, monkeypatch):
    """Test MIKROTIK_USE_SSL environment variable override."""
    file_config_data = {"mikrotik": {"use_ssl": False}}
    with open(temp_config_file_path, 'w') as f:
        json.dump(file_config_data, f)

    monkeypatch.setenv("MIKROTIK_USE_SSL", "true")
    loader = ConfigLoader(config_file=temp_config_file_path)
    config = loader.get_config()
    assert config['mikrotik']['use_ssl'] is True

    monkeypatch.setenv("MIKROTIK_USE_SSL", "0")
    loader = ConfigLoader(config_file=temp_config_file_path) # Re-load
    config = loader.get_config()
    assert config['mikrotik']['use_ssl'] is False


def test_update_admin_password_hash_in_file(temp_config_file_path, monkeypatch):
    """Test update_admin_password_hash when hash is managed by file."""
    monkeypatch.delenv("APP_ADMIN_PASSWORD_HASH", raising=False) # Ensure ENV is not set

    initial_hash = "initial_file_hash"
    file_config_data = {"app_admin": {"password_hash": initial_hash}}
    with open(temp_config_file_path, 'w') as f:
        json.dump(file_config_data, f)

    loader = ConfigLoader(config_file=temp_config_file_path)
    assert loader.get_config()['app_admin']['password_hash'] == initial_hash

    new_hash = "new_updated_file_hash"
    success = loader.update_admin_password_hash(new_hash)
    assert success is True

    # Verify it's updated in the current instance's config
    assert loader.get_config()['app_admin']['password_hash'] == new_hash

    # Verify it's written to the file by loading fresh
    loader_fresh = ConfigLoader(config_file=temp_config_file_path)
    assert loader_fresh.get_config()['app_admin']['password_hash'] == new_hash


def test_update_admin_password_hash_blocked_by_env(temp_config_file_path, monkeypatch):
    """Test that update_admin_password_hash is blocked if APP_ADMIN_PASSWORD_HASH ENV is set."""
    env_hash = "this_is_from_env"
    monkeypatch.setenv("APP_ADMIN_PASSWORD_HASH", env_hash)

    file_config_data = {"app_admin": {"password_hash": "some_file_hash"}}
    with open(temp_config_file_path, 'w') as f:
        json.dump(file_config_data, f)

    loader = ConfigLoader(config_file=temp_config_file_path)
    # Config should reflect ENV var due to loading precedence
    assert loader.get_config()['app_admin']['password_hash'] == env_hash

    # Attempt to update should fail and not change the file or in-memory config from ENV
    success = loader.update_admin_password_hash("attempt_to_update_file_hash")
    assert success is False

    # In-memory config should still be the ENV hash
    assert loader.get_config()['app_admin']['password_hash'] == env_hash

    # File should remain unchanged because update was blocked
    loader_fresh = ConfigLoader(config_file=temp_config_file_path) # This will again pick up env_hash
    assert loader_fresh.get_config()['app_admin']['password_hash'] == env_hash
    # To check the file content itself:
    with open(temp_config_file_path, 'r') as f:
        file_content_after_attempt = json.load(f)
    assert file_content_after_attempt['app_admin']['password_hash'] == "some_file_hash"

# TODO: Add tests for logging warnings when sensitive data is loaded from config.json in non-debug mode.
# This would require capturing log output (e.g., using caplog fixture from pytest).
# Example:
# def test_logs_warning_for_mikrotik_password_from_file_in_prod_mode(caplog, temp_config_file_path, monkeypatch):
#     monkeypatch.delenv("MIKROTIK_PASSWORD", raising=False)
#     monkeypatch.setenv("FLASK_DEBUG", "false") # Simulate production
#
#     file_config_data = {
#         "mikrotik": {"password": "verysecret"},
#         "server": {"debug": False} # Ensure config also says not debug
#     }
#     with open(temp_config_file_path, 'w') as f:
#         json.dump(file_config_data, f)
#
#     with caplog.at_level(logging.WARNING):
#         loader = ConfigLoader(config_file=temp_config_file_path)
#         loader.get_config() # Trigger loading
#
#     assert "SECURITY WARNING: Using Mikrotik password from config.json" in caplog.text
#     assert "MIKROTIK_PASSWORD environment variable" in caplog.text

# def test_logs_warning_for_admin_hash_from_file_in_prod_mode(caplog, temp_config_file_path, monkeypatch):
#     monkeypatch.delenv("APP_ADMIN_PASSWORD_HASH", raising=False)
#     monkeypatch.setenv("FLASK_DEBUG", "false")
#
#     file_config_data = {
#         "app_admin": {"password_hash": "a_real_hash_not_default"},
#         "server": {"debug": False}
#     }
#     with open(temp_config_file_path, 'w') as f:
#         json.dump(file_config_data, f)
#
#     with caplog.at_level(logging.WARNING):
#         loader = ConfigLoader(config_file=temp_config_file_path)
#         loader.get_config()
#
#     assert "SECURITY WARNING: Using App Admin password hash from config.json" in caplog.text
#     assert "APP_ADMIN_PASSWORD_HASH environment variable" in caplog.text

# def test_no_warning_for_default_admin_hash_from_file(caplog, temp_config_file_path, monkeypatch):
#     monkeypatch.delenv("APP_ADMIN_PASSWORD_HASH", raising=False)
#     monkeypatch.setenv("FLASK_DEBUG", "false")
#
#     # Using the default hash for "changeme"
#     default_changeme_hash = "pbkdf2:sha256:600000$zR0gQY0gV0gY0gV0$c2df639e9e31b0cf9352d789a8f074d2f6a603cf8bd77a9a20addf32089e11f9"
#     file_config_data = {
#         "app_admin": {"password_hash": default_changeme_hash },
#         "server": {"debug": False}
#     }
#     with open(temp_config_file_path, 'w') as f:
#         json.dump(file_config_data, f)
#
#     with caplog.at_level(logging.WARNING):
#         loader = ConfigLoader(config_file=temp_config_file_path)
#         loader.get_config()
#
#     assert "SECURITY WARNING: Using App Admin password hash from config.json" not in caplog.text
