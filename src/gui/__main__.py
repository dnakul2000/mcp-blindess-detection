"""Entry point: ``python -m src.gui``."""

from __future__ import annotations

import webbrowser

import uvicorn

from src.gui.config import HOST, PORT


def main() -> None:
    """Launch the GUI server and open a browser tab."""
    url = f"http://{HOST}:{PORT}"
    print(f"Starting MCP Detection Blindness GUI at {url}")  # noqa: T201
    webbrowser.open(url)
    uvicorn.run("src.gui.app:create_app", host=HOST, port=PORT, factory=True)


if __name__ == "__main__":
    main()
