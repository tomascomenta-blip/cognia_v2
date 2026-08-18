"""Entry point: `python -m cognia.tui` arranca la TUI de Cognia."""

# Piso REAL de textual, el mismo que declara pyproject.toml en las deps duras.
# Medido, no estimado: 0.85.2 muere en "No module named 'textual.theme'" y
# 0.86.0 monta la app entera (el sistema de temas nace en 0.86.0).
TEXTUAL_MINIMO = "0.86.0"


def _version_textual() -> str:
    """Version instalada de textual, o 'no instalado'. Nunca levanta."""
    try:
        from importlib.metadata import version
        return version("textual")
    except Exception:
        return "no instalado"


def _explicar_import_roto(exc: BaseException) -> None:
    """Mensaje humano cuando la TUI no puede importar textual.

    Ya NO dice "pip install cognia-ai[tui]": desde 4.8.x textual es dependencia
    DURA, asi que una instalacion sana siempre lo tiene. Si igual falta o esta
    viejo, la instalacion esta rota (venv a medias, textual pisado por otro
    paquete, pip interrumpido) y el usuario tiene que poder leer QUE pasa.
    """
    print("La TUI de Cognia no pudo cargar 'textual'.")
    print(f"  error real:  {exc}")
    print(f"  instalado:   textual {_version_textual()}")
    print(f"  se necesita: textual >= {TEXTUAL_MINIMO}")
    print("  Es parte del core de cognia-ai, o sea que esta instalacion quedo")
    print("  incompleta. Repararla con:")
    print("      pip install --upgrade --force-reinstall cognia-ai")
    print(f'  o, sin tocar el resto:  pip install "textual>={TEXTUAL_MINIMO}"')


def main() -> None:
    try:
        from cognia.first_run import apply_config
        apply_config()   # config.env instalado (fix auditoria 2026-07-15)
    except Exception:
        pass
    try:
        from .app import CogniaTUI
    except ImportError as e:
        # ModuleNotFoundError (falta textual, o falta textual.theme porque es
        # anterior a 0.86) e ImportError a secas (symbol que ya no existe).
        if "textual" in str(e) or "textual" in str(getattr(e, "name", "") or ""):
            _explicar_import_roto(e)
            raise SystemExit(1)
        raise
    CogniaTUI().run()


if __name__ == "__main__":
    main()
