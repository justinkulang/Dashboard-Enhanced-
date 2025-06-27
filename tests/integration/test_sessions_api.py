import pytest
import json
from unittest.mock import patch

TEST_ACTIVE_SESSION_ID = "*S1"

@pytest.fixture(autouse=True)
def mock_router_os_service_session_methods(mocker):
    """Mocks session-related methods in RouterOSService for session API tests."""
    mocker.patch('app.router_os_service.get_active_sessions', return_value=[])
    mocker.patch('app.router_os_service.disconnect_user', return_value=(True, "User disconnected successfully"))

# --- GET /api/active-sessions ---
def test_get_active_sessions_success(logged_in_client):
    with patch('app.router_os_service.get_active_sessions') as mock_get:
        mock_get.return_value = [{'user': 'user1', '.id': TEST_ACTIVE_SESSION_ID, 'address': '1.2.3.4'}]
        response = logged_in_client.get('/api/active-sessions')
        assert response.status_code == 200
        json_data = response.get_json()
        assert 'sessions' in json_data
        assert len(json_data['sessions']) == 1
        assert json_data['sessions'][0]['.id'] == TEST_ACTIVE_SESSION_ID

def test_get_active_sessions_empty(logged_in_client):
    # Default mock returns empty list
    response = logged_in_client.get('/api/active-sessions')
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'sessions' in json_data
    assert len(json_data['sessions']) == 0

def test_get_active_sessions_service_error(logged_in_client):
    with patch('app.router_os_service.get_active_sessions') as mock_get:
        # Simulate service returning empty list on error, as per current service impl.
        mock_get.side_effect = Exception("Failed to fetch sessions")
        # Or, if service returns None or specific error structure, adapt this.
        # The current service methods for get_* return [] on error.
        response = logged_in_client.get('/api/active-sessions')
        assert response.status_code == 200 # API call itself is fine
        json_data = response.get_json()
        assert 'sessions' in json_data
        assert len(json_data['sessions']) == 0 # As service returns [] on error

# --- POST /api/disconnect-user/<active_id> ---
def test_disconnect_user_success(logged_in_client):
    response = logged_in_client.post(f'/api/disconnect-user/{TEST_ACTIVE_SESSION_ID}')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "User disconnected successfully" in json_data['message']
    # Verify the mock was called
    from app import router_os_service
    router_os_service.disconnect_user.assert_called_once_with(TEST_ACTIVE_SESSION_ID)


def test_disconnect_user_service_failure(logged_in_client):
    with patch('app.router_os_service.disconnect_user') as mock_disconnect:
        mock_disconnect.return_value = (False, "Mikrotik Error: No such active user")
        response = logged_in_client.post(f'/api/disconnect-user/{TEST_ACTIVE_SESSION_ID}')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "Mikrotik Error: No such active user" in json_data['message']

# --- Unauthenticated access ---
def test_session_apis_unauthenticated(client):
    endpoints_methods = [
        ('GET', '/api/active-sessions'),
        ('POST', f'/api/disconnect-user/{TEST_ACTIVE_SESSION_ID}')
    ]
    for method, endpoint in endpoints_methods:
        if method == 'GET':
            response = client.get(endpoint)
        elif method == 'POST':
            response = client.post(endpoint) # No JSON data needed for disconnect

        assert response.status_code == 302 # Redirects to login
        assert '/login' in response.location
