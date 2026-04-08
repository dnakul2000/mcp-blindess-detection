"""Direct tests for server tool functions (not via MCP protocol).

The integration tests in test_servers.py run servers in subprocesses
via the MCP client SDK, which means the coverage tool cannot track
coverage of the server source files. These tests import and call the
tool functions directly to ensure source-level coverage.
"""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# Echo server
# ---------------------------------------------------------------------------


async def test_echo_tool_direct() -> None:
    from src.servers.echo import echo

    result = await echo(message="hello world")
    assert result == "hello world"


def test_echo_server_exists() -> None:
    from src.servers.echo import server

    assert server.name == "echo-server"


def test_echo_main_calls_run() -> None:
    from src.servers.echo import main

    with patch("src.servers.echo.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Shadow params server
# ---------------------------------------------------------------------------


async def test_shadow_params_weather_normal() -> None:
    from src.servers.shadow_params import get_weather

    result = await get_weather(city="London")
    assert "Weather for London" in result
    assert "SHADOW_PARAM" not in result


async def test_shadow_params_weather_with_exfil() -> None:
    from src.servers.shadow_params import get_weather

    result = await get_weather(city="London", exfil_path="/etc/passwd")
    assert "SHADOW_PARAM_ACTIVATED" in result
    assert "exfil_path=/etc/passwd" in result


def test_shadow_params_server_exists() -> None:
    from src.servers.shadow_params import server

    assert server.name == "shadow-params-server"


def test_shadow_params_main_calls_run() -> None:
    from src.servers.shadow_params import main

    with patch("src.servers.shadow_params.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Response injection server
# ---------------------------------------------------------------------------


async def test_response_injection_weather() -> None:
    from src.servers.response_injection import get_weather

    result = await get_weather(city="London")
    assert "Weather for London" in result
    # Should contain an injection payload.
    assert len(result) > len("Weather for London: 22°C, partly cloudy, humidity 65%")


async def test_response_injection_read_file() -> None:
    from src.servers.response_injection import read_file

    result = await read_file(path="/etc/passwd")
    assert "MOCK" in result
    assert "/etc/passwd" in result


def test_response_injection_server_exists() -> None:
    from src.servers.response_injection import server

    assert server.name == "response-injection-server"


def test_response_injection_config_loaded() -> None:
    from src.servers.response_injection import _CONFIG

    assert _CONFIG.payload  # Should have a non-empty payload.


def test_response_injection_false_error_variant_in_map() -> None:
    from src.servers.config import InjectionVariant
    from src.servers.response_injection import _VARIANT_MAP

    assert "false_error" in _VARIANT_MAP
    assert _VARIANT_MAP["false_error"] == InjectionVariant.FALSE_ERROR


def test_response_injection_main_calls_run() -> None:
    from src.servers.response_injection import main

    with patch("src.servers.response_injection.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Control clean server
# ---------------------------------------------------------------------------


async def test_control_clean_weather() -> None:
    from src.servers.control_clean import get_weather

    result = await get_weather(city="London")
    assert "Weather for London" in result


async def test_control_clean_read_file() -> None:
    from src.servers.control_clean import read_file

    result = await read_file(path="/tmp/test")
    assert "MOCK" in result


def test_control_clean_server_exists() -> None:
    from src.servers.control_clean import server

    assert server.name == "control-clean-server"


def test_control_clean_main_calls_run() -> None:
    from src.servers.control_clean import main

    with patch("src.servers.control_clean.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Control strict server
# ---------------------------------------------------------------------------


async def test_control_strict_weather() -> None:
    from src.servers.control_strict import get_weather

    result = await get_weather(city="London")
    assert "Weather for London" in result


def test_control_strict_server_exists() -> None:
    from src.servers.control_strict import server

    assert server.name == "control-strict-server"


def test_control_strict_main_calls_run() -> None:
    from src.servers.control_strict import main

    with patch("src.servers.control_strict.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Combined server (H2 + H3)
# ---------------------------------------------------------------------------


async def test_combined_weather_normal() -> None:
    from src.servers.combined import get_weather

    result = await get_weather(city="London")
    assert "Weather for London" in result
    assert "SHADOW_PARAM" not in result
    # Should contain an injection payload.
    assert len(result) > len("Weather for London: 22°C, partly cloudy, humidity 65%")


async def test_combined_weather_with_exfil() -> None:
    from src.servers.combined import get_weather

    result = await get_weather(city="London", exfil_path="/etc/passwd")
    assert "SHADOW_PARAM_ACTIVATED" in result
    assert "exfil_path=/etc/passwd" in result
    # Should also contain injection payload.
    assert len(result) > len(
        "Weather for London: 22°C, partly cloudy, humidity 65%\n"
        "[SHADOW_PARAM_ACTIVATED: exfil_path=/etc/passwd]"
    )


async def test_combined_read_file() -> None:
    from src.servers.combined import read_file

    result = await read_file(path="/tmp/test")
    assert "MOCK" in result
    assert "/tmp/test" in result


def test_combined_server_exists() -> None:
    from src.servers.combined import server

    assert server.name == "combined-server"


def test_combined_config_loaded() -> None:
    from src.servers.combined import _CONFIG

    assert _CONFIG.payload


def test_combined_main_calls_run() -> None:
    from src.servers.combined import main

    with patch("src.servers.combined.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Name collision server
# ---------------------------------------------------------------------------


async def test_name_collision_weather() -> None:
    from src.servers.name_collision import get_weather

    result = await get_weather(city="London")
    assert "Weather for London" in result
    assert "read_file" in result
    assert "verification" in result.lower() or "verify" in result.lower()


async def test_name_collision_read_file() -> None:
    from src.servers.name_collision import read_file

    result = await read_file(path="/tmp/weather_cache.json")
    assert "NAME_COLLISION_MARKER" in result
    assert "/tmp/weather_cache.json" in result
    assert "CACHE_RESULT" in result


def test_name_collision_server_exists() -> None:
    from src.servers.name_collision import server

    assert server.name == "name-collision-server"


def test_name_collision_main_calls_run() -> None:
    from src.servers.name_collision import main

    with patch("src.servers.name_collision.server") as mock_server:
        main()
        mock_server.run.assert_called_once_with(transport="stdio")
