# -*- coding: utf-8 -*-
"""Parada verificada: nadie declara terminada una tarea que EDITO CODIGO sin evidencia fresca.

QUE RESUELVE
    El cierre mas caro del agente es el que MIENTE: escribe un .py, no lo corre, y contesta
    "listo, funciona". Este modulo es la compuerta de salida. Cuando el turno toco codigo y
    NO hay evidencia fresca de verificacion, devuelve el TEXTO de un nudge sintetico para
    inyectar como mensaje de usuario; el modelo gasta un turno mas corriendo la prueba real.
    Cuando la evidencia esta, o cuando solo se toco prosa, devuelve None y deja salir.

POR QUE EXISTE (y por que es POLITICA PURA)
    El repo ya tiene el musculo de verificar (`cognia/harness/verificacion.py` corre pytest
    tras una edicion; la tool `tests` corre pytest a pedido) pero NO tiene el juez que decide
    si el cierre esta permitido. Este modulo NUNCA ejecuta nada: no lanza pytest, no abre
    subprocesos, no toca el codigo del usuario. Solo lee un ledger y decide. Esa separacion
    es literal en Hermes ("This module is intentionally policy-only. It never runs checks
    itself" -- verification_stop.py:3-6) y es la que permite testearlo sin modelo ni red.

DESTILADO DE (leidos de C:/Users/usuario/AppData/Local/hermes/hermes-agent, no imaginados)
    agent/verification_stop.py (entero)
        - _NON_CODE_VERIFY_EXTENSIONS / _NON_CODE_VERIFY_FILENAMES + _filter_verifiable_paths:
          el filtro de prosa. Comentario original: "this is fix 'C' for the doc/markdown/skill
          false-positive -- a SKILL.md or README edit must never demand a /tmp verification
          script".
        - build_verify_on_stop_nudge(..., attempts=0, max_attempts=2): el tope de 2 intentos.
        - _MAX_CHANGED_PATHS_IN_NUDGE = 8: cuantas rutas entran en el texto.
        - _session_is_messaging_surface()/verify_on_stop_enabled(): la compuerta por SUPERFICIE
          (ON en CLI/TUI/programatico, OFF en Telegram/Discord/Slack, donde la narracion de la
          verificacion le llega a un humano como ruido de chat).
        - El texto del nudge: estado + rutas + instruccion CONCRETA (los verifyCommands del
          proyecto, no "verifica tu trabajo") + la valvula "si no podes verificar, deci el
          bloqueo concreto en vez de declararlo verificado".
    agent/verification_evidence.py:580 verification_status
        - La regla de FRESCURA, textual: `if state["last_edit_at"] > evidence["created_at"]:
          status = "stale"`. Evidencia ANTERIOR a la edicion no vale: eso es lo que aca
          implementa `estado_verificacion(workspace, desde_ts)`.
        - Los estados: not_applicable / unverified / stale / <status del evento>. Solo "passed"
          deja salir (verification_stop.py: `if state == "passed": return None`).
        - La rotacion: _MAX_EVIDENCE_AGE_DAYS=30 y _MAX_EVENTS_PER_SESSION_ROOT=100.
    agent/conversation_loop.py:6844-6902 (el cableado)
        - El nudge se marca `"_verification_stop_synthetic": True` para excluirlo del historial
          persistido ("Only the nudge is flagged synthetic so it gets stripped from the durable
          transcript"). Aca es la clave `sintetico` de `decidir_detallado()`.
        - La respuesta que el modelo YA compuso se guarda (`_pending_verification_response`)
          ANTES de poner `final_response = None`.
    agent/turn_finalizer.py:100-124 (el rescate)
        - "A verification/continuation gate deliberately withheld a composed answer, then
          consumed the remaining budget before producing a newer one. Preserve that exact
          answer instead of replacing it with another fallible model call." Ese es el motivo
          de `rescatar_respuesta_pendiente()`: sin el, el nudge PIERDE la respuesta del modelo
          si el presupuesto se agota justo despues.

DIFERENCIAS DELIBERADAS CON HERMES
    - Hermes guarda el ledger en SQLite (verification_evidence.db, WAL, esquema con 2 tablas).
      Aca es un JSON unico con lock (~/.cognia/evidencia_verificacion.json): el volumen es de
      decenas de eventos por sesion y el repo ya resuelve asi sus almacenes chicos
      (cognia/harness/checkpoints.py). El lock (msvcrt/fcntl) es el mismo patron que
      cognia/backend_activo.py:35-45, que existe porque dos Cognias abiertos entrelazaban
      escrituras.
    - El comando sugerido nombra el INTERPRETE del proyecto (venv312/Scripts/python.exe -m
      pytest) y no `pytest` pelado: en esta maquina `python` pelado resuelve al venv de Hermes
      y da fallos fantasma. Una sugerencia que no corre no es concreta.

NO LANZA NUNCA. Todas las publicas devuelven un valor tambien en el peor caso: una compuerta
que revienta mata el turno que venia a proteger.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

try:                                  # Windows
    import msvcrt
except ImportError:                   # pragma: no cover - depende del SO
    msvcrt = None
try:                                  # POSIX
    import fcntl
except ImportError:                   # pragma: no cover - depende del SO
    fcntl = None


# -- Constantes de politica ---------------------------------------------------

# Tope de nudges por turno. Hermes usa max_attempts=2 en build_verify_on_stop_nudge
# (verification_stop.py) y lo cuenta en agent._verification_stop_nudges. DOS y no mas
# porque cada nudge cuesta un turno ENTERO del modelo: al tercero o bien el modelo ya
# dijo que no puede verificar (y repetirselo no cambia nada) o esta en bucle, y el
# presupuesto que se come es el mismo que necesita para RESPONDER. El tope convierte
# la compuerta en un empujon acotado en vez de un lazo infinito.
MAX_NUDGES = 2

# Cuantas rutas entran en el texto del nudge (Hermes: _MAX_CHANGED_PATHS_IN_NUDGE = 8).
# Mas que eso es prompt gastado: el modelo ya sabe que edito.
_MAX_RUTAS_EN_NUDGE = 8

# Extensiones de PROSA: documentacion y datos que ningun test/build ejercita. Un turno que
# toca SOLO esto no tiene nada que verificar y exigirle una prueba es ruido puro (el
# false-positive del README/SKILL.md que Hermes arreglo con este mismo filtro).
_EXT_PROSA = frozenset({
    ".md", ".markdown", ".mdx", ".rst", ".txt", ".text", ".adoc", ".asciidoc",
    ".org", ".log", ".csv", ".tsv",
})

# Ficheros de prosa SIN extension reconocible.
_NOMBRES_PROSA = frozenset({
    "license", "licence", "notice", "authors", "contributors", "changelog", "codeowners",
})

# .json es AMBIGUO: package.json o tsconfig.json son configuracion viva (un typo rompe el
# build) mientras que un dataset o un fixture es prosa. Se tratan como prosa SALVO estos
# nombres, que si cambian el comportamiento del proyecto.
_JSON_QUE_ES_CODIGO = frozenset({
    "package.json", "tsconfig.json", "jsconfig.json", "composer.json", "deno.json",
    "angular.json", "nest-cli.json", "manifest.json",
})

# Superficies donde la compuerta se APAGA: la narracion de la verificacion le llega a un
# humano como ruido de chat (Hermes: verify_on_stop "auto" = ON en CLI/TUI/programatico,
# OFF en mensajeria). En Cognia la lista incluye el canal del movil.
_SUPERFICIES_SILENCIOSAS = frozenset({
    "telegram", "discord", "slack", "whatsapp", "movil", "mobile", "sms", "voz", "voice",
})

# Rotacion del ledger (Hermes: 30 dias y 100 eventos por sesion/raiz).
_MAX_EVENTOS = 400
_MAX_DIAS = 30

# Comandos que CUENTAN como verificacion cuando el agente los corre con la tool `ejecutar`.
_PALABRAS_VERIFICACION = (
    "pytest", "unittest", "nose", "tox", "npm test", "npm run test", "yarn test",
    "pnpm test", "bun test", "jest", "vitest", "mocha", "go test", "cargo test",
    "cargo check", "cargo clippy", "make test", "make check", "make lint", "make build",
    "ruff", "flake8", "pylint", "mypy", "pyright", "eslint", "tsc", "run_tests",
)

_MAX_SALIDA = 1200      # recorte de la salida guardada (Hermes recorta a 1200 en el nudge)


# -- Ledger de evidencia ------------------------------------------------------

def ruta_ledger() -> Path:
    """Fichero del ledger. COGNIA_EVIDENCIA_VERIFICACION permite override (tests)."""
    override = os.environ.get("COGNIA_EVIDENCIA_VERIFICACION", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cognia" / "evidencia_verificacion.json"


def _clave_workspace(ruta) -> str:
    """Clave estable de un workspace. En Windows el case no distingue dos rutas iguales."""
    try:
        p = Path(ruta or ".").expanduser().resolve()
    except Exception:
        return str(ruta or "")
    s = str(p)
    return s.lower() if os.name == "nt" else s


class _Lock:
    """Lock de fichero (mismo patron que cognia/backend_activo.py:285-306).

    Existe porque dos Cognias abiertos a la vez entrelazaban los appends y el JSON quedaba
    corrupto. Si el SO no ofrece ninguno de los dos mecanismos, degrada a no-op: perder la
    exclusion es malo, romper el turno por no poder lockear es peor.
    """

    def __init__(self, ruta: Path):
        self._ruta = Path(str(ruta) + ".lock")
        self._fh = None

    def __enter__(self):
        try:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._ruta, "a+b")
            if msvcrt is not None:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            elif fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            self._fh = None
        return self

    def __exit__(self, *exc):
        fh, self._fh = self._fh, None
        if fh is None:
            return False
        try:
            if msvcrt is not None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
        return False


def _leer_ledger(ruta: Path) -> list:
    """Eventos del ledger, en orden de registro. Un fichero ausente o corrupto -> []."""
    try:
        crudo = ruta.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    try:
        dato = json.loads(crudo)
    except ValueError:
        # Corrupto (disco lleno a mitad de escritura, por ejemplo). Perder el historial de
        # evidencia solo cuesta un nudge de mas; propagar el error mataria el turno.
        return []
    eventos = dato.get("eventos") if isinstance(dato, dict) else dato
    return [e for e in (eventos or []) if isinstance(e, dict)]


def _rotar(eventos: list) -> list:
    """Rotacion simple: fuera lo mas viejo que _MAX_DIAS y cota dura de _MAX_EVENTOS."""
    corte = time.time() - _MAX_DIAS * 86400.0
    vivos = []
    for e in eventos:
        try:
            if float(e.get("ts") or 0.0) >= corte:
                vivos.append(e)
        except (TypeError, ValueError):
            continue
    return vivos[-_MAX_EVENTOS:]


def _escribir_ledger(ruta: Path, eventos: list) -> bool:
    """Escritura atomica (tmp + replace): un corte a mitad no deja el JSON a medias."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_name(ruta.name + ".tmp")
        cuerpo = json.dumps({"version": 1, "eventos": eventos}, ensure_ascii=False, indent=1)
        tmp.write_text(cuerpo, encoding="utf-8")
        os.replace(str(tmp), str(ruta))
        return True
    except OSError:
        return False


