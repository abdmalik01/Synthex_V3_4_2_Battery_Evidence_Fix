from pathlib import Path


def test_public_streamlit_sections_do_not_echo_raw_exception_messages():
    source = Path("platform_app.py").read_text(encoding="utf-8")
    public_source = source.split('elif page == "Developer · Battery validation":', 1)[0]

    assert "st.error(str(exc))" not in public_source
    assert '"message": str(exc)' not in public_source
    assert "Calibration was not accepted:" not in public_source
    assert "SERVER Busy" not in public_source
    assert "Server Busy" in public_source


def test_developer_diagnostics_can_still_surface_technical_details():
    source = Path("platform_app.py").read_text(encoding="utf-8")
    developer_source = source.split('elif page == "Developer · Battery validation":', 1)[1]
    assert "Developer · Diagnostics" in developer_source
    assert "st.error(str(exc))" in developer_source
