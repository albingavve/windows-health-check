"""Entrypoint: starts the local dashboard server.

Run with: python -m src.main
"""

import uvicorn


def main() -> None:
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