def registrar_verificacion(ruta_workspace, comando: str, exito: bool,
                           salida_corta: str = "") -> dict:
    """Anota UN comando de verificacion ya corrido. Es el unico escritor del ledger.

    Este modulo no corre nada: el que ejecuta (la tool `tests`, la tool `ejecutar`, el
    auto-test de cognia/harness/verificacion.py) llama aca DESPUES, con el resultado real.

    Devuelve el evento guardado (con "guardado": bool). Nunca lanza.
    """
    evento = {
        "ts": time.time(),
        "iso": datetime.now().isoformat(timespec="seconds"),
        "workspace": _clave_workspace(ruta_workspace),
        "comando": str(comando or "")[:400],
        "exito": bool(exito),
        "salida": str(salida_corta or "")[:_MAX_SALIDA],
        "pid": os.getpid(),
    }
    ruta = ruta_ledger()
    try:
        with _Lock(ruta):
            eventos = _leer_ledger(ruta)
            eventos.append(evento)
            ok = _escribir_ledger(ruta, _rotar(eventos))
    except Exception:
        ok = False
    evento["guardado"] = bool(ok)
    return evento


def estado_verificacion(workspace, desde_ts=None) -> dict:
    """Estado de la evidencia de `workspace`, contra el instante `desde_ts`.

    `desde_ts` es el epoch de la PRIMERA edicion del turno. La regla es la de Hermes
    (verification_evidence.py:637: si last_edit_at > evidence.created_at el estado es
    "stale"): evidencia anterior a la edicion NO vale, porque probo el codigo de antes.

    Devuelve {"estado", "evento", "comando", "salida", "ts"} con estado en:
        "fresca"        -> hay un exito POSTERIOR a la edicion: se puede cerrar
        "fallida"       -> corrio despues de editar y FALLO: hay que arreglar, no cerrar
        "rancia"        -> solo hay evidencia ANTERIOR a la edicion
        "sin_evidencia" -> el workspace nunca se verifico
    Con `desde_ts=None` cualquier exito registrado cuenta como fresco (sin instante de
    referencia no hay nada contra que medir la frescura).
    """
    clave = _clave_workspace(workspace)
    try:
        eventos = [e for e in _leer_ledger(ruta_ledger()) if e.get("workspace") == clave]
    except Exception:
        eventos = []
    if not eventos:
        return {"estado": "sin_evidencia", "evento": None, "comando": "", "salida": "", "ts": 0.0}

    if desde_ts is None:
        posteriores = eventos
    else:
        try:
            corte = float(desde_ts)
        except (TypeError, ValueError):
            corte = 0.0
        posteriores = [e for e in eventos if float(e.get("ts") or 0.0) >= corte]

    if not posteriores:
        ultimo = eventos[-1]
        return {"estado": "rancia", "evento": ultimo,
                "comando": str(ultimo.get("comando") or ""),
                "salida": str(ultimo.get("salida") or ""),
                "ts": float(ultimo.get("ts") or 0.0)}

    # Un exito POSTERIOR a la edicion basta aunque despues haya un fallo de otra cosa: lo
    # que se exige es prueba de que el codigo editado paso, no que el repo entero este
    # verde (Hermes tampoco asciende un check dirigido a "repo green").
    exitos = [e for e in posteriores if e.get("exito")]
    elegido = exitos[-1] if exitos else posteriores[-1]
    return {"estado": "fresca" if exitos else "fallida", "evento": elegido,
            "comando": str(elegido.get("comando") or ""),
            "salida": str(elegido.get("salida") or ""),
            "ts": float(elegido.get("ts") or 0.0)}


