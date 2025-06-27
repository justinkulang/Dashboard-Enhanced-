import pytest
import json
from unittest.mock import patch

TEST_PROFILE_TO_DELETE_USERS_FROM = "guest_profile"
DELETED_COUNT_EXAMPLE = 5

@pytest.fixture(autouse=True)
def mock_router_os_service_maintenance_methods(mocker):
    """Mocks maintenance-related methods in RouterOSService."""
    mocker.patch('app.router_os_service.find_and_delete_expired_users',
                 return_value=(True, f"Successfully deleted {DELETED_COUNT_EXAMPLE} expired user(s).", DELETED_COUNT_EXAMPLE))
    mocker.patch('app.router_os_service.delete_users_by_profile',
                 return_value=(True, f"Successfully deleted {DELETED_COUNT_EXAMPLE} user(s) from profile '{TEST_PROFILE_TO_DELETE_USERS_FROM}'.", DELETED_COUNT_EXAMPLE))
    mocker.patch('app.router_os_service.delete_users_by_active_status',
                 return_value=(True, f"Successfully deleted {DELETED_COUNT_EXAMPLE} active (enabled) user(s).", DELETED_COUNT_EXAMPLE))


# --- POST /api/delete-expired-users ---
def test_delete_expired_users_success(logged_in_client):
    response = logged_in_client.post('/api/delete-expired-users')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert f"Successfully deleted {DELETED_COUNT_EXAMPLE} expired user(s)." in json_data['message']
    assert json_data['deleted_count'] == DELETED_COUNT_EXAMPLE

def test_delete_expired_users_service_failure(logged_in_client):
    with patch('app.router_os_service.find_and_delete_expired_users') as mock_delete_expired:
        mock_delete_expired.return_value = (False, "An unexpected error occurred", 0)
        response = logged_in_client.post('/api/delete-expired-users')
        assert response.status_code == 200 # API call itself is fine
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "An unexpected error occurred" in json_data['message']
        assert json_data['deleted_count'] == 0

# --- DELETE /api/users/delete-by-profile/<profile_name> ---
def test_delete_users_by_profile_success(logged_in_client):
    response = logged_in_client.delete(f'/api/users/delete-by-profile/{TEST_PROFILE_TO_DELETE_USERS_FROM}')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert f"Successfully deleted {DELETED_COUNT_EXAMPLE} user(s) from profile '{TEST_PROFILE_TO_DELETE_USERS_FROM}'." in json_data['message']
    assert json_data['deleted_count'] == DELETED_COUNT_EXAMPLE
    from app import router_os_service
    router_os_service.delete_users_by_profile.assert_called_once_with(TEST_PROFILE_TO_DELETE_USERS_FROM)


def test_delete_users_by_profile_service_failure_no_users(logged_in_client):
    with patch('app.router_os_service.delete_users_by_profile') as mock_delete_by_prof:
        mock_delete_by_prof.return_value = (True, f"No users found for profile '{TEST_PROFILE_TO_DELETE_USERS_FROM}'. Nothing to delete.", 0)
        response = logged_in_client.delete(f'/api/users/delete-by-profile/{TEST_PROFILE_TO_DELETE_USERS_FROM}')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True # Operation considered successful by service
        assert "No users found" in json_data['message']
        assert json_data['deleted_count'] == 0

# --- DELETE /api/users/delete-by-active-status/<status> ---
def test_delete_users_by_status_active_success(logged_in_client):
    status_to_delete = "active"
    with patch('app.router_os_service.delete_users_by_active_status') as mock_delete_by_status:
        # Adjust mock to reflect the status being tested
        mock_delete_by_status.return_value = (True, f"Successfully deleted {DELETED_COUNT_EXAMPLE} active (enabled) user(s).", DELETED_COUNT_EXAMPLE)
        response = logged_in_client.delete(f'/api/users/delete-by-active-status/{status_to_delete}')

    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert f"Successfully deleted {DELETED_COUNT_EXAMPLE} active (enabled) user(s)." in json_data['message']
    assert json_data['deleted_count'] == DELETED_COUNT_EXAMPLE
    from app import router_os_service
    router_os_service.delete_users_by_active_status.assert_called_once_with(False) # is_disabled = False for 'active'

def test_delete_users_by_status_disabled_success(logged_in_client):
    status_to_delete = "disabled"
    with patch('app.router_os_service.delete_users_by_active_status') as mock_delete_by_status:
        mock_delete_by_status.return_value = (True, f"Successfully deleted {DELETED_COUNT_EXAMPLE} disabled user(s).", DELETED_COUNT_EXAMPLE)
        response = logged_in_client.delete(f'/api/users/delete-by-active-status/{status_to_delete}')

    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert f"Successfully deleted {DELETED_COUNT_EXAMPLE} disabled user(s)." in json_data['message']
    assert json_data['deleted_count'] == DELETED_COUNT_EXAMPLE
    from app import router_os_service
    router_os_service.delete_users_by_active_status.assert_called_once_with(True) # is_disabled = True for 'disabled'

def test_delete_users_by_status_invalid_status(logged_in_client):
    response = logged_in_client.delete('/api/users/delete-by-active-status/invalidstatus')
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "Invalid status parameter" in json_data['message']

# --- Unauthenticated access ---
def test_maintenance_apis_unauthenticated(client):
    endpoints_methods = [
        ('POST', '/api/delete-expired-users'),
        ('DELETE', f'/api/users/delete-by-profile/{TEST_PROFILE_TO_DELETE_USERS_FROM}'),
        ('DELETE', '/api/users/delete-by-active-status/active')
    ]
    for method, endpoint in endpoints_methods:
        if method == 'POST':
            response = client.post(endpoint)
        elif method == 'DELETE':
            response = client.delete(endpoint)

        assert response.status_code == 302 # Redirects to login
        assert '/login' in response.location
