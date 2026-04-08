"""Simple echo MCP server for development and testing.

FOR SECURITY RESEARCH ONLY.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("echo-server")


@server.tool()
async def echo(message: str) -> str:
    """Return the input message unchanged.

    Args:
        message: The message to echo back.

    Returns:
        The same message, unchanged.
    """
    return message


def main() -> None:
    """Run the echo server via stdio."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
