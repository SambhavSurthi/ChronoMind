from fastmcp import FastMCP

mcp = FastMCP("ChronoMind MCP Server")


@mcp.tool()
def health_check() -> dict:
    """Returns server health status."""
    return {"status": "ok"}


if __name__ == "__main__":
    mcp.run(transport="sse")