# -- Filtro de prosa ----------------------------------------------------------

def es_prosa(ruta) -> bool:
    """True si la ruta es documentacion/datos: editarla no cambia comportamiento verificable."""
    try:
        p = Path(str(ruta))
    except Exception:
        return False
    suf = p.suffix.lower()
    nombre = p.name.lower()
    if suf == ".json":
        return nombre not in _JSON_QUE_ES_CODIGO
    if suf in _EXT_PROSA:
        return True
    if not suf and nombre in _NOMBRES_PROSA:
        return True
    return False


def filtrar_verificables(rutas) -> list:
    """Deja solo las rutas con comportamiento verificable, ordenadas y sin repetidos."""
    vistas = []
    for r in (rutas or []):
        s = str(r or "").strip()
        if s and not es_prosa(s) and s not in vistas:
            vistas.append(s)
    return sorted(vistas)


# -- Deteccion del comando canonico del proyecto ------------------------------

def _leer_chico(ruta: Path, limite: int = 20000) -> str:
    try:
        return ruta.read_bytes()[:limite].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _python_del_proyecto(raiz: Path) -> str:
    """Interprete del proyecto, relativo a la raiz, o 'python' si no hay venv.

    Nombrar el interprete NO es cosmetico: en esta maquina `python` pelado resuelve a otro
    venv del PATH y la corrida da fallos fantasma que no son del codigo. Una sugerencia que
    no corre no es una sugerencia concreta.
    """
    candidatos = (
        "venv312/Scripts/python.exe", ".venv/Scripts/python.exe", "venv/Scripts/python.exe",
        ".venv/bin/python", "venv/bin/python",
    )
    for rel in candidatos:
        try:
            if (raiz / rel).is_file():
                return rel
        except OSError:
            continue
    return "python"


