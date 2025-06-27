import pytest
import json
from unittest.mock import patch

# Test data
TEST_PROFILE_NAME = "testprofile1"
TEST_PROFILE_ID = "*P1"

@pytest.fixture(autouse=True)
def mock_router_os_service_profile_methods(mocker):
    """Mocks all profile-related methods in RouterOSService for profile API tests."""
    mocker.patch('app.router_os_service.get_user_profiles', return_value=[])
    mocker.patch('app.router_os_service.create_hotspot_profile', return_value=(True, f"Profile '{TEST_PROFILE_NAME}' created successfully."))
    mocker.patch('app.router_os_service.edit_hotspot_profile', return_value=(True, "Profile updated successfully."))
    mocker.patch('app.router_os_service.delete_hotspot_profile', return_value=(True, "Profile deleted successfully."))

# --- GET /api/profiles ---
def test_get_profiles_success(logged_in_client):
    with patch('app.router_os_service.get_user_profiles') as mock_get:
        mock_get.return_value = [{'name': TEST_PROFILE_NAME, '.id': TEST_PROFILE_ID}]
        response = logged_in_client.get('/api/profiles')
        assert response.status_code == 200
        json_data = response.get_json()
        assert 'profiles' in json_data
        assert len(json_data['profiles']) == 1
        assert json_data['profiles'][0]['name'] == TEST_PROFILE_NAME

def test_get_profiles_empty(logged_in_client):
    # Default mock returns empty list
    response = logged_in_client.get('/api/profiles')
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'profiles' in json_data
    assert len(json_data['profiles']) == 0

# --- POST /api/profiles (Create Profile) ---
def test_create_profile_success(logged_in_client):
    profile_data = {
        "name": "newprofile",
        "rate-limit": "1M/1M",
        "session-timeout": "1d",
        "shared-users": "1"
    }
    response = logged_in_client.post('/api/profiles', json=profile_data)
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert f"Profile '{profile_data['name']}' created successfully." in json_data['message']

def test_create_profile_validation_failure_missing_name(logged_in_client):
    profile_data = {"rate-limit": "1M/1M"}
    response = logged_in_client.post('/api/profiles', json=profile_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'errors' in json_data
    assert 'name' in json_data['errors']

def test_create_profile_validation_failure_bad_rate_limit(logged_in_client):
    profile_data = {"name": "badprofile", "rate-limit": "invalidformat"}
    response = logged_in_client.post('/api/profiles', json=profile_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'errors' in json_data
    assert 'rate-limit' in json_data['errors']

def test_create_profile_service_failure(logged_in_client):
    with patch('app.router_os_service.create_hotspot_profile') as mock_create:
        mock_create.return_value = (False, "Mikrotik Error: Profile already exists")
        profile_data = {"name": "existingprofile"}
        response = logged_in_client.post('/api/profiles', json=profile_data)
        assert response.status_code == 200 # API itself is fine
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "Mikrotik Error: Profile already exists" in json_data['message']

# --- PUT /api/profiles/<profile_id> (Edit Profile) ---
def test_edit_profile_success(logged_in_client):
    edit_data = {"rate-limit": "2M/2M", "session-timeout": "2d"}
    response = logged_in_client.put(f'/api/profiles/{TEST_PROFILE_ID}', json=edit_data)
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "Profile updated successfully" in json_data['message']

def test_edit_profile_validation_failure_empty_name(logged_in_client):
    edit_data = {"name": ""}
    response = logged_in_client.put(f'/api/profiles/{TEST_PROFILE_ID}', json=edit_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'errors' in json_data
    assert 'name' in json_data['errors']

def test_edit_profile_no_data(logged_in_client):
    response = logged_in_client.put(f'/api/profiles/{TEST_PROFILE_ID}', json={})
    assert response.status_code == 400 # Current implementation expects data
    # If it were to return "No changes detected", status would be 200.
    # Current: if not data: return jsonify({'success': False, 'message': _('No data provided for update.')}), 400
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "No data provided for update" in json_data['message']


def test_edit_profile_service_failure_not_found(logged_in_client):
    with patch('app.router_os_service.edit_hotspot_profile') as mock_edit:
        mock_edit.return_value = (False, "Mikrotik Error: No such item")
        edit_data = {"rate-limit": "3M/3M"}
        response = logged_in_client.put('/api/profiles/ghostprofileid', json=edit_data)
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "Mikrotik Error: No such item" in json_data['message']

# --- DELETE /api/profiles/<profile_id> ---
def test_delete_profile_success(logged_in_client):
    response = logged_in_client.delete(f'/api/profiles/{TEST_PROFILE_ID}')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert "Profile deleted successfully" in json_data['message']

def test_delete_profile_service_failure(logged_in_client):
    with patch('app.router_os_service.delete_hotspot_profile') as mock_delete:
        mock_delete.return_value = (False, "Mikrotik Error: Profile in use")
        response = logged_in_client.delete(f'/api/profiles/{TEST_PROFILE_ID}')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is False
        assert "Mikrotik Error: Profile in use" in json_data['message']

# --- Unauthenticated access ---
def test_profile_apis_unauthenticated(client):
    endpoints_methods = [
        ('GET', '/api/profiles'),
        ('POST', '/api/profiles', {}),
        ('PUT', f'/api/profiles/{TEST_PROFILE_ID}', {}),
        ('DELETE', f'/api/profiles/{TEST_PROFILE_ID}')
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
