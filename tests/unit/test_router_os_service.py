import pytest
from unittest.mock import patch, MagicMock
from app import RouterOSService, app # Import app for app_context
from librouteros.exceptions import TrapError, LibRouterosError # For simulating errors

# Instantiate the service once, as its __init__ is simple
# If __init__ had side effects or dependencies, we'd make this a fixture.
service = RouterOSService()

@pytest.fixture
def mock_get_api(mocker):
    """Fixture to mock get_mikrotik_api and its return value (the API client)."""
    mock_api_client = MagicMock()
    # Make the path method itself a MagicMock so we can chain calls like .path().select().where()
    mock_api_client.path.return_value = MagicMock()

    # Patch 'app.get_mikrotik_api' so it returns our mock_api_client
    return mocker.patch('app.get_mikrotik_api', return_value=mock_api_client), mock_api_client

@pytest.fixture
def mock_get_api_none(mocker):
    """Fixture to mock get_mikrotik_api to return None (simulating connection failure)."""
    return mocker.patch('app.get_mikrotik_api', return_value=None)

# --- Tests for get_hotspot_users ---
def test_get_hotspot_users_success(mock_get_api, app_context):
    """Test get_hotspot_users successfully returns a list of users."""
    _, mock_api_client = mock_get_api

    # Configure the chained mock calls for the specific path
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance # .path()

    expected_users = [
        {'.id': '*1', 'name': 'user1', 'profile': 'default'},
        {'.id': '*2', 'name': 'user2', 'profile': 'guest'}
    ]
    mock_path_instance.select.return_value = expected_users # .select()

    with app_context: # Need app context for 'g' if get_mikrotik_api uses it
        users = service.get_hotspot_users()

    assert users == expected_users
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'user')
    mock_path_instance.select.assert_called_once_with(
        '.id', 'name', 'password', 'profile', 'disabled', 'limit-uptime', 'limit-bytes-total',
        'uptime', 'bytes-in', 'bytes-out', 'comment', 'limit-bytes-in', 'limit-bytes-out'
    )

def test_get_hotspot_users_api_returns_none(mock_get_api_none, app_context):
    """Test get_hotspot_users when get_mikrotik_api returns None."""
    with app_context:
        users = service.get_hotspot_users()
    assert users == []

def test_get_hotspot_users_api_call_exception(mock_get_api, app_context):
    """Test get_hotspot_users when the API call itself raises an exception."""
    _, mock_api_client = mock_get_api
    mock_api_client.path.side_effect = LibRouterosError("API communication error")

    with app_context:
        users = service.get_hotspot_users()
    assert users == []


# --- Tests for create_hotspot_user ---
def test_create_hotspot_user_success(mock_get_api, app_context):
    """Test successful user creation."""
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance

    user_data = {'name': 'newuser', 'password': 'password123', 'profile': 'default'}

    with app_context:
        success, message = service.create_hotspot_user(user_data)

    assert success is True
    assert message == "User created successfully" # Assuming this is the exact message
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'user')
    mock_path_instance.add.assert_called_once_with(**user_data)

def test_create_hotspot_user_api_returns_none(mock_get_api_none, app_context):
    """Test create_hotspot_user when get_mikrotik_api returns None."""
    user_data = {'name': 'newuser', 'password': 'password123'}
    with app_context:
        success, message = service.create_hotspot_user(user_data)
    assert success is False
    assert message == "Mikrotik connection not available"

def test_create_hotspot_user_trap_error(mock_get_api, app_context):
    """Test create_hotspot_user when Mikrotik returns a TrapError."""
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance

    trap_message = "failure: user already exists"
    mock_path_instance.add.side_effect = TrapError(trap_message)

    user_data = {'name': 'existinguser', 'password': 'password123'}
    with app_context:
        success, message = service.create_hotspot_user(user_data)

    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"


# --- Tests for edit_hotspot_user ---
@pytest.fixture
def mock_edit_user_api_calls(mock_get_api):
    """Specific mock setup for edit_hotspot_user's API interactions."""
    _, mock_api_client = mock_get_api

    mock_path_select_instance = MagicMock() # For the .select().where() part
    mock_path_set_instance = MagicMock()    # For the .set() part

    # Configure path to return the select instance first, then the set instance
    # This requires careful chaining or separate path mocks if the path string changes.
    # Assuming path('ip', 'hotspot', 'user') is called for both select and set.
    mock_ip_hotspot_user_path = MagicMock()
    mock_api_client.path.return_value = mock_ip_hotspot_user_path

    # When .select().where() is called
    mock_ip_hotspot_user_path.select.return_value.where.return_value = [{'.id': '*5'}]

    return mock_api_client, mock_ip_hotspot_user_path


