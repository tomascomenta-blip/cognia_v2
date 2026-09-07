# -*- coding: utf-8 -*-
"""
cognia/fases/pipeline.py — las fases de la obra y el bucle de cada una.

    planificar -> prototipo -> completar -> robustez -> visual -> pulido
      -> optimizacion -> redteam -> regresion -> release

Dentro de cada fase, el mismo lazo:

    ANALIZAR (estado + DoD + issues)  ->  IMPLEMENTAR (el agente, con un
    rol y una hipotesis)  ->  PROBAR (el verificador corre la DoD con tools
    reales)  ->  JUZGAR (contra la ultima version aceptada)  ->  ACEPTAR
    (commit) / REVERTIR (git)  ->  ¿criterio de salida de la fase?

El agente NUNCA decide que la fase termino: lo decide el criterio de salida
sobre las metricas medidas. Con el tope de iteraciones agotado la fase queda
"incompleta" y se sigue (se dice en el informe); solo el prototipo sin
ninguna version aceptada aborta la obra.

El ejecutor del agente se INYECTA (`ejecutor(prompt, rol, allowed_tools)
-> texto`): en el CLI es cli._run_agent_task; en los tests, una funcion que
escribe ficheros. Asi el pipeline se prueba entero sin modelo.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from cognia.fases import dod as _dod
from cognia.fases import estado as _est
from cognia.fases import juez as _juez
from cognia.fases import verificador as _ver
from cognia.fases import versiones as _git

ITER_DEF = 3
FASES = [
    {"id": "planificar", "nombre": "Planificacion", "pregunta": "Que debe existir?", "rol": "planificador", "max_iter": 1},
    {"id": "prototipo", "nombre": "Prototipo funcional", "pregunta": "Funciona de punta a punta?", "rol": "constructor", "max_iter": 3},
    {"id": "completar", "nombre": "Completar funcionalidades", "pregunta": "Esta todo?", "rol": "constructor", "max_iter": 4},
    {"id": "robustez", "nombre": "Testing profundo", "pregunta": "Se rompe?", "rol": "qa", "max_iter": 3},
    {"id": "visual", "nombre": "Graficos y visual", "pregunta": "Se ve bien?", "rol": "visual", "max_iter": 3, "solo": ("web", "python_gui")},
    {"id": "pulido", "nombre": "Pulido UX", "pregunta": "Se siente bien?", "rol": "pulido", "max_iter": 2},
    {"id": "optimizacion", "nombre": "Optimizacion", "pregunta": "Es eficiente?", "rol": "optimizador", "max_iter": 2},
    {"id": "redteam", "nombre": "Red team", "pregunta": "Como lo rompo?", "rol": "redteam", "max_iter": 3},
    {"id": "regresion", "nombre": "Regresion final", "pregunta": "Sigue todo en pie?", "rol": "constructor", "max_iter": 2},
    {"id": "release", "nombre": "Release", "pregunta": "Esta realmente listo?", "rol": "", "max_iter": 1},
]
IDS = [f["id"] for f in FASES]

# Tools de solo lectura + pruebas para los roles que NO deben modificar nada
_SOLO_LECTURA = {"leer_archivo", "leer_lote", "listar", "arbol", "buscar", "buscar_ficheros", "contar_lineas",
                 "repo_map", "code_grafo", "git_estado", "git_diff", "git_log", "notas", "anotar", "calcular",
                 "ejecutar", "ejecutar_guion", "ejecutar_fondo", "ver_salida", "matar_proceso", "procesos",
                 "renderizar", "tests", "py_validar", "json_validar", "recordar", "responder"}


def fase_por_id(fid: str) -> dict | None:
    for f in FASES:
        if f["id"] == fid:
            return f
    return None


def fases_aplicables(est: dict, ids: list = None) -> list:
    out = []
    for f in FASES:
        if ids and f["id"] not in ids:
            continue
        solo = f.get("solo")
        if solo and est.get("tipo_producto") and est["tipo_producto"] not in solo:
            continue
        out.append(f)
    return out


# ---------------------------------------------------------------------------
# Prompts por rol
# ---------------------------------------------------------------------------

_REGLAS_COMUNES = """REGLAS DE LA OBRA (no negociables):
- Trabaja SOLO en el objetivo de esta fase. Nada de "ya que estoy, rehago X".
- Antes de tocar codigo declara la hipotesis: fases_hipotesis <que pasa y por que> | plan=1. ..; 2. .. | esperado=...
- Una hipotesis por iteracion, cambios pequenos y enfocados. Si algo falla dos veces igual, cambia de hipotesis.
- NO toques lo marcado NO TOCAR salvo razon concreta escrita en la hipotesis.
- Verifica con las tools REALES antes de afirmar nada: probar <ruta>, renderizar <html> | guion=..., app_probar <cmd> | pasos=..., ejecutar_guion, tests. Pega la salida real.
- Los requisitos MANUALES (visuales/UX) se marcan con evidencia: fases_dod marcar V1 ok | evidencia=... Los ejecutables los marca el verificador.
- Cada bug que veas: fases_issue agregar P2 | titulo | pasos=... | esperado=... | actual=... | evidencia=... ; al arreglarlo: fases_issue cerrar #id | causa=... | fix=...
- Un JUEZ externo correra la Definicion de Hecho al terminar y comparara con la version anterior: si algo empeora (menos requisitos OK, mas errores de consola, un traceback, un P0 nuevo) tu cambio se REVIERTE entero. Si no mejora nada medible, tambien.
- Cierra respondiendo con tres bloques: HIPOTESIS / CAMBIOS (ficheros) / RESULTADO (que verificaste y su salida real)."""

_ROLES = {
    "planificador": """FASE 0 — PLANIFICAR. NO programes todavia, no escribas ficheros del producto.