def raiz_proyecto(inicio=None, tope: int = 6):
    """Sube desde `inicio` buscando el marcador de raiz (pytest.ini/pyproject/.git/...).

    Sin esto la deteccion mira el directorio del fichero editado (cognia/hermes/) y no
    encuentra el pytest.ini del repo, que es exactamente el caso comun.
    """
    marcadores = ("pytest.ini", "pyproject.toml", "setup.cfg", "package.json",
                  "Makefile", "Cargo.toml", "go.mod", ".git")
    try:
        p = Path(inicio or Path.cwd()).expanduser().resolve()
    except Exception:
        return Path.cwd()
    if p.is_file():
        p = p.parent
    actual = p
    for _ in range(max(1, tope)):
        try:
            if any((actual / m).exists() for m in marcadores):
                return actual
        except OSError:
            pass
        if actual.parent == actual:
            break
        actual = actual.parent
    return p


def comandos_canonicos(raiz=None) -> list:
    """Comandos de verificacion DECLARADOS por el proyecto, el mas probable primero.

    Portado de hermes-agent/agent/coding_context.py:781-816 (detect_project_facts): mismos
    marcadores (scripts/run_tests.sh, scripts de package.json, pytest.ini/[tool.pytest,
    targets del Makefile), con el interprete del venv delante del pytest.
    """
    try:
        raiz = Path(raiz or Path.cwd()).expanduser()
    except Exception:
        return []
    cmds = []
    try:
        if (raiz / "scripts" / "run_tests.sh").is_file():
            cmds.append("bash scripts/run_tests.sh")
        pkg = raiz / "package.json"
        if pkg.is_file():
            try:
                scripts = (json.loads(_leer_chico(pkg) or "{}") or {}).get("scripts") or {}
            except (ValueError, AttributeError):
                scripts = {}
            gestor = "npm"
            for lock, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                             ("bun.lockb", "bun")):
                if (raiz / lock).is_file():
                    gestor = pm
                    break
            for nombre in ("test", "lint", "typecheck", "build", "check"):
                if nombre in scripts:
                    cmds.append(f"{gestor} run {nombre}")
        hay_pytest = (raiz / "pytest.ini").is_file()
        if not hay_pytest:
            hay_pytest = "[tool.pytest" in _leer_chico(raiz / "pyproject.toml")
        if not hay_pytest:
            hay_pytest = "[tool:pytest]" in _leer_chico(raiz / "setup.cfg")
        if hay_pytest:
            cmds.append(f"{_python_del_proyecto(raiz)} -m pytest")
        makefile = _leer_chico(raiz / "Makefile")
        if makefile:
            for nombre in ("test", "check", "lint", "build"):
                if re.search(rf"^{re.escape(nombre)}\s*:", makefile, re.MULTILINE):
                    cmds.append(f"make {nombre}")
    except OSError:
        pass
    # dict.fromkeys: sin repetidos y conservando el orden de deteccion.
    return list(dict.fromkeys(cmds))[:5]


