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


# --- Tests for delete_users_by_profile ---
@pytest.fixture
def mock_delete_by_profile_deps(mocker, mock_get_api):
    mock_api_client, _ = mock_get_api
    mock_get_users = mocker.patch.object(service, 'get_hotspot_users')
    mock_remove_path = MagicMock() # For the .remove() call
    mock_api_client.path.return_value.remove = mock_remove_path # Ensure .remove() is a mock
    return mock_api_client, mock_get_users, mock_remove_path

def test_delete_users_by_profile_success_deletes_matching(mock_delete_by_profile_deps, app_context):
    mock_api_client, mock_get_users, mock_remove_path = mock_delete_by_profile_deps
    target_profile = "delete_me_prof"
    mock_users_data = [
        {'.id': '*1', 'name': 'userA', 'profile': target_profile},
        {'.id': '*2', 'name': 'userB', 'profile': 'other_profile'},
        {'.id': '*3', 'name': 'userC', 'profile': target_profile},
    ]
    mock_get_users.return_value = mock_users_data

    with app_context:
        success, message, count = service.delete_users_by_profile(target_profile)

    assert success is True
    assert count == 2
    assert f"Successfully deleted 2 user(s) from profile '{target_profile}'." in message
    mock_remove_path.assert_any_call('*1')
    mock_remove_path.assert_any_call('*3')
    assert mock_remove_path.call_count == 2

def test_delete_users_by_profile_no_matching_users(mock_delete_by_profile_deps, app_context):
    mock_api_client, mock_get_users, mock_remove_path = mock_delete_by_profile_deps
    target_profile = "no_such_profile"
    mock_get_users.return_value = [
        {'.id': '*2', 'name': 'userB', 'profile': 'other_profile'},
    ]
    with app_context:
        success, message, count = service.delete_users_by_profile(target_profile)

    assert success is True
    assert count == 0
    assert f"No users found for profile '{target_profile}'. Nothing to delete." in message
    mock_remove_path.assert_not_called()

def test_delete_users_by_profile_api_none_at_start(mock_get_api_none, app_context):
    with app_context:
        success, message, count = service.delete_users_by_profile("any_profile")
    assert success is False
    assert message == "Mikrotik connection not available"
    assert count == 0

def test_delete_users_by_profile_get_users_fails(mocker, mock_get_api, app_context):
    # This test simulates get_mikrotik_api() returning None *during* the get_hotspot_users call
    mock_api_client, _ = mock_get_api # API client is initially available
    mocker.patch.object(service, 'get_hotspot_users', return_value=[]) # get_users returns empty
    mocker.patch('app.get_mikrotik_api', side_effect=[mock_api_client, None]) # First call ok, second (in get_users) fails

    with app_context:
        success, message, count = service.delete_users_by_profile("any_profile")
    assert success is False
    assert "Mikrotik connection not available (users fetch failed)" in message
    assert count == 0

def test_delete_users_by_profile_some_deletes_fail(mock_delete_by_profile_deps, app_context):
    mock_api_client, mock_get_users, mock_remove_path = mock_delete_by_profile_deps
    target_profile = "partial_delete_prof"
    mock_users_data = [
        {'.id': '*good1', 'name': 'userA', 'profile': target_profile},
        {'.id': '*bad1', 'name': 'userB', 'profile': target_profile}, # This one will fail
        {'.id': '*good2', 'name': 'userC', 'profile': target_profile},
    ]
    mock_get_users.return_value = mock_users_data

    # Simulate TrapError for one of the calls to remove
    def remove_side_effect(user_id):
        if user_id == '*bad1':
            raise TrapError("Failed to delete this specific user")
        return None # Success for others
    mock_remove_path.side_effect = remove_side_effect

    with app_context:
        success, message, count = service.delete_users_by_profile(target_profile)

    assert success is True # Overall operation considered success by service, message indicates partial failure
    assert count == 2 # Two successful deletions
    assert "Successfully deleted 2 user(s)" in message
    assert "Failed to delete 1 user(s)." in message # Check for the failure part
    mock_remove_path.assert_any_call('*good1')
    mock_remove_path.assert_any_call('*bad1')
    mock_remove_path.assert_any_call('*good2')
    assert mock_remove_path.call_count == 3


# --- Tests for delete_users_by_active_status ---
@pytest.fixture
def mock_delete_by_status_deps(mocker, mock_get_api):
    mock_api_client, _ = mock_get_api
    mock_get_users = mocker.patch.object(service, 'get_hotspot_users')
    mock_remove_path = MagicMock()
    mock_api_client.path.return_value.remove = mock_remove_path
    return mock_api_client, mock_get_users, mock_remove_path

