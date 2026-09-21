"""Read-only MCP boundary for catalog discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from agentic_data_analyst.bootstrap import build_catalog
from agentic_data_analyst.config import Settings


def create_server(settings: Settings | None = None) -> FastMCP:
    """Expose catalog search and schema lookup as read-only MCP tools."""
    resolved = settings or Settings.from_env()
    catalog = build_catalog(resolved)
    server = FastMCP("agentic-data-analyst-catalog")

    @server.tool()
    def search_catalog(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search logical dataset descriptions without loading every schema."""
        return [item.model_dump() for item in catalog.search(query, limit=min(max(limit, 1), 20))]

    @server.tool()
    def get_dataset_schema(name: str) -> dict[str, Any]:
        """Get the annotated schema for one selected dataset."""
        return catalog.get_dataset(name).model_dump(exclude={"path"})

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