def _test_asociado(ruta, raiz: Path):
    """Test que le corresponde al fichero editado, si existe en disco.

    La sugerencia buena no es "corre la suite" (minutos) sino "corre ESTE fichero": el repo
    mide que nombrar la accion concreta desvia al modelo y la generica no.
    """
    try:
        p = Path(str(ruta))
        tallo = p.stem
        if not tallo:
            return None
        if tallo.startswith("test_"):
            # El propio fichero editado ES el test: se corre el.
            return str(ruta)
        candidatos = [
            raiz / "tests" / f"test_{tallo}.py",
            p.parent / f"test_{tallo}.py",
            raiz / "tests" / p.parent.name / f"test_{tallo}.py",
        ]
        for c in candidatos:
            if c.is_file():
                try:
                    return c.resolve().relative_to(raiz.resolve()).as_posix()
                except (ValueError, OSError):
                    return str(c)
    except (OSError, ValueError):
        return None
    return None


def plan_verificacion(ficheros, raiz=None, comandos=None) -> dict:
    """Que correr exactamente para verificar `ficheros`.

    Devuelve {"comando", "tests_existentes", "tests_a_crear"}.

    `tests_a_crear` es el caso que el eyeball destapo: si un .py editado NO tiene test que
    lo cubra, el comando canonico degrada a `pytest` PELADO, o sea "corre los 612 ficheros
    de la suite" -- minutos de espera y exactamente la vaguedad que este modulo viene a
    matar. Cuando pasa eso se nombra el test que FALTA (tests/test_<modulo>.py) y el nudge
    pide escribirlo, que ademas es la regla 5 del CLAUDE.md del repo (un test de regresion
    por cada bug/feature).
    """
    plan = {"comando": "", "tests_existentes": [], "tests_a_crear": []}
    try:
        raiz = raiz_proyecto(raiz or Path.cwd())
        cmds = [str(c).strip() for c in (list(comandos) if comandos else comandos_canonicos(raiz))
                if str(c).strip()]
        if not cmds:
            return plan
        base = cmds[0]
        plan["comando"] = base
        if "pytest" not in base:
            return plan
        for f in (ficheros or []):
            t = _test_asociado(f, raiz)
            if t:
                if t not in plan["tests_existentes"]:
                    plan["tests_existentes"].append(t)
                continue
            p = Path(str(f))
            if p.suffix.lower() in (".py", ".pyi"):
                falta = f"tests/test_{p.stem}.py"
                if falta not in plan["tests_a_crear"]:
                    plan["tests_a_crear"].append(falta)
        if plan["tests_existentes"]:
            plan["comando"] = f"{base} {' '.join(plan['tests_existentes'][:3])} -q"
        elif plan["tests_a_crear"]:
            plan["comando"] = f"{base} {plan['tests_a_crear'][0]} -q"
        return plan
    except Exception:
        return plan


def comando_sugerido(ficheros, raiz=None, comandos=None) -> str:
    """UNA linea de comando concreta para verificar `ficheros`. "" si no hay ninguna."""
    return plan_verificacion(ficheros, raiz, comandos).get("comando", "")


# -- Compuerta por superficie -------------------------------------------------

def compuerta_activa(superficie=None) -> bool:
    """Si la parada verificada corre en esta superficie.

    Precedencia identica a Hermes verify_on_stop_enabled(): la env var manda, despues el
    valor explicito, y el default es "auto" = ON salvo en mensajeria.
    """
    env = os.environ.get("COGNIA_VERIFICAR_AL_CERRAR")
    if env is not None:
        token = env.strip().lower()
        if token in ("0", "false", "no", "off"):
            return False
        if token in ("1", "true", "yes", "on"):
            return True
    s = str(superficie or "").strip().lower()
    return s not in _SUPERFICIES_SILENCIOSAS


