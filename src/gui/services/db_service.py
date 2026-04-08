"""Read-only SQLite access for experiment databases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from src.gui.config import RESULTS_DIR

PER_PAGE = 50


def _find_db(exp_id: str, run_number: int) -> Path | None:
    """Locate the experiment.db for a given experiment/run."""
    # Try results/{exp_id}/run_{run_number}/experiment.db
    candidate = RESULTS_DIR / exp_id / f"run_{run_number}" / "experiment.db"
    if candidate.exists():
        return candidate
    # Fallback: search recursively
    for db in RESULTS_DIR.rglob("experiment.db"):
        if exp_id in str(db):
            return db
    return None


def _find_config(exp_id: str, run_number: int) -> dict[str, Any]:
    """Load config.json for a given experiment/run."""
    config_path = RESULTS_DIR / exp_id / f"run_{run_number}" / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())  # type: ignore[no-any-return]
    return {}


async def list_experiments(page: int = 1) -> dict[str, Any]:
    """List all experiments with summary info."""
    experiments: list[dict[str, Any]] = []

    if not RESULTS_DIR.exists():
        return {"items": [], "total": 0, "pages": 0}

    # Scan results directory for experiment folders
    exp_dirs = sorted(
        [d for d in RESULTS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    for exp_dir in exp_dirs:
        run_dirs = sorted(
            [r for r in exp_dir.iterdir() if r.is_dir() and r.name.startswith("run_")],
        )
        if not run_dirs:
            continue

        # Load config from the first run
        config_path = run_dirs[0] / "config.json"
        config: dict[str, Any] = {}
        if config_path.exists():
            config = json.loads(config_path.read_text())

        # Try to get compliance from agent_result.json
        compliance = "unknown"
        for rd in run_dirs:
            result_path = rd / "agent_result.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text())
                    if "compliance" in result:
                        compliance = result["compliance"]
                except (json.JSONDecodeError, KeyError):
                    pass

        experiments.append({
            "experiment_id": exp_dir.name,
            "hypothesis": config.get("hypothesis", "unknown"),
            "variant": config.get("variant", "unknown"),
            "provider": config.get("provider", "unknown"),
            "model": config.get("model", "unknown"),
            "runs": len(run_dirs),
            "compliance": compliance,
            "timestamp": exp_dir.stat().st_mtime,
        })

    total = len(experiments)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE

    return {
        "items": experiments[start:end],
        "total": total,
        "pages": pages,
    }


async def get_run_metadata(exp_id: str, run_number: int) -> dict[str, Any]:
    """Load metadata for a specific run."""
    config = _find_config(exp_id, run_number)
    db_path = _find_db(exp_id, run_number)

    meta: dict[str, Any] = {
        "experiment_id": exp_id,
        "run_number": run_number,
        "config": config,
        "hypothesis": config.get("hypothesis", "unknown"),
        "variant": config.get("variant", "unknown"),
        "provider": config.get("provider", "unknown"),
        "model": config.get("model", "unknown"),
        "db_exists": db_path is not None,
        "compliance": "unknown",
    }

    # Try to read agent_result.json
    result_path = RESULTS_DIR / exp_id / f"run_{run_number}" / "agent_result.json"
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text())
            meta["result"] = result
            if "compliance" in result:
                meta["compliance"] = result["compliance"]
        except (json.JSONDecodeError, OSError):
            pass

    # Try to read error.txt
    error_path = RESULTS_DIR / exp_id / f"run_{run_number}" / "error.txt"
    if error_path.exists():
        meta["error"] = error_path.read_text()

    # Get message count and adapter stats from db
    if db_path:
        async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            async with db.execute("SELECT COUNT(*) FROM proxy_messages") as cur:
                row = await cur.fetchone()
                meta["message_count"] = row[0] if row else 0

            async with db.execute("SELECT COUNT(*) FROM adapter_responses") as cur:
                row = await cur.fetchone()
                meta["iteration_count"] = row[0] if row else 0

    return meta


async def get_messages(
    exp_id: str,
    run_number: int,
    page: int = 1,
    direction: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """Get paginated proxy messages for a run."""
    db_path = _find_db(exp_id, run_number)
    if not db_path:
        return {"items": [], "total": 0, "pages": 0}

    conditions: list[str] = []
    params: list[str] = []
    if direction:
        conditions.append("direction = ?")
        params.append(direction)
    if method:
        conditions.append("method = ?")
        params.append(method)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = aiosqlite.Row

        # Count total
        async with db.execute(f"SELECT COUNT(*) FROM proxy_messages {where}", params) as cur:
            row = await cur.fetchone()
            total = row[0] if row else 0

        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        offset = (page - 1) * PER_PAGE

        # Fetch page (list view: no full JSON blob)
        query = f"""
            SELECT id, session_id, timestamp, direction, message_type, method,
                   content_hash, parse_error
            FROM proxy_messages {where}
            ORDER BY id ASC
            LIMIT ? OFFSET ?
        """
        async with db.execute(query, [*params, PER_PAGE, offset]) as cur:
            items = [dict(row) async for row in cur]

    return {"items": items, "total": total, "pages": pages}


async def get_message_detail(exp_id: str, run_number: int, msg_id: int) -> dict[str, Any]:
    """Get full message content for a specific message."""
    db_path = _find_db(exp_id, run_number)
    if not db_path:
        return {}

    async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM proxy_messages WHERE id = ?", [msg_id]) as cur:
            row = await cur.fetchone()
            if row:
                msg = dict(row)
                # Try to pretty-print the JSON
                if msg.get("message_json"):
                    try:
                        parsed = json.loads(msg["message_json"])
                        msg["message_pretty"] = json.dumps(parsed, indent=2)
                    except json.JSONDecodeError:
                        msg["message_pretty"] = msg["message_json"]
                return msg
    return {}


async def get_tool_schemas(exp_id: str, run_number: int) -> list[dict[str, Any]]:
    """Get all tool schemas from a run."""
    db_path = _find_db(exp_id, run_number)
    if not db_path:
        return []

    async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM proxy_tool_schemas ORDER BY list_call_sequence_number, id"
        ) as cur:
            return [dict(row) async for row in cur]


async def get_adapter_pairs(exp_id: str, run_number: int) -> list[dict[str, Any]]:
    """Get adapter request/response pairs for a run."""
    db_path = _find_db(exp_id, run_number)
    if not db_path:
        return []

    pairs: list[dict[str, Any]] = []
    async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM adapter_requests ORDER BY id") as cur:
            requests = [dict(row) async for row in cur]

        async with db.execute("SELECT * FROM adapter_responses ORDER BY id") as cur:
            responses = [dict(row) async for row in cur]

        # Pair them by position (they're logged sequentially)
        for i, req in enumerate(requests):
            pair: dict[str, Any] = {"request": req, "response": None}
            if i < len(responses):
                pair["response"] = responses[i]
                # Pretty-print JSON fields
                for field in ("response_json", "tool_calls_json"):
                    val = pair["response"].get(field)
                    if val:
                        try:
                            pair["response"][f"{field}_pretty"] = json.dumps(
                                json.loads(val), indent=2
                            )
                        except json.JSONDecodeError:
                            pass
            # Pretty-print request JSON
            for field in ("request_json", "translated_tools_json"):
                val = req.get(field)
                if val:
                    try:
                        req[f"{field}_pretty"] = json.dumps(json.loads(val), indent=2)
                    except json.JSONDecodeError:
                        pass
            pairs.append(pair)

    return pairs