@pytest.mark.parametrize("is_disabled_param, target_status_str, status_desc", [
    (True, 'true', 'disabled'),
    (False, 'false', 'active (enabled)')
])
def test_delete_users_by_active_status_success(mock_delete_by_status_deps, app_context, is_disabled_param, target_status_str, status_desc):
    mock_api_client, mock_get_users, mock_remove_path = mock_delete_by_status_deps
    mock_users_data = [
        {'.id': '*1', 'name': 'userA', 'disabled': target_status_str},
        {'.id': '*2', 'name': 'userB', 'disabled': 'true' if not is_disabled_param else 'false'}, # Opposite status
        {'.id': '*3', 'name': 'userC', 'disabled': target_status_str},
    ]
    mock_get_users.return_value = mock_users_data

    with app_context:
        success, message, count = service.delete_users_by_active_status(is_disabled=is_disabled_param)

    assert success is True
    assert count == 2
    assert f"Successfully deleted 2 {status_desc} user(s)." in message
    mock_remove_path.assert_any_call('*1')
    mock_remove_path.assert_any_call('*3')
    assert mock_remove_path.call_count == 2

def test_delete_users_by_active_status_no_matching(mock_delete_by_status_deps, app_context):
    mock_api_client, mock_get_users, mock_remove_path = mock_delete_by_status_deps
    mock_get_users.return_value = [
        {'.id': '*1', 'name': 'userA', 'disabled': 'false'}, # All are active
    ]
    with app_context: # Try to delete disabled users
        success, message, count = service.delete_users_by_active_status(is_disabled=True)

    assert success is True
    assert count == 0
    assert "No disabled users found. Nothing to delete." in message
    mock_remove_path.assert_not_called()


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

# --- Tests for get_basic_bandwidth_analytics ---
def test_get_basic_bandwidth_analytics_no_users(mocker, app_context):
    mocker.patch.object(service, 'get_hotspot_users', return_value=[])
    with app_context:
        analytics = service.get_basic_bandwidth_analytics()
    assert analytics['total_data_all_users'] == 0
    assert analytics['all_users_sorted_by_data'] == []
    assert analytics['data_usage_by_profile'] == {}

def test_get_basic_bandwidth_analytics_users_with_data(mocker, app_context):
    mock_users = [
        {'name': 'userA', 'profile': 'p1', 'bytes-in': '1000', 'bytes-out': '2000'}, # 3000
        {'name': 'userB', 'profile': 'p2', 'bytes-in': '500', 'bytes-out': '500'},   # 1000
        {'name': 'userC', 'profile': 'p1', 'bytes-in': '3000', 'bytes-out': '1000'}, # 4000
        {'name': 'userD', 'profile': 'p2', 'bytes-in': None, 'bytes-out': '500'},    # 500 (None bytes-in)
        {'name': 'userE', 'profile': 'p3', 'bytes-in': 'invalid', 'bytes-out': 'invalid'}, # 0 (invalid data)
    ]
    mocker.patch.object(service, 'get_hotspot_users', return_value=mock_users)
    with app_context:
        analytics = service.get_basic_bandwidth_analytics()

    assert analytics['total_data_all_users'] == 3000 + 1000 + 4000 + 500 + 0

    assert len(analytics['all_users_sorted_by_data']) == 5
    assert analytics['all_users_sorted_by_data'][0]['name'] == 'userC' # 4000
    assert analytics['all_users_sorted_by_data'][1]['name'] == 'userA' # 3000
    assert analytics['all_users_sorted_by_data'][2]['name'] == 'userB' # 1000
    assert analytics['all_users_sorted_by_data'][3]['name'] == 'userD' # 500
    assert analytics['all_users_sorted_by_data'][4]['name'] == 'userE' # 0

    assert analytics['data_usage_by_profile']['p1'] == 3000 + 4000
    assert analytics['data_usage_by_profile']['p2'] == 1000 + 500
    assert analytics['data_usage_by_profile']['p3'] == 0

def test_get_basic_bandwidth_analytics_service_unavailable(mocker, mock_get_api_none, app_context):
    # get_hotspot_users will return [] if API is None
    mocker.patch.object(service, 'get_hotspot_users', return_value=[]) # Explicitly mock to be sure
    with app_context:
        analytics = service.get_basic_bandwidth_analytics()
    assert analytics['total_data_all_users'] == 0
    assert analytics['all_users_sorted_by_data'] == []
    assert analytics['data_usage_by_profile'] == {}


# --- Tests for find_and_delete_expired_users ---
@pytest.fixture
def mock_find_delete_dependencies(mocker, mock_get_api): # Uses mock_get_api to get mock_api_client
    mock_api_client, _ = mock_get_api # We need the client part for .path().remove()

    # Mock the _parse_ros_time method as it's complex and tested separately
    mocker.patch.object(service, '_parse_ros_time', side_effect=lambda t: int(t[:-1]) if t and t[:-1].isdigit() else 0) # Simplified mock

    # Mock get_hotspot_users, which is called internally
    mock_get_users = mocker.patch.object(service, 'get_hotspot_users')

    return mock_api_client, mock_get_users

