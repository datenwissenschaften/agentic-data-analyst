import asyncio
from pathlib import Path

from agentic_data_analyst.config import Settings
from agentic_data_analyst.mcp.catalog_server import create_server


def test_mcp_exposes_only_read_only_catalog_tools_without_physical_paths(
    sample_data_dir: Path,
) -> None:
    server = create_server(Settings(catalog_path=sample_data_dir))

    async def inspect() -> tuple[set[str], object, object]:
        tools = await server.list_tools()
        search = await server.call_tool("search_catalog", {"query": "session", "limit": 500})
        schema = await server.call_tool("get_dataset_schema", {"name": "sessions"})
        return {tool.name for tool in tools}, search, schema

    names, search, schema = asyncio.run(inspect())

    assert names == {"search_catalog", "get_dataset_schema"}
    assert "sessions" in str(search)
    assert str(sample_data_dir) not in str(schema)
    assert "session_id" in str(schema)