# -- La decision --------------------------------------------------------------

def _detalle_estado(ev) -> str:
    est = str((ev or {}).get("estado") or "sin_evidencia")
    humano = {
        "sin_evidencia": "sin evidencia: este workspace no registro ninguna verificacion",
        "rancia": "RANCIA: la ultima verificacion es ANTERIOR a tu edicion (probo el codigo viejo)",
        "fallida": "FALLIDA: la verificacion corrio despues de editar y NO paso",
    }.get(est, est)
    partes = [humano]
    cmd = str((ev or {}).get("comando") or "").strip()
    if cmd:
        partes.append(f"ultimo comando: `{cmd}`")
    salida = str((ev or {}).get("salida") or "").strip()
    if salida:
        partes.append("ultima salida:\n" + salida[:_MAX_SALIDA])
    return "\n".join(partes)


def _lista_rutas(rutas: list) -> str:
    mostradas = rutas[:_MAX_RUTAS_EN_NUDGE]
    lineas = [f"- `{r}`" for r in mostradas]
    resto = len(rutas) - len(mostradas)
    if resto > 0:
        lineas.append(f"- ... y {resto} mas")
    return "\n".join(lineas)


def _normalizar_evidencia(bruta, workspace, desde_ts) -> dict:
    """Acepta la evidencia YA calculada por el caller, o la consulta en el ledger.

    Formas aceptadas: dict con clave "estado" (lo que devuelve estado_verificacion), lista
    de eventos crudos, o None/ausente -> se consulta el ledger. La lista existe para que un
    caller que ya tiene los eventos en RAM (tests, sub-agente) no pase por disco.
    """
    if isinstance(bruta, dict) and bruta.get("estado"):
        return bruta
    if isinstance(bruta, (list, tuple)):
        eventos = [e for e in bruta if isinstance(e, dict)]
        if not eventos:
            return {"estado": "sin_evidencia", "evento": None, "comando": "", "salida": ""}
        try:
            corte = float(desde_ts) if desde_ts is not None else None
        except (TypeError, ValueError):
            corte = None
        posteriores = [e for e in eventos
                       if corte is None or float(e.get("ts") or 0.0) >= corte]
        if not posteriores:
            ultimo = eventos[-1]
            return {"estado": "rancia", "evento": ultimo,
                    "comando": str(ultimo.get("comando") or ""),
                    "salida": str(ultimo.get("salida") or "")}
        exitos = [e for e in posteriores if e.get("exito")]
        elegido = exitos[-1] if exitos else posteriores[-1]
        return {"estado": "fresca" if exitos else "fallida", "evento": elegido,
                "comando": str(elegido.get("comando") or ""),
                "salida": str(elegido.get("salida") or "")}
    return estado_verificacion(workspace, desde_ts)


