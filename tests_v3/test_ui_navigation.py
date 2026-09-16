from synthex_platform.ui_navigation import (
    DEVELOPER_NAVIGATION,
    PUBLIC_NAVIGATION,
    developer_mode_enabled,
    navigation_items,
)


def test_public_navigation_contains_only_researcher_facing_tools():
    assert PUBLIC_NAVIGATION == (
        "Home",
        "Analyze Papers",
        "Discover Papers",
        "Explore Results",
        "Visualize Data",
        "Gas Sensing Analytics",
        "Extract Data from Graphs",
    )
    assert not any("Advanced" in item for item in PUBLIC_NAVIGATION)
    assert not any("validation" in item.casefold() for item in PUBLIC_NAVIGATION)
    assert not any("benchmark" in item.casefold() for item in PUBLIC_NAVIGATION)
    assert not any("diagnostic" in item.casefold() for item in PUBLIC_NAVIGATION)


def test_developer_navigation_hidden_by_default():
    assert navigation_items(developer_mode=False) == PUBLIC_NAVIGATION


def test_developer_navigation_available_when_explicitly_enabled():
    items = navigation_items(developer_mode=True)
    assert items[: len(PUBLIC_NAVIGATION)] == PUBLIC_NAVIGATION
    assert items[len(PUBLIC_NAVIGATION):] == DEVELOPER_NAVIGATION


def test_developer_mode_truthy_values():
    for value in ("1", "true", "TRUE", "yes", "on"):
        assert developer_mode_enabled(value)
    for value in ("", "0", "false", "no", "off", "random"):
        assert not developer_mode_enabled(value)


def test_gas_sensing_is_native_unversioned_public_capability():
    assert "Gas Sensing Analytics" in PUBLIC_NAVIGATION
    assert all("V2" not in item and "V3" not in item for item in PUBLIC_NAVIGATION)
