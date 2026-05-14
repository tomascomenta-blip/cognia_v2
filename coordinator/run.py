"""Entrypoint para Railway y cognia-coordinator CLI."""
import os
import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT", 8001))
    print(f"Iniciando coordinador en http://0.0.0.0:{port}")
    uvicorn.run("coordinator.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