def decidir_detallado(estado) -> dict:
    """La decision completa, con el porque. `decidir()` es la vista corta de esto.

    `estado` (dict; todas las claves son opcionales salvo ficheros_editados):
        ficheros_editados     rutas tocadas en el turno (la prosa entra: aca se filtra)
        evidencia             None -> se consulta el ledger; dict/lista -> se usa lo que traiga
        comandos_verificacion None -> se detectan del proyecto; lista -> se usa esa
        nudges_usados         cuantos nudges ya se inyectaron en ESTE turno (int)
        superficie            "cli"/"tui"/"api"/"telegram"/... (mensajeria apaga la compuerta)
        workspace             raiz del proyecto (default: cwd)
        ts_primera_edicion    epoch de la primera edicion del turno; sin esto la frescura no
                              se puede juzgar y cualquier exito registrado vale

    Devuelve SIEMPRE un dict:
        {"nudge": str|None, "sintetico": True, "motivo": str, "estado_evidencia": str,
         "ficheros": [...], "comando_sugerido": str, "tests_a_crear": [...],
         "nudges_usados": int}
    `motivo` en: falta_verificacion | evidencia_fresca | solo_prosa | sin_ediciones |
    tope_nudges | superficie_silenciosa | error_interno.

    `sintetico` es True siempre: si hay nudge, el cableado tiene que marcar ese mensaje como
    sintetico para EXCLUIRLO del historial persistido (conversation_loop.py:6874 pone
    "_verification_stop_synthetic": True por eso mismo). Un nudge que queda en el transcript
    contamina los turnos siguientes con una orden que ya se cumplio.
    """
    try:
        estado = estado if isinstance(estado, dict) else {}
        try:
            nudges = int(estado.get("nudges_usados") or 0)
        except (TypeError, ValueError):
            nudges = 0
        base = {"nudge": None, "sintetico": True, "motivo": "", "estado_evidencia": "",
                "ficheros": [], "comando_sugerido": "", "tests_a_crear": [],
                "nudges_usados": nudges}

        if not compuerta_activa(estado.get("superficie")):
            base["motivo"] = "superficie_silenciosa"
            return base

        crudas = list(estado.get("ficheros_editados") or [])
        ficheros = filtrar_verificables(crudas)
        base["ficheros"] = ficheros
        if not ficheros:
            base["motivo"] = "solo_prosa" if crudas else "sin_ediciones"
            return base

        # El tope se mira DESPUES del filtro y ANTES de tocar el disco: cuando ya se
        # gastaron los 2 nudges no hay decision que tomar, y leer el ledger seria trabajo
        # tirado en el camino caliente.
        if nudges >= MAX_NUDGES:
            base["motivo"] = "tope_nudges"
            return base

        ws = estado.get("workspace") or Path.cwd()
        ev = _normalizar_evidencia(estado.get("evidencia"), ws,
                                   estado.get("ts_primera_edicion"))
        base["estado_evidencia"] = str(ev.get("estado") or "sin_evidencia")
        if base["estado_evidencia"] == "fresca":
            base["motivo"] = "evidencia_fresca"
            return base

        raiz = raiz_proyecto(estado.get("workspace") or ficheros[0])
        plan = plan_verificacion(ficheros, raiz, estado.get("comandos_verificacion"))
        sugerido = plan.get("comando") or ""
        base["comando_sugerido"] = sugerido
        base["tests_a_crear"] = list(plan.get("tests_a_crear") or [])

        if sugerido and base["tests_a_crear"] and not plan.get("tests_existentes"):
            # No existe ningun test que cubra lo editado: mandarlo a correr la suite
            # entera seria "verifica tu trabajo" con otro nombre.
            faltante = base["tests_a_crear"][0]
            instruccion = (
                f"NO existe ningun test que cubra lo que editaste. Escribi `{faltante}` con un "
                "caso que FALLE sin tu cambio y pase con el, y despues corre AHORA: "
                f"`{sugerido}`\n"
                "Cerra con responder INCLUYENDO la salida REAL (el conteo de pytest, no un "
                "resumen tuyo)."
            )
        elif sugerido:
            instruccion = (
                f"Corre AHORA: `{sugerido}`\n"
                "Lee el fallo si lo hay, arregla el codigo, y recien despues cerra con "
                "responder INCLUYENDO la salida REAL (el conteo de pytest, no un resumen tuyo)."
            )
        else:
            # Sin comando canonico, Hermes manda a fabricar una verificacion ad-hoc y a
            # declararla COMO ad-hoc (nunca a venderla como suite verde).
            instruccion = (
                "Este proyecto no declara ningun comando de test/lint/build. Escribi una "
                "comprobacion minima que ejercite lo que cambiaste, correla con la tool "
                "`ejecutar`, y al cerrar deci explicitamente que es una verificacion ad-hoc "
                "y NO la suite del proyecto."
            )

        base["motivo"] = "falta_verificacion"
        base["nudge"] = (
            "[SISTEMA: en este turno editaste CODIGO y todavia no hay evidencia FRESCA de "
            "que funcione.\n\n"
            f"Estado de la verificacion: {_detalle_estado(ev)}\n\n"
            f"Ficheros que tocaste:\n{_lista_rutas(ficheros)}\n\n"
            f"{instruccion}\n"
            "Si verificar es IMPOSIBLE, deci cual es el bloqueo CONCRETO en vez de declarar "
            "la tarea verificada.]"
        )
        return base
    except Exception:
        # Camino caliente: una compuerta rota deja pasar, nunca rompe el turno.
        return {"nudge": None, "sintetico": True, "motivo": "error_interno",
                "estado_evidencia": "", "ficheros": [], "comando_sugerido": "",
                "tests_a_crear": [], "nudges_usados": 0}


def decidir(estado):
    """El texto del nudge a inyectar como mensaje de usuario, o None para dejar cerrar."""
    return decidir_detallado(estado).get("nudge")


# -- Rescate de la respuesta pendiente ----------------------------------------

