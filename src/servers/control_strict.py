"""Control server for H2 — strict schema validation baseline.

FOR SECURITY RESEARCH ONLY.

Identical interface to ``shadow_params.py`` but accepts ONLY the declared
``city`` parameter.  Used as a control to confirm that observed effects in
the adversarial variant are attributable to the shadow parameter.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("control-strict-server")


@server.tool()
async def get_weather(city: str) -> str:
    """Get current weather for a city.

    Args:
        city: Name of the city to query.

    Returns:
        Clean weather report string.
    """
    return f"Weather for {city}: 22°C, partly cloudy, humidity 65%"


def main() -> None:
    """Run the control-strict server via stdio."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
