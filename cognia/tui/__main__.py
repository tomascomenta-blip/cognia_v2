"""Entry point: `python -m cognia.tui` arranca la TUI de Cognia."""


def main() -> None:
    try:
        from cognia.first_run import apply_config
        apply_config()   # config.env instalado (fix auditoria 2026-07-15)
    except Exception:
        pass
    try:
        from .app import CogniaTUI
    except ModuleNotFoundError as e:
        if "textual" in str(e):
            print("La TUI necesita el paquete 'textual' (no viene por "
                  "defecto). Instalalo con:  pip install cognia-ai[tui]")
            raise SystemExit(1)
        raise
    CogniaTUI().run()


if __name__ == "__main__":
    main()
