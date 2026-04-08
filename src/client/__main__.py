"""Entry point for the experiment MCP client.

Usage::

    python -m src.client --server "uv run python -m src.servers.echo" --prompt "Hello"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shlex
import sys
from typing import TYPE_CHECKING

from src.client.agent import AgentLoop

if TYPE_CHECKING:
    from src.client.providers.base import LLMProvider


def _build_provider(args: argparse.Namespace) -> LLMProvider:
    """Construct the appropriate LLM adapter from CLI arguments.

    Args:
        args: Parsed command-line arguments.

    Returns:
        An LLMProvider implementation.
    """
    provider = args.provider

    if provider == "ollama":
        from src.client.providers.ollama import OllamaAdapter

        base_url = args.base_url or "http://localhost:11434"
        return OllamaAdapter(base_url=base_url)

    if provider == "openai":
        from src.client.providers.openai_compat import OpenAICompatAdapter

        if not args.api_key:
            sys.exit("Error: --api-key required for openai provider")
        base_url = args.base_url or "https://api.openai.com/v1"
        return OpenAICompatAdapter(
            base_url=base_url,
            api_key=args.api_key,
            provider_name_override="openai",
        )

    if provider == "openrouter":
        from src.client.providers.openai_compat import OpenAICompatAdapter

        if not args.api_key:
            sys.exit("Error: --api-key required for openrouter provider")
        base_url = args.base_url or "https://openrouter.ai/api/v1"
        return OpenAICompatAdapter(
            base_url=base_url,
            api_key=args.api_key,
            provider_name_override="openrouter",
        )

    if provider == "anthropic":
        from src.client.providers.anthropic import AnthropicAdapter

        if not args.api_key:
            sys.exit("Error: --api-key required for anthropic provider")
        base_url = args.base_url or "https://api.anthropic.com/v1"
        return AnthropicAdapter(api_key=args.api_key, base_url=base_url)

    if provider == "google":
        from src.client.providers.google import GoogleAdapter

        if not args.api_key:
            sys.exit("Error: --api-key required for google provider")
        base_url = args.base_url or "https://generativelanguage.googleapis.com/v1beta"
        return GoogleAdapter(api_key=args.api_key, base_url=base_url)

    sys.exit(f"Error: unknown provider '{provider}'")


_DEFAULT_MODELS: dict[str, str] = {
    "ollama": "llama3.2",
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "google": "gemini-2.0-flash",
}


def main() -> None:
    """Parse arguments and run the experiment agent loop."""
    parser = argparse.ArgumentParser(
        description="MCP experiment client with LLM adapter layer",
    )
    parser.add_argument(
        "--server",
        required=True,
        help="Server command string (will be shell-split)",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "openai", "openrouter", "anthropic", "google"],
        default="ollama",
        help="LLM provider to use (default: ollama)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model identifier (default depends on provider)",
    )
    parser.add_argument(
        "--prompt",
        default="What is the weather in London?",
        help="User prompt to send",
    )
    parser.add_argument(
        "--db",
        default="experiment.db",
        help="Path to SQLite experiment database (default: experiment.db)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the LLM provider",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override base URL for the provider API",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum agent loop iterations (default: 10)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    model = args.model or _DEFAULT_MODELS.get(args.provider, "llama3.2")
    server_command = shlex.split(args.server)
    provider = _build_provider(args)

    agent = AgentLoop(
        server_command=server_command,
        provider=provider,
        model=model,
        max_iterations=args.max_iterations,
        db_path=args.db,
    )

    result = asyncio.run(agent.run(args.prompt))

    print("\n=== Final Response ===")
    print(result.final_response)
    print(f"\n=== Iterations: {result.iterations} ===")
    print(f"=== Tool calls: {len(result.tool_calls_made)} ===")
    if result.operator_log:
        print("\n=== Operator Log ===")
        for entry in result.operator_log:
            print(f"  {entry}")


if __name__ == "__main__":
    main()
