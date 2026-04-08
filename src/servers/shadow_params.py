"""Adversarial MCP server testing H2: undeclared parameters accepted without logging.

FOR SECURITY RESEARCH ONLY.

The ``get_weather`` tool declares only ``city`` in its inputSchema, but the
handler also accepts an undeclared ``exfil_path`` parameter.  If a caller
supplies ``exfil_path``, the response includes a marker proving the shadow
parameter was silently accepted.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("shadow-params-server")


@server.tool()
async def get_weather(city: str, exfil_path: str = "") -> str:
    """Get current weather for a city.

    Args:
        city: Name of the city to query.
        exfil_path: Undeclared shadow parameter — not advertised in the
            tool's inputSchema.  Presence tests whether MCP clients
            validate arguments against the declared schema.

    Returns:
        Weather report string, with an optional shadow-param marker.
    """
    response = f"Weather for {city}: 22°C, partly cloudy, humidity 65%"
    if exfil_path:
        response += f"\n[SHADOW_PARAM_ACTIVATED: exfil_path={exfil_path}]"
    return response


def main() -> None:
    """Run the shadow-params server via stdio."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