def test_find_and_delete_expired_users_time_limit(mock_find_delete_dependencies, app_context):
    mock_api_client, mock_get_users = mock_find_delete_dependencies

    mock_users_data = [
        {'.id': '*1', 'name': 'expired_time', 'limit-uptime': '10s', 'uptime': '20s'}, # Expired
        {'.id': '*2', 'name': 'active_time', 'limit-uptime': '100s', 'uptime': '20s'}, # Active
        {'.id': '*3', 'name': 'no_time_limit', 'limit-uptime': '0s', 'uptime': '500s'}, # No limit
    ]
    mock_get_users.return_value = mock_users_data

    # Path for remove: api.path('ip', 'hotspot', 'user').remove(user_id)
    mock_remove_path = MagicMock()
    mock_api_client.path.return_value = mock_remove_path

    with app_context:
        success, message, count = service.find_and_delete_expired_users()

    assert success is True
    assert count == 1
    assert "Successfully deleted 1 expired user(s)." in message
    mock_remove_path.remove.assert_called_once_with('*1')


def test_find_and_delete_expired_users_data_limit(mock_find_delete_dependencies, app_context):
    mock_api_client, mock_get_users = mock_find_delete_dependencies
    mock_users_data = [
        {'.id': '*1', 'name': 'expired_data', 'limit-bytes-total': '1000', 'bytes-in': '500', 'bytes-out': '600'}, # Expired (1100 > 1000)
        {'.id': '*2', 'name': 'active_data', 'limit-bytes-total': '2000', 'bytes-in': '500', 'bytes-out': '400'}, # Active (900 < 2000)
    ]
    mock_get_users.return_value = mock_users_data
    mock_remove_path = MagicMock()
    mock_api_client.path.return_value = mock_remove_path

    with app_context:
        success, message, count = service.find_and_delete_expired_users()

    assert success is True
    assert count == 1
    mock_remove_path.remove.assert_called_once_with('*1')

def test_find_and_delete_expired_users_no_one_expired(mock_find_delete_dependencies, app_context):
    mock_api_client, mock_get_users = mock_find_delete_dependencies
    mock_users_data = [
        {'.id': '*1', 'name': 'active_user', 'limit-uptime': '100s', 'uptime': '10s', 'limit-bytes-total': '1000', 'bytes-in': '10', 'bytes-out': '10'},
    ]
    mock_get_users.return_value = mock_users_data
    mock_remove_path = MagicMock() # Path for remove
    mock_api_client.path.return_value = mock_remove_path

    with app_context:
        success, message, count = service.find_and_delete_expired_users()
    assert success is True
    assert count == 0
    assert "Successfully deleted 0 expired user(s)." in message
    mock_remove_path.remove.assert_not_called()

def test_find_and_delete_expired_users_api_none(mock_get_api_none, app_context): # Test if get_mikrotik_api returns None at start
    with app_context:
        success, message, count = service.find_and_delete_expired_users()
    assert success is False
    assert message == "Mikrotik connection not available"
    assert count == 0

def test_find_and_delete_expired_users_get_users_fails(mocker, mock_get_api, app_context):
    # Simulate get_hotspot_users itself returning empty due to an internal API error
    # but get_mikrotik_api() initially succeeded.
    mocker.patch.object(service, 'get_hotspot_users', return_value=[])
    # And ensure that get_mikrotik_api when called by get_hotspot_users returns None
    mocker.patch('app.get_mikrotik_api', return_value=None) # This makes get_hotspot_users return []

    with app_context:
        success, message, count = service.find_and_delete_expired_users()

    # This scenario will now be caught by `if not users and api is None:`
    assert success is False
    assert "Mikrotik connection not available (users fetch failed)" in message
    assert count == 0

def test_find_and_delete_expired_users_delete_trap_error(mock_find_delete_dependencies, app_context):
    mock_api_client, mock_get_users = mock_find_delete_dependencies
    mock_users_data = [
        {'.id': '*1', 'name': 'expired_time', 'limit-uptime': '10s', 'uptime': '20s'}, # Expired
    ]
    mock_get_users.return_value = mock_users_data

    mock_remove_path = MagicMock()
    mock_api_client.path.return_value = mock_remove_path
    mock_remove_path.remove.side_effect = TrapError("Cannot delete active user")

    with app_context:
        success, message, count = service.find_and_delete_expired_users()

    assert success is True # The overall operation is true, but with errors
    assert count == 0 # No successful deletions
    assert "Failed to delete: expired_time" in message

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
