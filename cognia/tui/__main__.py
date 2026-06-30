"""Entry point: `python -m cognia.tui` arranca la TUI de Cognia."""

from .app import CogniaTUI


def main() -> None:
    CogniaTUI().run()


if __name__ == "__main__":
    main()