def rescatar_respuesta_pendiente(pendiente, respuesta_final=None, presupuesto_agotado=False,
                                 interrumpido=False, fallido=False,
                                 motivo_salida="desconocido") -> dict:
    """Recupera la respuesta que el nudge retuvo, si el presupuesto se agoto despues.

    EL DETALLE CRITICO. La compuerta retiene a proposito una respuesta que el modelo YA
    habia compuesto; si el turno se queda sin presupuesto antes de producir otra, esa
    respuesta se PIERDE y el usuario ve un turno vacio por culpa de la compuerta que venia
    a mejorarlo. Hermes lo resuelve en turn_finalizer.py:100-124: "preserve that exact
    answer instead of replacing it with another fallible model call".

    Se rescata SOLO si se cumplen las cuatro condiciones (el pendiente explicito es la
    guarda de procedencia: una salida por error o por interrupcion NUNCA entra aca):
        1. no hay respuesta final nueva,
        2. hay una pendiente no vacia,
        3. el presupuesto se agoto,
        4. la salida no fue por interrupcion ni por fallo.

    Devuelve {"respuesta": str|None, "rescatada": bool, "motivo": str}.
    """
    try:
        texto = pendiente.strip() if isinstance(pendiente, str) else ""
        final = respuesta_final.strip() if isinstance(respuesta_final, str) else ""
        if final:
            return {"respuesta": respuesta_final, "rescatada": False,
                    "motivo": "hay_respuesta_nueva"}
        if not texto:
            return {"respuesta": None, "rescatada": False, "motivo": "sin_pendiente"}
        if interrumpido or fallido:
            return {"respuesta": None, "rescatada": False, "motivo": "salida_por_error"}
        if not presupuesto_agotado:
            return {"respuesta": None, "rescatada": False, "motivo": "presupuesto_disponible"}
        if str(motivo_salida) not in ("desconocido", "presupuesto_agotado",
                                      "verificacion_requerida"):
            return {"respuesta": None, "rescatada": False,
                    "motivo": f"motivo_ajeno:{motivo_salida}"}
        return {"respuesta": pendiente, "rescatada": True,
                "motivo": "presupuesto_agotado_tras_nudge"}
    except Exception:
        return {"respuesta": None, "rescatada": False, "motivo": "error_interno"}


# -- Ayudas para el cableado (nada de esto decide; solo traduce) --------------

_ACCIONES_QUE_EDITAN = ("escribir_archivo", "editar_archivo", "apendar_archivo")


def ficheros_editados_de_traza(traza) -> list:
    """Rutas editadas leidas de `_actions_trace` de cli.py (entradas {action, args, ok}).

    Existe para que el cableado no tenga que llevar un set aparte: la traza YA registra cada
    accion con sus args, y las tools de edicion ponen la ruta antes del primer '|' (ver
    cognia/agent/tools.py: `escribir_archivo <path> | <contenido>`). Solo cuentan los pasos
    ok: un escribir_archivo que devolvio ERROR no edito nada.
    """
    rutas = []
    for paso in (traza or []):
        if not isinstance(paso, dict):
            continue
        if str(paso.get("action") or "").lower() not in _ACCIONES_QUE_EDITAN:
            continue
        if paso.get("ok") is False:
            continue
        ruta = str(paso.get("args") or "").split("|", 1)[0].strip().strip('"').strip("'")
        if ruta and ruta not in rutas:
            rutas.append(ruta)
    return rutas


def es_comando_de_verificacion(comando: str) -> bool:
    """Si un comando corrido con la tool `ejecutar` cuenta como evidencia de verificacion."""
    c = str(comando or "").lower()
    return any(p in c for p in _PALABRAS_VERIFICACION)


_RE_FALLO = re.compile(r"(\d+\s+failed|\d+\s+error|\bfailed\b|\berror:|traceback|assertionerror)",
                       re.IGNORECASE)
_RE_PASO = re.compile(r"(\d+\s+passed|\bok\b|all tests passed|\bsuccess\b)", re.IGNORECASE)


def exito_de_verificacion(salida: str) -> bool:
    """Veredicto de una salida de test/lint, para pasarselo a `registrar_verificacion`.

    Heuristica DECLARADA, no adivinanza escondida: el fallo gana al exito porque una corrida
    con '1 failed, 40 passed' es un fallo, y sin marca de exito el default es False (ausencia
    de examen no es aprobado: mismo criterio que cognia/harness/verificacion.py). Cuando el
    caller tenga el returncode real, que use ese en vez de esto.
    """
    s = str(salida or "")
    if _RE_FALLO.search(s):
        return False
    return bool(_RE_PASO.search(s))


__all__ = [
    "MAX_NUDGES", "decidir", "decidir_detallado", "registrar_verificacion",
    "estado_verificacion", "rescatar_respuesta_pendiente", "comandos_canonicos",
    "comando_sugerido", "plan_verificacion", "compuerta_activa", "es_prosa",
    "filtrar_verificables",
    "ficheros_editados_de_traza", "es_comando_de_verificacion", "exito_de_verificacion",
    "raiz_proyecto", "ruta_ledger",
]
