"""Agent loop for MCP experiment client."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.client.providers.base import LLMProvider, LLMResponse, MCPToolSchema, ToolCall
from src.proxy.logger import ProxyLogger

if TYPE_CHECKING:
    from mcp.types import ListToolsResult

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result of an agent loop execution.

    Attributes:
        final_response: The final text response from the LLM.
        tool_calls_made: All tool calls executed during the loop.
        iterations: Number of loop iterations completed.
        operator_log: Human-readable log of actions taken.
    """

    final_response: str
    tool_calls_made: list[ToolCall] = field(default_factory=list)
    iterations: int = 0
    operator_log: list[str] = field(default_factory=list)
    timed_out: bool = False


class AgentLoop:
    """MCP experiment agent that loops between an LLM and tool execution.

    Connects to an MCP server, discovers tools, and runs an iterative
    loop: query LLM, execute any requested tool calls, feed results back,
    until the LLM produces a final text response or max iterations reached.
    """

    def __init__(
        self,
        server_command: list[str],
        provider: LLMProvider,
        model: str,
        max_iterations: int = 10,
        max_seconds: float = 120.0,
        query_timeout: float = 60.0,
        tool_timeout: float = 30.0,
        db_path: str = "experiment.db",
    ) -> None:
        """Initialise the agent loop.

        Args:
            server_command: Command and arguments to start the MCP server.
            provider: LLM provider adapter instance.
            model: Model identifier to pass to the provider.
            max_iterations: Maximum number of LLM query iterations.
            max_seconds: Wall-clock timeout for the entire run.
            query_timeout: Timeout in seconds for a single LLM query.
            tool_timeout: Timeout in seconds for a single tool call.
            db_path: Path to the SQLite experiment database.
        """
        self._server_command = server_command
        self._provider = provider
        self._model = model
        self._max_iterations = max_iterations
        self._max_seconds = max_seconds
        self._query_timeout = query_timeout
        self._tool_timeout = tool_timeout
        self._db_path = db_path

    @staticmethod
    def _tools_to_schemas(
        tools_result: ListToolsResult,
    ) -> list[MCPToolSchema]:
        """Convert MCP tools/list result to MCPToolSchema list.

        Args:
            tools_result: The result from session.list_tools().

        Returns:
            List of MCPToolSchema dataclass instances.
        """
        schemas: list[MCPToolSchema] = []
        for tool in tools_result.tools:
            schemas.append(
                MCPToolSchema(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if tool.inputSchema else {},
                ),
            )
        return schemas

    async def _log_to_db(
        self,
        db_logger: ProxyLogger,
        llm_response: LLMResponse,
        iteration: int,
    ) -> None:
        """Log adapter request and response to the database.

        Args:
            db_logger: The ProxyLogger instance for database writes.
            llm_response: The LLM response containing raw JSON to log.
            iteration: The current agent loop iteration number.
        """
        await db_logger.log_adapter_request(
            provider=self._provider.provider_name,
            model=self._model,
            translated_tools=llm_response.translated_tools_json,
            request_json=llm_response.raw_request_json,
        )
        tool_calls_json: str | None = None
        if llm_response.tool_calls:
            tool_calls_json = json.dumps(
                [
                    {"name": tc.tool_name, "arguments": tc.arguments}
                    for tc in llm_response.tool_calls
                ],
                indent=2,
            )
        await db_logger.log_adapter_response(
            provider=self._provider.provider_name,
            model=self._model,
            response_json=llm_response.raw_response_json,
            tool_calls_json=tool_calls_json,
            classification=None,
            iteration_number=iteration,
        )

    async def run(self, user_prompt: str) -> AgentResult:
        """Execute the agent loop with the given user prompt.

        Connects to the MCP server, discovers available tools, and
        iteratively queries the LLM and executes tool calls until the
        LLM produces a final response or max iterations are exhausted.

        Args:
            user_prompt: The initial user message to send.

        Returns:
            AgentResult with the final response, tool calls, and logs.
        """
        server_params = StdioServerParameters(
            command=self._server_command[0],
            args=self._server_command[1:],
        )

        result = AgentResult(final_response="")

        async with (
            ProxyLogger(self._db_path) as db_logger,
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()

            tools_result = await session.list_tools()
            mcp_tools = self._tools_to_schemas(tools_result)
            logger.info(
                "Discovered %d tools: %s",
                len(mcp_tools),
                [t.name for t in mcp_tools],
            )

            messages: list[dict[str, Any]] = [
                {"role": "user", "content": user_prompt},
            ]

            deadline = time.monotonic() + self._max_seconds

            for iteration in range(1, self._max_iterations + 1):
                if time.monotonic() >= deadline:  # pragma: no cover
                    result.final_response = (
                        f"Wall-clock timeout ({self._max_seconds}s) reached"
                    )
                    result.timed_out = True
                    break

                result.iterations = iteration
                logger.info("Iteration %d", iteration)

                try:
                    llm_response = await asyncio.wait_for(
                        self._provider.query(
                            messages=messages,
                            tools=mcp_tools,
                            model=self._model,
                        ),
                        timeout=self._query_timeout,
                    )
                except TimeoutError:
                    result.final_response = (
                        f"LLM query timeout ({self._query_timeout}s) at iteration {iteration}"
                    )
                    result.timed_out = True
                    break

                await self._log_to_db(db_logger, llm_response, iteration)

                if not llm_response.tool_calls:
                    result.final_response = llm_response.content
                    break

                messages.append(
                    {
                        "role": "assistant",
                        "content": llm_response.content,
                        "tool_calls": [
                            {
                                "name": tc.tool_name,
                                "arguments": tc.arguments,
                            }
                            for tc in llm_response.tool_calls
                        ],
                    },
                )

                for tc in llm_response.tool_calls:
                    result.tool_calls_made.append(tc)
                    logger.info(
                        "Calling tool: %s(%s)",
                        tc.tool_name,
                        json.dumps(tc.arguments),
                    )

                    try:
                        tool_result = await asyncio.wait_for(
                            session.call_tool(
                                tc.tool_name,
                                tc.arguments,
                            ),
                            timeout=self._tool_timeout,
                        )
                    except TimeoutError:  # pragma: no cover
                        result_text = f"[TIMEOUT] Tool call timed out after {self._tool_timeout}s"
                        result.operator_log.append(
                            f"tool={tc.tool_name} args={json.dumps(tc.arguments)} "
                            f"result={result_text}"
                        )
                        logger.warning("Tool call timed out: %s", tc.tool_name)
                        messages.append(
                            {
                                "role": "tool",
                                "content": result_text,
                                "tool_name": tc.tool_name,
                            },
                        )
                        continue

                    result_text = ""
                    if tool_result.content:
                        result_text = " ".join(
                            getattr(c, "text", str(c)) for c in tool_result.content
                        )

                    log_entry = (
                        f"tool={tc.tool_name} "
                        f"args={json.dumps(tc.arguments)} "
                        f"result={result_text[:200]}"
                    )
                    result.operator_log.append(log_entry)
                    logger.info("Result: %s", result_text[:200])

                    messages.append(
                        {
                            "role": "tool",
                            "content": result_text,
                            "tool_name": tc.tool_name,
                        },
                    )
            else:
                result.final_response = f"Max iterations ({self._max_iterations}) reached"

        return result