def test_edit_hotspot_user_success(mock_edit_user_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_edit_user_api_calls
    user_to_edit = "testuser"
    new_data = {'profile': 'new_profile', 'comment': 'Updated comment'}

    with app_context:
        success, message = service.edit_hotspot_user(user_to_edit, new_data)

    assert success is True
    assert message == "User updated successfully"

    # Check select call
    mock_path_instance.select.assert_called_once_with('.id')
    mock_path_instance.select.return_value.where.assert_called_once_with(name=user_to_edit)

    # Check set call
    expected_set_data = {'.id': '*5', **new_data}
    mock_path_instance.set.assert_called_once_with(**expected_set_data)


def test_edit_hotspot_user_not_found(mock_edit_user_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_edit_user_api_calls
    # Simulate user not found by having the .where() call return an empty list
    mock_path_instance.select.return_value.where.return_value = []

    user_to_edit = "nonexistentuser"
    new_data = {'comment': 'Attempt to update'}

    with app_context:
        success, message = service.edit_hotspot_user(user_to_edit, new_data)

    assert success is False
    assert message == "User not found"
    mock_path_instance.set.assert_not_called() # Ensure .set() was not called

def test_edit_hotspot_user_api_returns_none(mock_get_api_none, app_context):
    with app_context:
        success, message = service.edit_hotspot_user("anyuser", {'comment': 'test'})
    assert success is False
    assert message == "Mikrotik connection not available"

def test_edit_hotspot_user_trap_error(mock_edit_user_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_edit_user_api_calls
    trap_message = "failure: cannot change profile"
    mock_path_instance.set.side_effect = TrapError(trap_message)

    user_to_edit = "testuser"
    new_data = {'profile': 'invalid_profile_for_trap'}

    with app_context:
        success, message = service.edit_hotspot_user(user_to_edit, new_data)

    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"


# --- Tests for delete_hotspot_user ---
# Similar fixture structure to edit_user for mocking select and remove
@pytest.fixture
def mock_delete_user_api_calls(mock_get_api):
    _, mock_api_client = mock_get_api
    mock_ip_hotspot_user_path = MagicMock()
    mock_api_client.path.return_value = mock_ip_hotspot_user_path
    mock_ip_hotspot_user_path.select.return_value.where.return_value = [{'.id': '*10'}]
    return mock_api_client, mock_ip_hotspot_user_path

def test_delete_hotspot_user_success(mock_delete_user_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_delete_user_api_calls
    user_to_delete = "usertodelete"

    with app_context:
        success, message = service.delete_hotspot_user(user_to_delete)

    assert success is True
    assert message == "User deleted successfully"
    mock_path_instance.select.assert_called_once_with('.id')
    mock_path_instance.select.return_value.where.assert_called_once_with(name=user_to_delete)
    mock_path_instance.remove.assert_called_once_with('*10')


def test_delete_hotspot_user_not_found(mock_delete_user_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_delete_user_api_calls
    mock_path_instance.select.return_value.where.return_value = [] # Simulate user not found

    with app_context:
        success, message = service.delete_hotspot_user("ghostuser")

    assert success is False
    assert message == "User not found"
    mock_path_instance.remove.assert_not_called()

def test_delete_hotspot_user_api_returns_none(mock_get_api_none, app_context):
    with app_context:
        success, message = service.delete_hotspot_user("anyuser")
    assert success is False
    assert message == "Mikrotik connection not available"

def test_delete_hotspot_user_trap_error(mock_delete_user_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_delete_user_api_calls
    trap_message = "failure: user has active session"
    mock_path_instance.remove.side_effect = TrapError(trap_message)

    with app_context:
        success, message = service.delete_hotspot_user("activeuser")

    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"

# Fixture for app_context if not already available globally from conftest.py
# This is needed if tests use 'g' or other app-specific context.
# The main conftest.py 'app' fixture should already provide this when used.
@pytest.fixture
def app_context(app):
    with app.app_context():
        yield

# --- Tests for get_active_sessions ---
def test_get_active_sessions_success(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance
    expected_sessions = [{'user': 'u1', 'address': '1.1.1.1'}, {'user': 'u2', 'address': '2.2.2.2'}]
    mock_path_instance.select.return_value = expected_sessions

    with app_context:
        sessions = service.get_active_sessions()
    assert sessions == expected_sessions
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'active')
    mock_path_instance.select.assert_called_once_with(
        'user', 'address', 'mac-address', 'uptime', 'bytes-in', 'bytes-out',
        'session-time-left', 'idle-time', '.id'
    )

def test_get_active_sessions_api_none(mock_get_api_none, app_context):
    with app_context:
        sessions = service.get_active_sessions()
    assert sessions == []

def test_get_active_sessions_exception(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_api_client.path.side_effect = LibRouterosError("Session fetch error")
    with app_context:
        sessions = service.get_active_sessions()
    assert sessions == []

# --- Tests for disconnect_user ---
def test_disconnect_user_success(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance
    active_id_to_disconnect = "*A1"

    with app_context:
        success, message = service.disconnect_user(active_id_to_disconnect)
    assert success is True
    assert message == "User disconnected successfully"
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'active')
    mock_path_instance.remove.assert_called_once_with(active_id_to_disconnect)

def test_disconnect_user_api_none(mock_get_api_none, app_context):
    with app_context:
        success, message = service.disconnect_user("*A1")
    assert success is False
    assert message == "Mikrotik connection not available"

def test_disconnect_user_trap_error(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance
    trap_message = "failure: no such item"
    mock_path_instance.remove.side_effect = TrapError(trap_message)

    with app_context:
        success, message = service.disconnect_user("*A1")
    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"


# --- Tests for get_user_profiles ---
def test_get_user_profiles_success(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance
    expected_profiles = [{'.id': '*P1', 'name': 'prof1'}, {'.id': '*P2', 'name': 'prof2'}]
    mock_path_instance.select.return_value = expected_profiles

    with app_context:
        profiles = service.get_user_profiles()
    assert profiles == expected_profiles
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'user', 'profile')
    mock_path_instance.select.assert_called_once_with(
        '.id', 'name', 'rate-limit', 'session-timeout', 'shared-users',
        'mac-cookie-timeout', 'keepalive-timeout'
    )

def test_get_user_profiles_api_none(mock_get_api_none, app_context):
    with app_context:
        profiles = service.get_user_profiles()
    assert profiles == []

# --- Tests for create_hotspot_profile ---
def test_create_hotspot_profile_success(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance
    profile_data = {'name': 'newprof', 'rate-limit': '1M/1M'}

    with app_context:
        success, message = service.create_hotspot_profile(profile_data)
    assert success is True
    assert message == f"Profile '{profile_data['name']}' created successfully."
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'user', 'profile')
    # The service filters out None/empty values, so if profile_data had them, they wouldn't be passed
    mock_path_instance.add.assert_called_once_with(**{k: v for k,v in profile_data.items() if v})


def test_create_hotspot_profile_api_none(mock_get_api_none, app_context):
    with app_context:
        success, message = service.create_hotspot_profile({'name': 'newprof'})
    assert success is False
    assert message == "Mikrotik connection not available"

def test_create_hotspot_profile_trap_error(mock_get_api, app_context):
    _, mock_api_client = mock_get_api
    mock_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_path_instance
    trap_message = "failure: profile already exists"
    mock_path_instance.add.side_effect = TrapError(trap_message)

    with app_context:
        success, message = service.create_hotspot_profile({'name': 'existingprof'})
    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"


# --- Tests for edit_hotspot_profile ---
@pytest.fixture
def mock_edit_profile_api_calls(mock_get_api):
    _, mock_api_client = mock_get_api
    mock_profile_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_profile_path_instance
    # For edit, we don't typically need a .select().where() first if we have the .id
    # The service method takes profile_id directly.
    return mock_api_client, mock_profile_path_instance

def test_edit_hotspot_profile_success(mock_edit_profile_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_edit_profile_api_calls
    profile_id_to_edit = "*P5"
    new_data = {'rate-limit': '2M/2M', 'session-timeout': '1d'}

    with app_context:
        success, message = service.edit_hotspot_profile(profile_id_to_edit, new_data)
    assert success is True
    assert message == "Profile updated successfully."
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'user', 'profile')
    expected_set_data = {'.id': profile_id_to_edit, **new_data}
    mock_path_instance.set.assert_called_once_with(**expected_set_data)

def test_edit_hotspot_profile_api_none(mock_get_api_none, app_context):
    with app_context:
        success, message = service.edit_hotspot_profile("*P5", {'rate-limit': '1M'})
    assert success is False
    assert message == "Mikrotik connection not available"

def test_edit_hotspot_profile_trap_error(mock_edit_profile_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_edit_profile_api_calls
    trap_message = "failure: no such item to set"
    mock_path_instance.set.side_effect = TrapError(trap_message)

    with app_context:
        success, message = service.edit_hotspot_profile("*PNonExistent", {'rate-limit': '1M'})
    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"


# --- Tests for delete_hotspot_profile ---
@pytest.fixture
def mock_delete_profile_api_calls(mock_get_api):
    _, mock_api_client = mock_get_api
    mock_profile_path_instance = MagicMock()
    mock_api_client.path.return_value = mock_profile_path_instance
    return mock_api_client, mock_profile_path_instance

def test_delete_hotspot_profile_success(mock_delete_profile_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_delete_profile_api_calls
    profile_id_to_delete = "*P10"

    with app_context:
        success, message = service.delete_hotspot_profile(profile_id_to_delete)
    assert success is True
    assert message == "Profile deleted successfully."
    mock_api_client.path.assert_called_once_with('ip', 'hotspot', 'user', 'profile')
    mock_path_instance.remove.assert_called_once_with(profile_id_to_delete)

def test_delete_hotspot_profile_api_none(mock_get_api_none, app_context):
    with app_context:
        success, message = service.delete_hotspot_profile("*P10")
    assert success is False
    assert message == "Mikrotik connection not available"

def test_delete_hotspot_profile_trap_error(mock_delete_profile_api_calls, app_context):
    mock_api_client, mock_path_instance = mock_delete_profile_api_calls
    trap_message = "failure: profile in use"
    mock_path_instance.remove.side_effect = TrapError(trap_message)

    with app_context:
        success, message = service.delete_hotspot_profile("*PInUse")
    assert success is False
    assert message == f"Mikrotik Error: {trap_message}"