1. Decide tipo_producto (web | python_gui | python_cli | node | otro) y el entrypoint (index.html, juego.py...).
2. Divide el producto en CORE / FEATURES / UI / GRAFICOS / AUDIO / UX / RENDIMIENTO / TESTS y decide la arquitectura (ficheros y responsabilidad de cada uno, 3-6 lineas).
3. Escribe la DEFINICION DE HECHO: requisitos FUNCIONALES (uno por comportamiento observable, en orden de flujo principal primero), VISUALES y de CALIDAD. Cada requisito lleva una verificacion EJECUTABLE siempre que se pueda (guion de renderizar con asserts, app_probar con pasos, ejecutar con regex, tests); solo lo que de verdad necesita ojo humano va como manual.
4. Guardala con la tool: fases_dod definir <el JSON>  (formato exacto abajo). Responde ademas con el mismo JSON en un bloque ```json.
FORMATO:
""",
    "constructor_prototipo": """FASE 1 — PROTOTIPO FUNCIONAL. Objetivo: que EXISTA el flujo principal de punta a punta, aunque sea feo:
{core}
No pulas nada, no hagas menus bonitos: primero que arranque, se juegue/use y termine. Crea el entrypoint {entrypoint} y lo minimo alrededor. Verifica que arranca de verdad (probar / renderizar guion / app_probar) antes de cerrar.""",
    "constructor_completar": """FASE 2 — COMPLETAR FUNCIONALIDADES. Recorre los requisitos que faltan UNO A UNO (implementa uno, verificalo, pasa al siguiente):
{pendientes}
No toques lo que ya pasa. Si un requisito necesita un test, escribelo (tests/) y pasalo.""",
    "qa": """FASE 3 — TESTING PROFUNDO. Sos QA, no desarrollador. Primero intenta ROMPER el producto usandolo como un usuario real y luego como un usuario malicioso:
spam de teclas y clics, dos entradas a la vez, reiniciar en mitad de algo, valores extremos (0, negativos, enormes), entradas invalidas, secuencias raras, redimensionar (pagina_responsive), cerrar y volver a abrir.
Usa renderizar | guion=..., app_probar | pasos=..., ejecutar_guion | entradas=..., pagina_consola, app_salida. Registra CADA bug reproducible con fases_issue agregar (prioridad honesta, pasos exactos, esperado, actual, evidencia).
Despues arregla de P0 a P4, UN bug por vez, con test de regresion cuando se pueda, y cierra cada issue con causa y fix. Issues abiertos ahora:
{issues}""",
    "visual": """FASE 4 — GRAFICOS Y VISUAL. Mira el producto DE VERDAD, no el codigo: renderizar (captura), app_ver, pagina_responsive (360/768/1280), pagina_fotogramas (anima?), captura_describir (VLM si hay), captura_cuadricula para posiciones, captura_diff entre versiones.
Evalua: composicion (jerarquia, alineacion, espaciado), consistencia (tipografia, colores, tamanos), errores (superposiciones, cortes, elementos fuera de pantalla, texturas/recursos faltantes) y pulido (transiciones, feedback). Corrige UNA sub-area por iteracion: {subarea}.
Marca los requisitos visuales con la captura que lo prueba (fases_dod marcar V1 ok | evidencia=...). Requisitos visuales:
{visuales}""",
    "pulido": """FASE 5 — PULIDO. El producto funciona y se ve bien. La pregunta ahora es: que lo hace parecer amateur?
Busca: feedback tras cada accion, transiciones bruscas, espaciados inconsistentes, timing, estados que faltan (vacio, error, cargando), mensajes de error comprensibles, microinteracciones. Elige UNA mejora concreta, implementala y demuestra con capturas/guion que mejoro sin romper nada.""",
    "optimizador": """FASE 6 — OPTIMIZACION. NO cambies funcionalidad. Mide ANTES (py_perfilar, tiempo de carga con renderizar espera=0, pagina_fotogramas para fluidez, tamano de ficheros/assets, tests con tiempo), optimiza lo que mas pese, mide DESPUES y reporta los dos numeros. Si no hay mejora medida, NO toques nada y dilo.""",
    "redteam": """FASE 7 — RED TEAM. Tu objetivo NO es mejorar el producto: es hacerlo FALLAR. NO modifiques ningun fichero (solo tools de lectura y prueba).
Prueba: entradas invalidas, secuencias inesperadas, valores extremos, interacciones rapidas y repetidas, resoluciones raras, interrupciones, agotamiento (muchos objetos), transiciones de estado, casos visuales limite.
Reporta CADA problema reproducible con fases_issue agregar <P0..P4> | <titulo> | pasos=... | esperado=... | actual=... | evidencia=... | causa=... . Si no encuentras nada tras probar de verdad, dilo con la lista de lo que probaste.""",
    "constructor_arreglar": """ARREGLAR LO QUE ENCONTRO EL RED TEAM. Arregla de P0 a P4, UN issue por vez, con test de regresion cuando se pueda, y cierra cada uno con causa y fix. Issues abiertos:
{issues}""",
    "constructor_regresion": """FASE 8 — REGRESION FINAL. Solo arregla lo que la Definicion de Hecho marca como FALLA (no agregues nada):
{fallan}
Si nada falla, no toques ficheros: responde que la regresion esta en verde.""",
}


def _lista(items, tope=14, fmt=lambda it: "- %s %s" % (it["id"], it["texto"])) -> str:
    return "\n".join(fmt(it) for it in items[:tope]) or "- (nada)"


def prompt_de(fase: dict, est: dict, iteracion: int, max_iter: int, contexto_extra: str = "") -> str:
    rol = fase["rol"]
    fid = fase["id"]
    d = est["dod"]
    if rol == "planificador":
        cuerpo = _ROLES["planificador"] + _dod.plantilla_para_modelo()
    elif fid == "prototipo":
        core = _lista([i for i in d.get("funcionales", [])][:6])
        cuerpo = _ROLES["constructor_prototipo"].format(core=core, entrypoint=est.get("entrypoint") or "el entrypoint que decidiste")
    elif fid == "completar":
        pend = _lista([i for i in d.get("funcionales", []) if i.get("ok") is not True])
        cuerpo = _ROLES["constructor_completar"].format(pendientes=pend)
    elif rol == "qa":
        cuerpo = _ROLES["qa"].format(issues=_lista(_est.issues_abiertos(est), fmt=lambda i: "- %s %s %s" % (i["id"], i["prioridad"], i["titulo"])))
    elif rol == "visual":
        subareas = ["direccion de arte y paleta", "escenario/fondo y layout", "personajes/objetos e iconos",
                    "UI (HUD, menus, botones) y tipografia", "animaciones, transiciones y efectos"]
        cuerpo = _ROLES["visual"].format(subarea=subareas[(iteracion - 1) % len(subareas)],
                                         visuales=_lista(d.get("visuales", [])))
    elif rol == "pulido":
        cuerpo = _ROLES["pulido"]
    elif rol == "optimizador":
        cuerpo = _ROLES["optimizador"]
    elif rol == "redteam":
        cuerpo = _ROLES["redteam"]
    elif fid == "regresion":
        fallan = _lista([i for i in _dod.items(d) if i.get("ok") is False],
                        fmt=lambda it: "- %s %s -- %s" % (it["id"], it["texto"], (it.get("evidencia") or "")[:120]))
        cuerpo = _ROLES["constructor_regresion"].format(fallan=fallan)
    else:
        cuerpo = _ROLES["constructor_arreglar"].format(issues=_lista(_est.issues_abiertos(est), fmt=lambda i: "- %s %s %s" % (i["id"], i["prioridad"], i["titulo"])))
    partes = ["OBRA POR FASES · fase %s (%s) · iteracion %d/%d" % (fase["nombre"].upper(), fase["pregunta"], iteracion, max_iter),
              "ENCARGO: " + est["encargo"], "", _est.resumen_para_prompt(est), "", cuerpo]
    if contexto_extra:
        partes += ["", "RESULTADO DE LA ITERACION ANTERIOR (del juez):", contexto_extra]
    if rol != "planificador":
        partes += ["", _REGLAS_COMUNES]
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# Criterios de salida por fase (sobre metricas medidas, nunca sobre opinion)
# ---------------------------------------------------------------------------

def _ejecutables(items):
    return [i for i in items if (i.get("verif") or {}).get("tipo") != "manual"]


def criterio_salida(fase: dict, est: dict, m: dict | None) -> tuple:
    """(cumplido, motivo)."""
    fid = fase["id"]
    d = est["dod"]
    c = _est.conteo_issues(est)
    if fid == "planificar":
        return (_dod.total(d) > 0, "DoD con %d requisitos" % _dod.total(d))
    if m is None:
        return (False, "sin version aceptada")
    func = d.get("funcionales", [])
    ejec = _ejecutables(func)
    if fid == "prototipo":
        base = ejec[:3] if ejec else []
        if base:
            ok = all(i.get("ok") for i in base)
            return (ok, "flujo principal: %d/%d requisitos ejecutables OK" % (sum(1 for i in base if i.get("ok")), len(base)))
        return (m.get("tracebacks", 0) == 0 and bool(est.get("entrypoint")), "sin requisitos ejecutables: arranca sin traceback")
    if fid == "completar":
        pend = [i for i in ejec if i.get("ok") is not True]
        return (not pend, "%d requisitos ejecutables pendientes" % len(pend))
    if fid == "robustez":
        cal = _ejecutables(d.get("calidad", []))
        cal_ok = all(i.get("ok") for i in cal) if cal else True
        return (c["P0"] == 0 and c["P1"] == 0 and cal_ok and m.get("tracebacks", 0) == 0,
                "P0=%d P1=%d, calidad ejecutable %s" % (c["P0"], c["P1"], "OK" if cal_ok else "FALLA"))
    if fid == "visual":
        vis = d.get("visuales", [])
        ok = [i for i in vis if i.get("ok") is True]
        return (bool(vis) and len(ok) == len(vis), "visuales %d/%d OK" % (len(ok), len(vis)))
    if fid in ("pulido", "optimizacion"):
        ult = est["fases"][fid]["iteraciones"]
        return (any(it.get("decision") == "aceptar" for it in ult), "una iteracion aceptada" if ult else "sin iteraciones")
    if fid == "redteam":
        return (c["P0"] == 0 and c["P1"] == 0 and c["P2"] == 0, "P0=%d P1=%d P2=%d" % (c["P0"], c["P1"], c["P2"]))
    if fid == "regresion":
        ejec_all = _ejecutables(_dod.items(d))
        fallan = [i for i in ejec_all if i.get("ok") is False]
        return (not fallan and m.get("tracebacks", 0) == 0 and m.get("consola_errores", 0) == 0,
                "%d ejecutables fallan, tracebacks %d, consola %d" % (len(fallan), m.get("tracebacks", 0), m.get("consola_errores", 0)))
    return (True, "")


# ---------------------------------------------------------------------------
# El bucle
# ---------------------------------------------------------------------------

class Obra:
    """Una corrida (reanudable) de la obra por fases sobre un workspace."""

    def __init__(self, workspace, encargo: str = "", ejecutor=None, imprimir=None,
                 iteraciones: int = None, minutos: float = None, fases_ids: list = None,
                 tools_visibles: set = None):
        self.ws = Path(str(workspace)).resolve()
        self.ejecutor = ejecutor
        self.imprimir = imprimir or (lambda s: None)
        self.iteraciones = iteraciones
        self.minutos = minutos
        self.tools_visibles = set(tools_visibles or ())
        self.t0 = time.time()
        self.est = _est.cargar(self.ws)
        if self.est is None:
            if not encargo:
                raise ValueError("no hay obra en %s y no se dio encargo" % self.ws)
            self.est = _est.nuevo(self.ws, encargo, fases_ids or IDS)
        elif encargo and encargo.strip() != self.est["encargo"]:
            self.est["notas"].append("encargo ampliado: " + encargo.strip()[:400])
        self.fases_ids = fases_ids or list(self.est["fases"].keys())
        self.git = _git.asegurar_repo(self.ws)
        if not self.git["ok"]:
            self.imprimir("[fases] sin git: no habra revert (%s)" % self.git["motivo"])
        elif self.git.get("creado"):
            _git.snapshot(self.ws, "fases: v0 base (estado previo del workspace)")

    # -- utilidades -------------------------------------------------------
    def _p(self, s: str) -> None:
        self.imprimir(s)

    def _guardar(self) -> None:
        _est.guardar(self.est)

    def _recargar(self) -> None:
        nuevo = _est.cargar(self.ws)
        if nuevo:
            self.est = nuevo

    def _tiempo_agotado(self) -> bool:
        return bool(self.minutos) and (time.time() - self.t0) > self.minutos * 60

    def _allowed(self, rol: str):
        fases_tools = {"fases_estado", "fases_dod", "fases_issue", "fases_hipotesis", "fases_estable"}
        if rol in ("redteam", "planificador"):
            base = set(_SOLO_LECTURA)
            try:
                from cognia.agent.tools import TOOLS, flag_de_optin
                base |= {n for n in TOOLS if flag_de_optin(n) == "COGNIA_PRUEBAS" and not n.startswith("app_cerrar")}
                base -= {"escribir_archivo", "editar_archivo", "apendar_archivo", "borrar_archivo"}
            except Exception:
                pass
            return base | fases_tools
        if self.tools_visibles:
            return set(self.tools_visibles) | fases_tools
        return None

    def _correr_agente(self, prompt: str, rol: str) -> str:
        os.environ["COGNIA_FASES_WORKSPACE"] = str(self.ws)
        os.environ["COGNIA_FASES"] = "1"      # anuncia las tools fases_* (ver tools._OPTIN_PREFIJOS)
        if self.minutos:
            # el arnes lee el reloj de pared: sin el, una iteracion se comia el
            # presupuesto entero (la obra Snake: 50 min pedidos, 61 corridos)
            restante = max(120, int(self.minutos * 60 - (time.time() - self.t0)))
            os.environ["COGNIA_PARED_S"] = str(min(restante, 1500))
        cwd = os.getcwd()
        try:
            os.chdir(str(self.ws))
            return self.ejecutor(prompt, rol, self._allowed(rol)) or ""
        finally:
            os.chdir(cwd)

    def _ef(self, fid: str) -> dict:
        """El dict de la fase en el estado VIVO (self.est cambia tras cada
        _recargar(): una referencia capturada antes queda rancia y las
        escrituras se pierden; cazado en el test del pipeline)."""
        return self.est["fases"].setdefault(fid, {"estado": "pendiente", "iteraciones": []})

    def _metricas_prev(self):
        ua = _est.ultima_aceptada(self.est)
        return (ua or {}).get("metricas")

    # -- fases ------------------------------------------------------------
    def correr(self) -> dict:
        """Recorre las fases desde `fase_actual`. Devuelve el informe final (dict)."""
        for fase in fases_aplicables(self.est, self.fases_ids):
            fid = fase["id"]
            if self._ef(fid)["estado"] in ("completa", "saltada"):
                continue
            if self._tiempo_agotado():
                self._p("[fases] tiempo agotado antes de %s: la obra queda reanudable (/fases reanudar)" % fid)
                break
            self.est["fase_actual"] = fid
            self._ef(fid)["estado"] = "en_curso"
            self._guardar()
            self._p("[fases] ══ FASE %s: %s — %s" % (fid, fase["nombre"], fase["pregunta"]))
            if fid == "release":
                self._ef(fid)["estado"] = "completa"
                self.est["terminado"] = True
                self._guardar()
                break
            ok = self._fase(fase)
            self._ef(fid)["estado"] = "completa" if ok else "incompleta"
            self._guardar()
            if fid == "prototipo" and not _est.ultima_aceptada(self.est):
                self._p("[fases] el prototipo no produjo ninguna version aceptada: la obra se detiene aqui")
                break
            if self._tiempo_agotado():
                self._p("[fases] tiempo agotado tras %s: la obra queda reanudable (/fases reanudar)" % fid)
                break
        os.environ.pop("COGNIA_FASES", None)
        inf = informe_final(self.est)
        self.est["veredicto"] = inf["estado"]
        self._guardar()
        return inf

    def _fase(self, fase: dict) -> bool:
        fid = fase["id"]
        max_iter = self.iteraciones or fase.get("max_iter", ITER_DEF)
        if fid == "planificar":
            return self._planificar(fase)
        contexto = ""
        hechas = len(self._ef(fid)["iteraciones"])
        for it in range(hechas + 1, max_iter + 1):
            if self._tiempo_agotado():
                return False
            cumplido, motivo = criterio_salida(fase, self.est, self._metricas_prev())
            if cumplido and it > 1 or (cumplido and fid in ("completar", "regresion", "robustez", "redteam")):
                self._p("[fases] criterio de salida ya cumplido (%s)" % motivo)
                return True
            rol = fase["rol"]
            if fid == "redteam":
                # el red team no cambia nada; luego arregla el constructor
                self._iteracion(fase, it, max_iter, "redteam", contexto)
                if self._tiempo_agotado():
                    return False
                if not [i for i in _est.issues_abiertos(self.est) if i["prioridad"] in ("P0", "P1", "P2")]:
                    self._p("[fases] el red team no dejo P0/P1/P2 abiertos")
                    return True
                rol = "constructor_arreglar"
            res = self._iteracion(fase, it, max_iter, rol, contexto)
            contexto = res.get("contexto", "")
            cumplido, motivo = criterio_salida(fase, self.est, self._metricas_prev())
            self._p("[fases] salida de %s: %s (%s)" % (fid, "CUMPLIDA" if cumplido else "no", motivo))
            if cumplido:
                return True
        self._p("[fases] %s: tope de %d iteraciones sin cumplir el criterio; se sigue con la obra (queda INCOMPLETA)" % (fid, max_iter))
        return False

    def _planificar(self, fase: dict) -> bool:
        prompt = prompt_de(fase, self.est, 1, 1)
        resp = self._correr_agente(prompt, "planificador")
        self._recargar()
        if _dod.total(self.est["dod"]) == 0:
            d = _dod.parsear_json(resp)
            if d is not None:
                meta = d.pop("_meta", {})
                self.est["dod"] = d
                self.est["tipo_producto"] = str(meta.get("tipo_producto") or self.est.get("tipo_producto") or "").lower()
                self.est["entrypoint"] = str(meta.get("entrypoint") or self.est.get("entrypoint") or "")
        if _dod.total(self.est["dod"]) == 0:
            self._p("[fases] el planificador no dejo una Definicion de Hecho valida: uso la automatica (enunciado + calidad estandar)")
            self.est["dod"] = _dod.automatica(self.est["encargo"], self.est.get("tipo_producto"), self.est.get("entrypoint"))
        if not self.est.get("tipo_producto"):
            self.est["tipo_producto"] = adivinar_tipo(self.est["encargo"], self.est.get("entrypoint", ""))
        if not self.est.get("entrypoint"):
            self.est["entrypoint"] = {"web": "index.html", "python_gui": "main.py", "python_cli": "main.py", "node": "index.js"}.get(self.est["tipo_producto"], "")
        res = _dod.resumen(self.est["dod"])
        self._ef(fase["id"])["iteraciones"].append({"n": 1, "decision": "aceptar", "resumen": "DoD %d requisitos" % res["total"], "ts": time.time()})
        self._p("[fases] Definicion de Hecho: %d requisitos (%d ejecutables, %d manuales) · tipo %s · entrypoint %s"
                % (res["total"], res["total"] - res["manuales"], res["manuales"], self.est["tipo_producto"], self.est["entrypoint"]))
        self._guardar()
        return True

    def _iteracion(self, fase: dict, n: int, max_iter: int, rol: str, contexto: str) -> dict:
        fid = fase["id"]
        head_antes = _git.head(self.ws) if self.git["ok"] else ""
        untracked_antes = _git.untracked(self.ws) if self.git["ok"] else set()
        dod_antes = _copia(self.est["dod"])
        issues_antes = _est.conteo_issues(self.est)
        cerrados_antes = sum(1 for i in self.est["issues"] if i["estado"] == "cerrado")
        self.est["hipotesis"] = {}
        self._guardar()
        self._p("[fases] iteracion %d/%d (%s)" % (n, max_iter, rol))
        prompt = prompt_de(dict(fase, rol=rol if rol != "constructor_arreglar" else "constructor"), self.est, n, max_iter, contexto) \
            if rol != "constructor_arreglar" else prompt_de(dict(fase, rol="constructor_arreglar"), self.est, n, max_iter, contexto)
        t_ag = time.time()
        respuesta = self._correr_agente(prompt, rol)
        self._recargar()
        hip = dict(self.est.get("hipotesis") or {})
        cambios = _git.ficheros_cambiados(self.ws, head_antes) if self.git["ok"] else ["(sin git)"]
        registro = {"n": n, "rol": rol, "segundos_agente": round(time.time() - t_ag, 1), "cambios": cambios[:30], "ts": time.time()}
        if rol == "redteam":
            nuevos = sum(_est.conteo_issues(self.est).values()) - sum(issues_antes.values())
            registro.update({"decision": "informe", "resumen": "%d issue(s) nuevos" % nuevos})
            if cambios and self.git["ok"]:
                # el red team no debe tocar nada: se revierte lo que haya tocado
                _git.revertir(self.ws, head_antes, untracked_antes)
                registro["resumen"] += " · toco %d fichero(s): revertidos" % len(cambios)
            self._ef(fid)["iteraciones"].append(registro)
            self._guardar()
            self._p("[fases] red team: %s" % registro["resumen"])
            return {"contexto": ""}
        self._p("[fases] verificando la Definicion de Hecho (%s)..." % (", ".join(cambios[:5]) or "sin cambios"))
        n_version = 1 + max([0] + [v["n"] for v in self.est["versiones"]])
        m = _ver.verificar(self.est, cambios if cambios != ["(sin git)"] else None, on_evento=self._p, version_n=n_version)
        prev = self._metricas_prev()
        cerrados = sum(1 for i in self.est["issues"] if i["estado"] == "cerrado") - cerrados_antes
        ver = _juez.juzgar(prev, m, cambios, self.est.get("estables"), fid, issues_antes, _est.conteo_issues(self.est), cerrados)
        self._p("[fases] " + _ver.texto_metricas(m))
        self._p(_juez.informe(prev, m, ver))
        decision = ver["decision"]
        if decision == "aceptar":
            commit = head_antes
            if self.git["ok"]:
                snap = _git.snapshot(self.ws, "fases: v%d fase %s it %d aceptada" % (n_version, fid, n))
                commit = snap.get("commit") or head_antes
                if not snap["ok"]:
                    self._p("[fases] commit fallo: %s" % snap["motivo"])
            _est.version_registrar(self.est, commit, fid, n, m, "aceptar", ver["motivos"], hip)
        elif decision == "rechazar":
            _est.version_registrar(self.est, head_antes, fid, n, m, "rechazar", ver["motivos"], hip)
            if self.git["ok"]:
                r = _git.revertir(self.ws, head_antes, untracked_antes)
                self._p("[fases] REVERTIDO a %s (%d restaurados, %d borrados)%s" % (head_antes[:8], r["restaurados"], r["borrados"],
                                                                                    (" · " + r["motivo"]) if r.get("motivo") else ""))
            else:
                self._p("[fases] sin git: no se puede revertir; los cambios quedan (el informe lo dice)")
            self.est["dod"] = dod_antes
        registro.update({"decision": decision, "resumen": "; ".join(ver["motivos"])[:300], "metricas": {k: m.get(k) for k in ("req_ok", "req_total", "tests_ok", "tests_total", "consola_errores", "tracebacks")}})
        self._ef(fid)["iteraciones"].append(registro)
        self._guardar()
        contexto = "%s. %s. Metricas: %s" % (decision.upper(), "; ".join(ver["motivos"])[:300], _ver.texto_metricas(m))
        fallan = [i for i in _dod.items(self.est["dod"]) if i.get("ok") is False]
        if fallan:
            contexto += "\nRequisitos que FALLAN: " + "; ".join("%s (%s)" % (i["id"], (i.get("evidencia") or "")[:100]) for i in fallan[:6])
        return {"contexto": contexto, "decision": decision, "metricas": m, "respuesta": respuesta}


def _copia(obj):
    import json
    return json.loads(json.dumps(obj))


def adivinar_tipo(encargo: str, entrypoint: str = "") -> str:
    e = (encargo + " " + entrypoint).lower()
    if entrypoint.lower().endswith((".html", ".htm")) or any(k in e for k in ("html", "canvas", "pagina", "página", "web", "css", "javascript", "sitio")):
        return "web"
    if any(k in e for k in ("pygame", "tkinter", "ventana", "gui", "qt", "arcade")):
        return "python_gui"
    if any(k in e for k in ("node", "npm", "express")):
        return "node"
    if any(k in e for k in ("python", ".py", "script", "cli", "consola", "terminal")):
        return "python_cli"
    return "otro"


# ---------------------------------------------------------------------------
# Informe final
# ---------------------------------------------------------------------------

def informe_final(est: dict) -> dict:
    ua = _est.ultima_aceptada(est)
    m = (ua or {}).get("metricas") or {}
    c = _est.conteo_issues(est)
    p = _juez.puntuacion(m, c)
    res = _dod.resumen(est["dod"])
    incompletas = [f for f, d in est["fases"].items() if d["estado"] == "incompleta"]
    pendientes = [f for f, d in est["fases"].items() if d["estado"] in ("pendiente", "en_curso")]
    rech = sum(1 for v in est["versiones"] if v["decision"] == "rechazar")
    ult3 = [v for v in est["versiones"][-3:]]
    sin_regresion = all(v["decision"] == "aceptar" for v in ult3) if ult3 else False
    listo = (ua is not None and c["P0"] == 0 and c["P1"] == 0 and res["fallan"] == 0 and not pendientes
             and not incompletas and m.get("tracebacks", 0) == 0 and m.get("consola_errores", 0) == 0)
    if listo:
        estado = "LISTO PARA ENTREGAR"
    elif ua is None:
        estado = "SIN PRODUCTO (ninguna version aceptada)"
    elif pendientes:
        estado = "A MEDIAS (fases pendientes: %s) — reanudable" % ", ".join(pendientes)
    else:
        estado = "NO LISTO (%s)" % "; ".join(x for x in [
            ("fases incompletas: " + ", ".join(incompletas)) if incompletas else "",
            ("P0=%d P1=%d abiertos" % (c["P0"], c["P1"])) if (c["P0"] or c["P1"]) else "",
            ("%d requisitos fallan" % res["fallan"]) if res["fallan"] else "",
            ("tracebacks %d" % m.get("tracebacks", 0)) if m.get("tracebacks") else "",
            ("errores de consola %d" % m.get("consola_errores", 0)) if m.get("consola_errores") else ""] if x)
    lineas = ["═" * 44, "        INFORME FINAL DE CALIDAD", "═" * 44,
              "VERSION:            v%s (%s)" % ((ua or {}).get("n", 0), ((ua or {}).get("commit") or "")[:8] or "sin commit"),
              "", "FUNCIONAL",
              "Requisitos:         %d/%d OK (%d fallan, %d sin verificar)" % (res["ok"], res["total"], res["fallan"], res["sin"]),
              "Tests:              %s" % (("%d/%d PASS" % (m.get("tests_ok", 0), m.get("tests_total", 0))) if m.get("tests_total") else "sin tests"),
              "Bugs P0/P1/P2:      %d / %d / %d abiertos" % (c["P0"], c["P1"], c["P2"]),
              "Bugs P3/P4:         %d / %d abiertos" % (c["P3"], c["P4"]),
              "", "CALIDAD",
              "Errores de consola: %s" % m.get("consola_errores", "?"),
              "Tracebacks:         %s" % m.get("tracebacks", "?"),
              "Revision profunda:  %s" % ({True: "OK", False: "FALLA", None: "no evaluable"}[m.get("revision_ok")]),
              "", "VISUAL",
              "Requisitos visuales:%s" % (" %d/%d OK" % (sum(1 for i in est["dod"].get("visuales", []) if i.get("ok")), len(est["dod"].get("visuales", []))) if est["dod"].get("visuales") else " (sin requisitos)"),
              "Capturas:           %d" % len(m.get("capturas") or []),
              "", "PUNTUACION",
              "Funcionalidad %3d · Calidad %3d · Robustez %3d%s" % (p["funcionalidad"], p["calidad"], p["robustez"],
                                                                      (" · Tests %d" % p["tests"]) if p["tests"] is not None else ""),
              "", "PROCESO",
              "Versiones:          %d aceptadas, %d rechazadas (revertidas)" % (len([v for v in est["versiones"] if v["decision"] == "aceptar"]), rech),
              "Ultimas 3:          %s" % ("sin regresiones" if sin_regresion else "hubo rechazos"),
              "Fases:              " + ", ".join("%s=%s" % (f, d["estado"]) for f, d in est["fases"].items()),
              "", "ESTADO:             " + estado, "═" * 44]
    return {"estado": estado, "listo": listo, "texto": "\n".join(lineas), "puntuacion": p, "issues": c, "metricas": m}
