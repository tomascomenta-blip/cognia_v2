# -*- coding: utf-8 -*-
"""Self-test del GATE de permisos al arrancar: el allowlist "definido y nunca
cargado" de Hermes (issue #4739) no puede pasar aquí sin que se vea.

Portado como LECCIÓN de hermes-agent (2026-09-04): su allowlist permanente
estuvo meses declarado en config y nunca leído; nadie lo notó porque el gate
"funcionaba" (pedía confirmación de todo). La memoria del repo dice lo mismo
de otra forma: "una lección en prosa no impide nada" y "Cognia degrada en
silencio". Esto es la lección convertida en un chequeo de arranque, como
`backend_activo.chequeo_arranque` lo es para el backend.

Corre en milisegundos, sin modelo, sin tocar el disco, y devuelve una lista de
PROBLEMAS (vacía = todo bien): el sentinel bloquea lo que debe bloquear y
permite lo que debe permitir, las reglas persistentes cargan, `es_destructivo`
sigue reconociendo un borrado, y la lista de comandos interactivos responde.
"""
from __future__ import annotations

# (comando, nivel esperado). Los niveles son los de sentinel: allow/confirm/block.
CASOS_SHELL = (
    ("rm -rf /", "block"),
    ("format c:", "block"),
    ("del /q *.png", "block"),
    ("dir", "allow"),
    ("git status", "allow"),
)


def autotest() -> list[str]:
    """Lista de problemas encontrados en el gate; vacía si todo responde bien."""
    problemas: list[str] = []
    try:
        from cognia.agent import sentinel
        if not sentinel.sentinel_enabled():
            problemas.append("sentinel APAGADO (COGNIA_SENTINEL=0): no hay bloqueo duro de comandos destructivos")
        else:
            for cmd, esperado in CASOS_SHELL:
                try:
                    nivel = sentinel.clasificar_shell(cmd)[0]
                except Exception as exc:
                    problemas.append(f"sentinel.clasificar_shell({cmd!r}) lanzó {type(exc).__name__}: {exc}")
                    continue
                if esperado == "block" and nivel != "block":
                    problemas.append(f"sentinel NO bloquea {cmd!r} (dio {nivel!r}, esperaba block)")
                elif esperado == "allow" and nivel == "block":
                    problemas.append(f"sentinel bloquea un comando de lectura: {cmd!r}")
    except Exception as exc:
        problemas.append(f"sentinel no importable: {type(exc).__name__}: {exc}")
    try:
        from cognia.harness import permisos_reglas as pr
        reglas = pr.cargar_vigentes()
        if reglas is None:
            problemas.append("permisos_reglas.cargar_vigentes() devolvió None: las reglas persistentes NO se cargaron")
        if not pr.es_destructivo("borrar_archivo", "x.py"):
            problemas.append("permisos_reglas.es_destructivo no reconoce borrar_archivo como destructivo")
    except Exception as exc:
        problemas.append(f"permisos_reglas no responde: {type(exc).__name__}: {exc}")
    try:
        from cognia.harness import comandos_interactivos as ci
        if ci.activo() and not ci.motivo_bloqueo("vim x.py"):
            problemas.append("comandos_interactivos no bloquea 'vim': la lista no se cargó")
    except Exception as exc:
        problemas.append(f"comandos_interactivos no responde: {type(exc).__name__}: {exc}")
    return problemas


def resumen() -> str:
    p = autotest()
    if not p:
        return "gate de permisos: OK (sentinel, reglas persistentes, interactivos)"
    return "gate de permisos con problemas:\n  - " + "\n  - ".join(p)


__all__ = ["autotest", "resumen", "CASOS_SHELL"]
