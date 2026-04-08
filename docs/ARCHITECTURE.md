# Architecture

## System Overview

The experimental infrastructure consists of five components connected in a pipeline, with SQLite as the shared data store and a web GUI for interactive operation.

```
  +-------------+
  |   Web GUI   |----> Configure & launch experiments
  | (src/gui/)  |<---- Inspect results, analysis, API keys
  +------+------+
         |
  +------v------+
  |   Operator  |
  +------+------+
         |
  +------v------+
  |   Agent     |----> LLM Provider
  |   Loop      |<---- (Anthropic/OpenAI/
  +------+------+       Google/Ollama)
         |
  +------v------+
  |   Proxy     |----> SQLite
  | (logging)   |      (experiment.db)
  +------+------+
         |
  +------v------+
  | Adversarial |
  |  Server     |
  +-------------+
```

## Component Details

### 1. Transparent Proxy (`src/proxy/`)

**Purpose:** Byte-for-byte stdio relay with comprehensive logging. The proxy is the ground truth for what actually happened on the wire.

**Files:**
- `proxy.py` — `TransparentProxy` class. Spawns upstream server via `asyncio.create_subprocess_exec()`. Two concurrent coroutines via `asyncio.gather()` for bidirectional piping. Signal handlers for SIGINT/SIGTERM with graceful shutdown.
- `logger.py` — `ProxyLogger` class. Async SQLite logger with session ID generation, UTC timestamps with microsecond precision. Creates 5 tables (proxy_messages, proxy_tool_schemas, adapter_requests, adapter_responses, schema_version). Schema version tracking (current: v2).
- `parser.py` — JSON-RPC message classification (request/response/notification/error). Supports both single messages and JSON-RPC batch requests (JSON arrays) via `parse_jsonrpc_batch()`. Canonical JSON hashing.
- `hasher.py` — SHA-256 content hashing with JSON canonicalization.

**Invariant:** The proxy MUST NOT modify any message content. This is validated by the transparency test suite.

### 2. Adversarial Servers (`src/servers/`)

**Purpose:** Generate controlled adversarial stimuli for the experiment.

**Files:**
- `config.py` — `InjectionVariant` enum (6 variants: direct, social_engineering, encoded, multistep, benign, context_poison). `InjectionConfig` and `ShadowParamConfig` dataclasses. Pre-defined payloads for all variants.
- `response_injection.py` — FastMCP server for H3. `get_weather` tool returns legitimate data + injection payload. `read_file` tool is the injection target (mock, no real I/O). Variant selected via `INJECTION_VARIANT` environment variable.
- `shadow_params.py` — FastMCP server for H2. `get_weather` tool accepts undeclared `exfil_path` parameter not in inputSchema.
- `control_clean.py` — Clean control (no injection, no shadow params).
- `control_strict.py` — Strict control (validates params against schema, rejects undeclared).
- `echo.py` — Echo server for proxy transparency validation.

### 3. Experiment Client (`src/client/`)

**Purpose:** MCP client that connects to servers, queries LLMs, and logs everything.

**Files:**
- `agent.py` — `AgentLoop` class. Iterative loop: discover tools → query LLM → execute tool calls → feed results back. Configurable timeouts: wall-clock (`max_seconds`), per-query (`query_timeout`), per-tool (`tool_timeout`). Iteration cap (`max_iterations`). Timeouts recorded as data.
- `providers/base.py` — `LLMProvider` protocol with `query()` method. `LLMResponse`, `ToolCall`, `MCPToolSchema` dataclasses.
- `providers/anthropic.py` — Anthropic Messages API adapter.
- `providers/openai_compat.py` — OpenAI/OpenRouter adapter.
- `providers/google.py` — Google Gemini adapter.
- `providers/ollama.py` — Ollama local inference adapter.

Each adapter: translates MCP schemas to provider format, sends HTTP requests, extracts tool calls, logs raw request/response JSON, redacts API keys.

### 4. Analysis Pipeline (`src/analysis/`)

**Purpose:** Post-hoc analysis of experiment databases.

