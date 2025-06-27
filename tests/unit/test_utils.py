import pytest
from app import format_bytes_for_export, generate_qr_code_base64, RouterOSService, QRCODE_AVAILABLE
# For _parse_ros_time, we'll access it via a RouterOSService instance or make it static/standalone later
# For now, let's assume we can call it. If RouterOSService has a complex __init__, this might need adjustment.
# If _parse_ros_time can be made static or moved out, that's cleaner.

# --- Tests for format_bytes_for_export ---

def test_format_bytes_unlimited():
    assert format_bytes_for_export(None) == "Unlimited"
    assert format_bytes_for_export('') == "Unlimited"
    assert format_bytes_for_export('0') == "Unlimited" # As per current implementation detail
    assert format_bytes_for_export(0) == "0 B" # Actual 0 bytes should be 0 B

def test_format_bytes_various_sizes():
    assert format_bytes_for_export(100) == "100.00 B" # Current impl adds .00 for B too
    assert format_bytes_for_export(1024) == "1.00 KB"
    assert format_bytes_for_export(1536) == "1.50 KB" # 1024 * 1.5
    assert format_bytes_for_export(1024 * 1024) == "1.00 MB"
    assert format_bytes_for_export(1024 * 1024 * 500) == "500.00 MB"
    assert format_bytes_for_export(1024 * 1024 * 1024) == "1.00 GB"
    assert format_bytes_for_export(1024**4) == "1.00 TB"
    assert format_bytes_for_export(1024**5) == "1024.00 TB" # Maxes out at TB with this logic

def test_format_bytes_string_input():
    assert format_bytes_for_export("2048") == "2.00 KB"

def test_format_bytes_invalid_input():
    # Current function returns the input as string for non-convertible types
    assert format_bytes_for_export("invalid") == "invalid"
    assert format_bytes_for_export("1024k") == "1024k" # Not parsed as number

# --- Tests for _parse_ros_time ---
# Assuming RouterOSService can be instantiated without side effects for this test,
# or that _parse_ros_time will be made static/standalone.
# For now, let's proceed by instantiating.

ros_service_instance = RouterOSService() # Create an instance to access the method

def test_parse_ros_time_empty_and_zero():
    assert ros_service_instance._parse_ros_time("") == 0
    assert ros_service_instance._parse_ros_time(None) == 0 # Based on current impl (if not time_str)
    assert ros_service_instance._parse_ros_time("0s") == 0 # Explicit zero

def test_parse_ros_time_simple_units():
    assert ros_service_instance._parse_ros_time("5s") == 5
    assert ros_service_instance._parse_ros_time("10m") == 10 * 60
    assert ros_service_instance._parse_ros_time("2h") == 2 * 3600
    assert ros_service_instance._parse_ros_time("3d") == 3 * 86400
    assert ros_service_instance._parse_ros_time("1w") == 1 * 604800

def test_parse_ros_time_combined_units():
    assert ros_service_instance._parse_ros_time("1h30m") == 3600 + (30 * 60)
    assert ros_service_instance._parse_ros_time("2d12h") == (2 * 86400) + (12 * 3600)
    assert ros_service_instance._parse_ros_time("1w3d5h10m5s") == 604800 + (3 * 86400) + (5 * 3600) + (10 * 60) + 5

def test_parse_ros_time_no_units():
    assert ros_service_instance._parse_ros_time("12345") == 0 # No units, should parse as 0

def test_parse_ros_time_invalid_format():
    assert ros_service_instance._parse_ros_time("1x2y") == 0
    assert ros_service_instance._parse_ros_time("1hour") == 0

# --- Tests for generate_qr_code_base64 ---
# These tests are basic: check if it runs and returns a string, or None if unavailable.
# Detailed image comparison is out of scope for simple unit tests.

@pytest.mark.skipif(not QRCODE_AVAILABLE, reason="qrcode library not available, skipping QR tests")
def test_generate_qr_code_returns_base64_string():
    login_url = "http://example.com/login"
    username = "testuser"
    password = "testpassword"
    qr_b64 = generate_qr_code_base64(login_url, username, password)
    assert isinstance(qr_b64, str)
    assert len(qr_b64) > 50 # Arbitrary check for non-empty sensible base64
    # Further check: try to decode it as base64 (optional)
    import base64
    try:
        base64.b64decode(qr_b64)
    except Exception:
        pytest.fail("Generated QR string is not valid Base64")

def test_generate_qr_code_unavailable(monkeypatch):
    monkeypatch.setattr("app.QRCODE_AVAILABLE", False) # Simulate qrcode not being available
    qr_b64 = generate_qr_code_base64("http://url", "user", "pass")
    assert qr_b64 is None

# Test case for when hotspot_login_url is empty in _generate_vouchers_page_html (indirectly affects QR)
# This is more of an integration point, but if generate_qr_code_base64 itself handles it:
@pytest.mark.skipif(not QRCODE_AVAILABLE, reason="qrcode library not available")
def test_generate_qr_code_with_empty_login_url():
    # The generate_qr_code_base64 function itself doesn't directly care if login_url is empty,
    # it will just generate a QR for that empty or partial URL.
    # The _generate_vouchers_page_html handles the logic of not calling it or handling None.
    # So, this test is more about ensuring it doesn't crash with an empty URL.
    qr_b64 = generate_qr_code_base64("", "user", "pass")
    assert isinstance(qr_b64, str) # Will generate QR for "?username=user&password=pass"
    assert len(qr_b64) > 0
