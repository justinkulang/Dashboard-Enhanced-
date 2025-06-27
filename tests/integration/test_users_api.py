import pytest
import json
from unittest.mock import patch

# Test data
TEST_USER_USERNAME = "testuser1"
TEST_USER_PROFILE = "default"

@pytest.fixture(autouse=True)
def mock_router_os_service_user_methods(mocker):
    """Mocks all user-related methods in RouterOSService for user API tests."""
    mocker.patch('app.router_os_service.get_hotspot_users', return_value=[])
    mocker.patch('app.router_os_service.create_hotspot_user', return_value=(True, "User created successfully"))
    mocker.patch('app.router_os_service.edit_hotspot_user', return_value=(True, "User updated successfully"))
    mocker.patch('app.router_os_service.delete_hotspot_user', return_value=(True, "User deleted successfully"))
    # Add mocks for other methods if they are indirectly called or if more complex scenarios are needed

# --- GET /api/users ---
def test_get_users_success(logged_in_client):
    """Test successfully fetching users."""
    with patch('app.router_os_service.get_hotspot_users') as mock_get:
        mock_get.return_value = [{'name': TEST_USER_USERNAME, 'profile': TEST_USER_PROFILE}]
        response = logged_in_client.get('/api/users')
        assert response.status_code == 200
        json_data = response.get_json()
        assert 'users' in json_data
        assert len(json_data['users']) == 1
        assert json_data['users'][0]['name'] == TEST_USER_USERNAME

def test_get_users_empty(logged_in_client):
    """Test fetching users when no users exist."""
    # Default mock returns empty list
    response = logged_in_client.get('/api/users')
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'users' in json_data
    assert len(json_data['users']) == 0

# --- POST /api/users (Create User) ---
def test_create_user_success(logged_in_client):
    """Test successful user creation with valid data."""
    user_data = {
        "name": "newvaliduser",
        "password": "password123",
        "profile": "default",
        "limit-uptime": "1d",
        "dataLimit": "1024" # In MB from UI
    }
    response = logged_in_client.post('/api/users', json=user_data)
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "User created successfully" in json_data['message']
    # Check if router_os_service.create_hotspot_user was called with transformed data
    # (dataLimit MB to bytes for 'limit-bytes-total')
    # This requires inspecting the arguments passed to the mock.
    # app.router_os_service.create_hotspot_user.assert_called_once() # Pytest-mock style
    # called_args = app.router_os_service.create_hotspot_user.call_args[0][0]
    # assert called_args['name'] == user_data['name']
    # assert called_args['limit-bytes-total'] == 1024 * 1024 * 1024


def test_create_user_validation_failure_missing_fields(logged_in_client):
    """Test user creation failure due to missing required fields."""
    response = logged_in_client.post('/api/users', json={}) # Empty data
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'errors' in json_data
    assert 'name' in json_data['errors']
    assert 'password' in json_data['errors']
    assert 'profile' in json_data['errors']

def test_create_user_validation_failure_bad_length(logged_in_client):
    """Test user creation failure due to bad field length."""
    user_data = {"name": "u", "password": "p", "profile": "default"}
    response = logged_in_client.post('/api/users', json=user_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert 'errors' in json_data
    assert 'name' in json_data['errors'] # "Username must be between 3 and 64 characters."
    assert 'password' in json_data['errors'] # "Password must be between 6 and 64 characters."

def test_create_user_service_failure(logged_in_client):
    """Test user creation when the service layer reports a failure."""
    with patch('app.router_os_service.create_hotspot_user') as mock_create:
        mock_create.return_value = (False, "Mikrotik Error: User already exists")
        user_data = {"name": "existinguser", "password": "password123", "profile": "default"}
        response = logged_in_client.post('/api/users', json=user_data)
        assert response.status_code == 200 # API itself succeeded, but operation failed
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "Mikrotik Error: User already exists" in json_data['message']

# --- PUT /api/users/<username> (Edit User) ---
def test_edit_user_success(logged_in_client):
    """Test successful user edit with valid data."""
    edit_data = {"comment": "Updated comment", "profile": "vip"}
    response = logged_in_client.put(f'/api/users/{TEST_USER_USERNAME}', json=edit_data)
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "User updated successfully" in json_data['message']

def test_edit_user_validation_failure_bad_password(logged_in_client):
    """Test user edit failure due to invalid password length."""
    edit_data = {"password": "short"}
    response = logged_in_client.put(f'/api/users/{TEST_USER_USERNAME}', json=edit_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'errors' in json_data
    assert 'password' in json_data['errors']

def test_edit_user_no_changes(logged_in_client):
    """Test user edit when no actual data is sent to update."""
    response = logged_in_client.put(f'/api/users/{TEST_USER_USERNAME}', json={})
    assert response.status_code == 200 # Should be success as per current implementation
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "No changes detected" in json_data['message']

def test_edit_user_service_failure_not_found(logged_in_client):
    """Test user edit when the service reports user not found."""
    with patch('app.router_os_service.edit_hotspot_user') as mock_edit:
        mock_edit.return_value = (False, "User not found")
        edit_data = {"comment": "Trying to update ghost"}
        response = logged_in_client.put('/api/users/ghostuser', json=edit_data)
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "User not found" in json_data['message']

# --- DELETE /api/users/<username> ---
def test_delete_user_success(logged_in_client):
    """Test successful user deletion."""
    response = logged_in_client.delete(f'/api/users/{TEST_USER_USERNAME}')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "User deleted successfully" in json_data['message']

def test_delete_user_service_failure_not_found(logged_in_client):
    """Test user deletion when service reports user not found."""
    with patch('app.router_os_service.delete_hotspot_user') as mock_delete:
        mock_delete.return_value = (False, "User not found")
        response = logged_in_client.delete('/api/users/ghostuser_to_delete')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "User not found" in json_data['message']

def test_delete_user_service_trap_error(logged_in_client):
    """Test user deletion when service reports a trap error."""
    with patch('app.router_os_service.delete_hotspot_user') as mock_delete:
        mock_delete.return_value = (False, "Mikrotik Error: User has active session")
        response = logged_in_client.delete(f'/api/users/{TEST_USER_USERNAME}') # User exists
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "Mikrotik Error: User has active session" in json_data['message']

# --- Unauthenticated access ---
def test_user_apis_unauthenticated(client):
    """Test user API endpoints require authentication."""
    endpoints_methods = [
        ('GET', '/api/users'),
        ('POST', '/api/users', {}),
        ('PUT', f'/api/users/{TEST_USER_USERNAME}', {}),
        ('DELETE', f'/api/users/{TEST_USER_USERNAME}')
    ]
    for method, endpoint, data in endpoints_methods:
        if method == 'GET':
            response = client.get(endpoint)
        elif method == 'POST':
            response = client.post(endpoint, json=data)
        elif method == 'PUT':
            response = client.put(endpoint, json=data)
        elif method == 'DELETE':
            response = client.delete(endpoint)

        assert response.status_code == 302 # Redirects to login
        assert '/login' in response.location
