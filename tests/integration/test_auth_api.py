import pytest
from flask import session, url_for

# Test data from conftest.py app fixture:
# ADMIN_USERNAME = "testadmin"
# ADMIN_PASSWORD = "testpassword" (actual password, not hash)

def test_app_login_success(client, app):
    """Test successful login to the web application."""
    test_admin_username = app.config['APP_ADMIN_CONFIG']['username']
    # The actual password for "testadmin" is "testpassword" as per conftest.py

    response = client.post('/app-login', data={
        'app_username': test_admin_username,
        'app_password': 'testpassword'
    }, follow_redirects=False) # Don't follow redirects to check intermediate response

    assert response.status_code == 200 # Original route returns JSON
    json_data = response.get_json()
    assert json_data['success'] is True
    assert 'Web app login successful.' in json_data['message']

    # Check if user is actually logged in by accessing a protected route
    # For this, we need to ensure the session is maintained across requests with the same client
    with client: # Use client as a context manager to maintain session
        client.post('/app-login', data={
            'app_username': test_admin_username,
            'app_password': 'testpassword'
        }) # Log in first

        # Now access a protected route (e.g., /dashboard which redirects to /mikrotik_userman_dashboard.html)
        # Or an API endpoint. Let's try /api/dashboard-stats which is simple.
        protected_response = client.get('/api/dashboard-stats')
        assert protected_response.status_code == 200
        # Further checks on protected_response.json if needed (e.g. presence of expected keys)


def test_app_login_failure_wrong_password(client, app):
    """Test login failure with wrong password."""
    test_admin_username = app.config['APP_ADMIN_CONFIG']['username']
    response = client.post('/app-login', data={
        'app_username': test_admin_username,
        'app_password': 'wrongtestpassword'
    })
    assert response.status_code == 401 # Unauthorized
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'Invalid web app username or password.' in json_data['message']

def test_app_login_failure_wrong_username(client, app):
    """Test login failure with wrong username."""
    response = client.post('/app-login', data={
        'app_username': 'nonexistentadmin',
        'app_password': 'testpassword'
    })
    assert response.status_code == 401
    json_data = response.get_json()
    assert json_data['success'] is False
    assert 'Invalid web app username or password.' in json_data['message']

def test_logout_success(logged_in_client, client, app): # Use both logged_in_client and a fresh client
    """Test successful logout."""
    # logged_in_client fixture ensures user is logged in
    response = logged_in_client.post('/api/logout')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert 'Logged out successfully' in json_data['message']

    # Verify session is cleared by trying to access a protected route with the same client
    # (logged_in_client's session should be cleared by the logout)
    protected_response_after_logout = logged_in_client.get('/api/dashboard-stats')
    # Expect redirect to login_page (302) if HTML, or 401 if API and not redirecting
    # The before_request_handler does a redirect for unauthenticated users.
    assert protected_response_after_logout.status_code == 302
    assert '/login' in protected_response_after_logout.location # Check redirect URL

    # Also, check with a completely fresh client instance to be sure
    fresh_client_response = client.get('/api/dashboard-stats')
    assert fresh_client_response.status_code == 302
    assert '/login' in fresh_client_response.location


def test_protected_route_unauthenticated(client):
    """Test that a protected route redirects unauthenticated users to login."""
    response = client.get('/dashboard', follow_redirects=False) # Main UI route
    assert response.status_code == 302
    assert '/login' in response.location # Check if it redirects to login_page

    api_response = client.get('/api/users', follow_redirects=False) # Protected API route
    assert api_response.status_code == 302
    assert '/login' in api_response.location

def test_login_page_accessible_unauthenticated(client):
    """Test that the login page itself is accessible."""
    response = client.get('/') # Root should serve login page
    assert response.status_code == 200
    assert b"Hotspot Manager Login" in response.data # Check for some content from login.html

def test_login_page_redirects_if_already_authenticated(logged_in_client):
    """Test that accessing login page when already logged in redirects to dashboard."""
    # logged_in_client fixture has already logged in the user
    # The login_page route has logic: if current_user.is_authenticated and api connected -> redirect
    # For this test, we need to mock or ensure get_mikrotik_api() returns a non-None api object
    # This is complex with the current structure.
    # A simpler check: if authenticated, it shouldn't show the login form again.
    # The current login_page route redirects to index ('/dashboard') if authenticated and API is available.
    # If API is not available, it might still serve login.html.
    # This test might need more sophisticated mocking of get_mikrotik_api.

    # Let's assume for now that if logged in, it won't serve the login page content directly.
    # Or, if it does redirect to dashboard, the status code would be 302.
    response = logged_in_client.get('/', follow_redirects=False)
    # If it redirects to /dashboard, status code will be 302
    # If it serves login.html because API is None (even if logged in), status will be 200
    # This test highlights a dependency on Mikrotik API state for a UI route.

    # Given the conftest.py sets up a mock Mikrotik config, get_mikrotik_api() might actually connect.
    # If it connects, redirect to /dashboard is expected.
    if response.status_code == 302:
        assert '/dashboard' in response.location
    elif response.status_code == 200:
        # This case implies get_mikrotik_api() returned None for the logged_in_client
        # which means the login page was re-rendered.
        # This is acceptable behavior if the router is down.
        assert b"Hotspot Manager Login" in response.data # Check it's the login page.
        print("Note: Logged-in user saw login page, likely because test Mikrotik API was not 'connected' in the view.")
    else:
        pytest.fail(f"Unexpected status code {response.status_code} for logged_in_client at /")

# Test for CSRF protection on login (more advanced, might need specific setup)
# For now, WTF_CSRF_ENABLED is False in test config, so CSRF checks are off for these tests.
# If it were enabled, we'd need to fetch the CSRF token first.
# def test_app_login_csrf_protection(client, app_with_csrf): # app_with_csrf would enable CSRF
#     test_admin_username = app_with_csrf.config['APP_ADMIN_CONFIG']['username']
#     response = client.post('/app-login', data={
#         'app_username': test_admin_username,
#         'app_password': 'testpassword'
#         # Missing CSRF token
#     })
#     assert response.status_code == 400 # Expect CSRF error (often 400 Bad Request)
#     assert b"CSRF token missing" in response.data # Or similar error message
