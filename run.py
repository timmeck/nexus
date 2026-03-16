"""Run the Nexus server."""

import uvicorn

from nexus.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run(
        "nexus.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
    )
