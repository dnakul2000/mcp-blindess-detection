"""Entry point for the transparent MCP proxy.

Usage::

    python -m src.proxy -- <upstream_command...>
    python -m src.proxy --db experiment.db -- uv run python -m src.servers.echo
    python -m src.proxy uv run python -m src.servers.echo
"""

from __future__ import annotations

import asyncio
import sys

from src.proxy.proxy import TransparentProxy


def _parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Parse command-line arguments for the proxy entry point.

    Supports ``--db <path>`` for custom database path and ``--`` as a
    separator before the upstream command. If no ``--`` is present, all
    non-flag arguments are treated as the upstream command.

    Args:
        argv: The argument list (excluding the program name).

    Returns:
        A tuple of (db_path, upstream_command).

    Raises:
        SystemExit: If no upstream command is provided.
    """
    db_path = "experiment.db"
    upstream_command: list[str] = []

    # Look for -- separator.
    if "--" in argv:
        sep_idx = argv.index("--")
        pre = argv[:sep_idx]
        upstream_command = argv[sep_idx + 1 :]
    else:
        pre = []
        upstream_command = list(argv)

    # Parse flags from the pre-separator portion.
    i = 0
    remaining: list[str] = []
    while i < len(pre):
        if pre[i] == "--db" and i + 1 < len(pre):
            db_path = pre[i + 1]
            i += 2
        else:
            remaining.append(pre[i])
            i += 1

    # If we had a -- separator, any remaining pre-args with --db extracted
    # are unexpected; ignore them. If no --, the upstream_command may also
    # contain --db which we need to strip.
    if "--" not in argv:
        # Re-parse the flat list for --db.
        cleaned: list[str] = []
        j = 0
        while j < len(upstream_command):
            if upstream_command[j] == "--db" and j + 1 < len(upstream_command):
                db_path = upstream_command[j + 1]
                j += 2
            else:
                cleaned.append(upstream_command[j])
                j += 1
        upstream_command = cleaned

    if not upstream_command:
        print(
            "Usage: python -m src.proxy [--db <path>] -- <upstream_command...>",
            file=sys.stderr,
        )
        sys.exit(1)

    return db_path, upstream_command


def main() -> None:
    """Parse arguments and run the transparent proxy."""
    db_path, upstream_command = _parse_args(sys.argv[1:])
    proxy = TransparentProxy(upstream_command=upstream_command, db_path=db_path)
    asyncio.run(proxy.run())


if __name__ == "__main__":
    main()
