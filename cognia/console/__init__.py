"""
cognia/console/__init__.py
==========================
Infraestructura de consola para el REPL de Cognia:

- proc_registry: registro global de subprocesos en background (/shells)
- monitors:     monitores en background que disparan eventos (/monitores)
- permissions:  modos de permiso automatico/manual/bypass (/modo-permiso)
- surveys:      encuestas interactivas con fallback a input() plano

Sin dependencias pesadas: rich y prompt_toolkit son opcionales (mismo patron
que cognia/cli.py) y todo degrada a texto plano si faltan.
"""
