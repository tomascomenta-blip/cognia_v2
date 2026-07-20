"""
cognia_v3_app.py — launcher del REPL de Cognia v3.

El módulo principal vive en cognia_v3/core/cognia_v3.py (migración SESSION 0).
Uso:
    python cognia_v3_app.py
"""

if __name__ == "__main__":
    from cognia_v3.core.cognia_v3 import repl
    repl()
