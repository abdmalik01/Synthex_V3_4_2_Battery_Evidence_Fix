from synthex_platform.ui_errors import is_server_busy_error, public_error_notice


def test_transient_gemini_failure_becomes_server_busy_without_raw_payload():
    exc = RuntimeError("503 UNAVAILABLE: provider high demand; secret-detail")
    notice = public_error_notice(exc)
    assert is_server_busy_error(exc) is True
    assert notice.title == "Server Busy"
    assert notice.status == "server_busy"
    assert "503" not in notice.message
    assert "secret-detail" not in notice.message


def test_permission_denied_provider_failure_is_hidden_from_public_ui():
    exc = RuntimeError("403 PERMISSION_DENIED: Your project has been denied access")
    notice = public_error_notice(exc)
    assert notice.title == "Server Busy"
    assert "PERMISSION_DENIED" not in notice.message
    assert "denied access" not in notice.message


def test_validation_failure_gets_safe_retry_message_only():
    exc = ValueError("raw parser traceback: invalid internal schema field")
    notice = public_error_notice(exc, context="extraction_validation")
    assert notice.title == "Request Not Completed"
    assert notice.status == "could_not_complete"
    assert "raw parser" not in notice.message
    assert "schema" not in notice.message


def test_force_server_busy_never_exposes_exception_text():
    exc = RuntimeError("highly technical backend failure")
    notice = public_error_notice(exc, force_server_busy=True)
    assert notice.title == "Server Busy"
    assert "technical" not in notice.message