**Files:**
- `events.py` — Four event detectors: `detect_schema_mutations()`, `detect_undeclared_params()`, `detect_injection_patterns()`, `detect_anomalous_calls()`. All async, all query SQLite.
- `compliance.py` — Per-turn classification (`classify_compliance()`) and session-level classification (`classify_session_compliance()`). 4-point scale with escalation detection. Supports `manual_override` for human review.
- `delta.py` — `compute_delta()` compares proxy events (ground truth) to client events (keyword matching). Produces detection rate and observability delta.
- `aggregate.py` — `aggregate_results()` scans directory of experiment.db files, runs full analysis pipeline, exports CSV and JSON summaries.

### 5. Experiment Runner (`experiments/runner.py`)

**Purpose:** Orchestrate experiment batches from JSON configuration files.

- `ExperimentConfig` dataclass with hypothesis, variant, server, provider, model, repetitions, env vars.
- `run_single()` creates output directory, sets env vars, wraps agent run in `asyncio.wait_for()` timeout.
- `run_experiment()` executes all repetitions sequentially.
- `run_batch()` executes multiple experiment configs with progress reporting.

## Database Schema

Single SQLite file per experiment run (`experiment.db`), schema version 2.

| Table | Writer | Columns | Purpose |
|-------|--------|---------|---------|
| `proxy_messages` | Proxy | session_id, timestamp, direction, message_type, method, message_json, content_hash, parse_error | All JSON-RPC traffic |
| `proxy_tool_schemas` | Proxy | session_id, timestamp, tool_name, description, description_hash, input_schema_json, input_schema_hash, list_call_sequence_number | Tool schemas per tools/list call |
| `adapter_requests` | Agent | session_id, timestamp, provider, model, translated_tools_json, request_json | What the LLM was asked |
| `adapter_responses` | Agent | session_id, timestamp, provider, model, response_json, tool_calls_json, compliance_classification, manual_override, iteration_number | What the LLM said |
| `schema_version` | Logger | version | Schema version tracking |

### 6. Web GUI (`src/gui/`)

**Purpose:** Browser-based research dashboard for experiment management, result inspection, and analysis visualisation.

**Stack:** FastAPI + Jinja2 + HTMX + Chart.js. No Node.js — vendored JS assets for offline use.

**Files:**
- `app.py` — FastAPI application factory with Jinja2 template rendering.
- `config.py` — Paths (results dir, prompts dir, key store) and server settings (host, port).
- `routes/dashboard.py` — Dashboard with aggregate compliance stats, recent experiments, donut chart.
- `routes/experiments.py` — Experiment configuration form (hypothesis, variant, provider/model, repetitions) and launch endpoint.
- `routes/results.py` — Results list, run detail with HTMX-loaded tabs (messages, schemas, adapter, events).
- `routes/analysis.py` — Compliance heatmap, detection rate chart, observability delta visualisation.
- `routes/keys.py` — API key management (save, verify, remove) with encrypted storage.
- `routes/sse.py` — Server-Sent Events endpoint for live experiment progress streaming.
- `services/db_service.py` — Read-only paginated queries against per-run SQLite databases.
- `services/experiment_service.py` — Async experiment launch wrapping `experiments/runner.py`.
- `services/analysis_service.py` — Wraps `src/analysis/*` modules for dashboard and chart data.
- `services/key_service.py` — Fernet-encrypted API key storage in `~/.mcp-blindness/keys.json`.
- `templates/` — Jinja2 templates: base shell, component partials, page templates.
- `static/` — CSS design tokens, vendored HTMX + Chart.js, chart initialisation JS, SSE handler.

**Entry point:** `uv run python -m src.gui` → serves at `http://127.0.0.1:8420`.

## Key Design Decisions

1. **Thin adapter layer over LiteLLM**: Each provider adapter is 100-160 LOC. Full control over schema translation and logging. No hidden retries or normalization.
2. **SQLite per run**: No coordination overhead. Trivially shareable. `aiosqlite` for async compatibility.
3. **Failures are data**: No retries, no fallbacks. Timeouts, errors, and null results are recorded and analysed.
4. **Proxy transparency as precondition**: Validated before every experiment batch. If the proxy modifies traffic, all results are invalid.
5. **Schema version tracking**: `schema_version` table prevents silent schema mismatches when analysing databases from different code versions.
6. **GUI as a layer, not a dependency**: The web GUI wraps existing modules (runner, analysis, db schema) without modifying them. All functionality remains accessible via CLI. The GUI adds no changes to core experiment, proxy, or analysis code.
