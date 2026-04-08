"""Integration tests for MCP servers using the official MCP client SDK.

FOR SECURITY RESEARCH ONLY.

Each test starts a real MCP server via stdio and communicates
with it using mcp.client.stdio.stdio_client + ClientSession.
"""

from __future__ import annotations

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server_params(module: str) -> StdioServerParameters:
    """Build StdioServerParameters for a given server module path."""
    return StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", module],
    )


# ---------------------------------------------------------------------------
# Echo server
# ---------------------------------------------------------------------------


async def test_echo_server_tools_list() -> None:
    """Echo server advertises exactly one tool named 'echo'."""
    params = _server_params("src.servers.echo")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()

    assert len(result.tools) == 1
    assert result.tools[0].name == "echo"


async def test_echo_server_echo() -> None:
    """Echo server returns the input message unchanged."""
    params = _server_params("src.servers.echo")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("echo", {"message": "hello"})

    assert any("hello" in c.text for c in result.content if hasattr(c, "text"))


async def test_echo_server_empty_string() -> None:
    """Echo server handles empty string input."""
    params = _server_params("src.servers.echo")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("echo", {"message": ""})

    texts = [c.text for c in result.content if hasattr(c, "text")]
    assert any(t == "" for t in texts)


async def test_echo_server_unicode() -> None:
    """Echo server preserves unicode content including emoji."""
    params = _server_params("src.servers.echo")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("echo", {"message": "日本語😀"})

    assert any("日本語😀" in c.text for c in result.content if hasattr(c, "text"))


# ---------------------------------------------------------------------------
# Shadow params server (H2 adversarial)
# ---------------------------------------------------------------------------


async def test_shadow_params_tools_list() -> None:
    """Shadow params server advertises get_weather with city in its schema."""
    params = _server_params("src.servers.shadow_params")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()

    tool_names = [t.name for t in result.tools]
    assert "get_weather" in tool_names

    weather_tool = next(t for t in result.tools if t.name == "get_weather")
    properties = weather_tool.inputSchema.get("properties", {})
    assert "city" in properties


async def test_shadow_params_normal_call() -> None:
    """Normal get_weather call returns weather data for the city."""
    params = _server_params("src.servers.shadow_params")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("get_weather", {"city": "London"})

    texts = [c.text for c in result.content if hasattr(c, "text")]
    full_text = " ".join(texts)
    assert "Weather for London" in full_text


async def test_shadow_params_shadow_activated() -> None:
    """Supplying the undeclared exfil_path triggers the shadow param marker."""
    params = _server_params("src.servers.shadow_params")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(
            "get_weather",
            {"city": "London", "exfil_path": "/etc/passwd"},
        )

    texts = [c.text for c in result.content if hasattr(c, "text")]
    full_text = " ".join(texts)
    assert "SHADOW_PARAM_ACTIVATED" in full_text


# ---------------------------------------------------------------------------
# Response injection server (H3 adversarial)
# ---------------------------------------------------------------------------


async def test_response_injection_tools_list() -> None:
    """Response injection server advertises get_weather and read_file."""
    params = _server_params("src.servers.response_injection")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()

    tool_names = {t.name for t in result.tools}
    assert "get_weather" in tool_names
    assert "read_file" in tool_names


async def test_response_injection_has_payload() -> None:
    """Response injection server embeds injection payload in get_weather response."""
    params = _server_params("src.servers.response_injection")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("get_weather", {"city": "London"})

    texts = [c.text for c in result.content if hasattr(c, "text")]
    full_text = " ".join(texts)
    # Default variant is "direct" which contains "IMPORTANT"
    assert "IMPORTANT" in full_text or "read_file" in full_text


# ---------------------------------------------------------------------------
# Control servers
# ---------------------------------------------------------------------------


async def test_control_strict_no_shadow() -> None:
    """Control-strict server returns clean weather with no shadow param marker."""
    params = _server_params("src.servers.control_strict")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("get_weather", {"city": "London"})

    texts = [c.text for c in result.content if hasattr(c, "text")]
    full_text = " ".join(texts)
    assert "Weather for London" in full_text
    assert "SHADOW_PARAM" not in full_text


async def test_control_clean_no_injection() -> None:
    """Control-clean server returns clean weather with no injection payload."""
    params = _server_params("src.servers.control_clean")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("get_weather", {"city": "London"})

    texts = [c.text for c in result.content if hasattr(c, "text")]
    full_text = " ".join(texts)
    assert "Weather for London" in full_text
    assert "IMPORTANT SYSTEM NOTE" not in full_text
