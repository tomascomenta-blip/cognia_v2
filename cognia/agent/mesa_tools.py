# -*- coding: utf-8 -*-
"""
cognia/agent/mesa_tools.py
==========================
La familia `mesa_*` (2026-09-08): el SEGUNDO PUESTO de Cognia. Un puntero
VIRTUAL y un teclado que operan el ESCRITORIO PROPIO (escritorio virtual
'Cognia') en PARALELO, sin tocar el raton ni el teclado del dueno, con una
PANTALLITA en vivo para que el dueno vea lo que hace. Ver `mesa.py` para lo
medido (SendInput no llega a un desktop de fondo; se usa PostMessage + UIA).

Ocho puertas (tope de anuncio de la familia):
  mesa_lanzar   abre una app en la mesa y enciende la pantallita
  mesa_ver      compone la pantalla de la mesa (lo que ve el dueno) y la resume
  mesa_raton    mover|clic|doble|derecho|arrastrar|rueda  (puntero virtual)
  mesa_invocar  clica un control por su ETIQUETA (la via mas fiable)
  mesa_teclear  escribe texto | tecla=intro | atajo=ctrl+s
  mesa_ventanas lista las ventanas de la mesa y permite activar una
  mesa_pantalla abrir|cerrar la pantallita en vivo
  mesa_estado   puntero, ventanas y si la pantallita esta abierta
"""
from __future__ import annotations

import time
from pathlib import Path

from cognia.agent import mesa as M
from cognia.agent import escritorio_propio as EP
from cognia.agent import pruebas_comun as PC

try:
    from cognia.agent import app_tools as AT
except Exception:
    AT = None

# Claves por tool (no un saco comun): con una lista ancha, un texto como
# "Nombre titulo=Informe" en mesa_teclear se partia por una clave ajena
# (revision adversarial 2026-09-08).
_CL_LANZAR = ("cwd", "espera", "titulo", "salida")
_CL_VER = ("salida", "escala")
_CL_TECLEAR = ("tecla", "atajo", "veces")
_CL_PANTALLA = ("fps", "escala")


def _err(tool: str, msg) -> str:
    return "ERROR %s: %s" % (tool, msg)


def _resumen_captura(r: dict) -> str:
    res = r.get("resumen") or {}
    try:
        return PC.texto_resumen_imagen(res) if "ancho" in res else res.get("veredicto", "")
    except Exception:
        return ""


def _ver(ctx, salida: str = "", escala: float = 1.0) -> dict:
    png = PC.ruta_salida(ctx, "mesa", ".png", salida)
    r = M.componer(str(png), escala=escala or 1.0, con_puntero=True)
    try:
        r["resumen"] = PC.resumen_imagen(png)
    except Exception:
        r["resumen"] = {}
    return r


def _texto_ui_activa(maximo: int = 900) -> str:
    hwnd = M.activa()
    if not hwnd:
        return ""
    partes = []
    try:
        arbol = M.arbol_estable(hwnd, profundidad=8, maximo=160)
        nombres = [n for _l, t, n, _r, _e in arbol if n and t not in ("Window",)]
        if nombres:
            partes.append("controles: " + " | ".join(dict.fromkeys(nombres))[:maximo])
    except Exception:
        pass
    return "\n".join(partes)


def register(tool) -> None:

    # ---- mesa_lanzar -----------------------------------------------------
    @tool("mesa_lanzar",
          "mesa_lanzar <comando> [| cwd=RUTA] [| espera=MS] [| titulo=texto]"
          "  -- abre una app en la MESA (escritorio propio) y enciende la pantallita en vivo",
          desc="Lanza una aplicacion con ventana en la mesa de Cognia (su escritorio propio, en paralelo, "
               "sin molestar al dueno), la deja como ventana ACTIVA para teclear/clicar, enciende la "
               "pantallita en vivo y devuelve una captura de la pantalla de la mesa. Luego usa mesa_raton, "
               "mesa_invocar, mesa_teclear, mesa_ver. Para juegos/apps que leen el raton fisico esto NO "
               "vale (usa el modo foco de /escritorio); para web usa las tools pagina_*.",
          params=[{"nombre": "comando", "tipo": "string", "requerido": True, "descripcion": "comando (python app.py, notepad.exe, ruta\\app.exe)"},
                  {"nombre": "cwd", "tipo": "string", "requerido": False, "clave": True, "descripcion": "directorio de trabajo"},
                  {"nombre": "espera", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "ms hasta la ventana (def 4000)"},
                  {"nombre": "titulo", "tipo": "string", "requerido": False, "clave": True, "descripcion": "parte del titulo esperado"}],
          danger=True, timeout_s=120)
    def _mesa_lanzar(args, ctx):
        if AT is None:
            return _err("mesa_lanzar", "app_tools no disponible")
        comando, o = PC.partir_args(args, _CL_LANZAR)
        try:
            cwd = o.get("cwd") or ((ctx or {}).get("workspace") if isinstance(ctx, dict) else None)
            if cwd and not Path(cwd).is_dir():
                return _err("mesa_lanzar", "cwd='%s' no es un directorio" % cwd)
            app_id, a = AT.lanzar(comando, cwd=cwd,
                                  espera_ms=PC.entero(o.get("espera"), 4000, 300, 60000),
                                  titulo=o.get("titulo", ""))
            if not a.get("mudada"):
                # La ventana se quedo en el escritorio del DUENO: no se opera
                # desde la mesa (estariamos tecleando en su pantalla).
                return _err("mesa_lanzar", "la app abrio (%r, id %s) pero NO se mudo a la mesa: %s. "
                            "Enciende el escritorio propio (/escritorio on) o instala pyvda; "
                            "mientras, cierrala con app_cerrar %s o pruebala con app_*"
                            % (a["titulo"], app_id, a.get("escritorio", ""), app_id))
            M.fijar_activa(a["hwnd"])
            pan = M.pantalla_abrir()
            # centrar el puntero en la ventana nueva
            try:
                rx, ry, rw, rh = EP.rect_ventana(a["hwnd"])
                M.mover(rx + rw // 2, ry + rh // 2, animar=False)
            except Exception:
                pass
            # UWP: despertar la app (plm) y quedarse con la ventana que expone
            # controles (la CoreWindow, no el marco de ApplicationFrameHost)
            ui_ok = M.mejor_ventana(a["hwnd"])
            if ui_ok.get("ok") and ui_ok["hwnd"] != a["hwnd"]:
                M.fijar_activa(ui_ok["hwnd"])
            r = _ver(ctx, o.get("salida", ""))
            ui = _texto_ui_activa()
            nota = "pantallita %s" % ("abierta" if pan.get("ok") and not pan.get("ya") else ("ya abierta" if pan.get("ya") else "no disponible: " + str(pan.get("error", ""))))
            if ui_ok.get("paquete"):
                nota += " · app de la Store mantenida despierta"
            aviso = ""
            if not ui_ok.get("ok"):
                aviso = ("\nAVISO: la ventana NO expone controles por UI Automation (%d nodo en %.0fs): mesa_invocar "
                         "no va a encontrar botones. Suele ser una instancia colgada de la app: cierrala con "
                         "app_cerrar %s (o app_cerrar todas) y vuelve a lanzarla; si es un juego/canvas, usa "
                         "mesa_teclear o el modo foco de /escritorio." % (ui_ok.get("nodos", 0), ui_ok.get("segundos", 0), app_id))
            return ("RESULTADO mesa_lanzar %s: ventana %r (hwnd %d) en la mesa%s · %s · captura %s (%d ventana(s))\n%s%s\n"
                    "Siguientes: mesa_invocar \"<etiqueta>\" · mesa_raton clic X Y · mesa_teclear <texto> · mesa_ver"
                    % (app_id, a["titulo"], a["hwnd"], " (ventana existente adoptada)" if a.get("adoptada") else "",
                       nota, r["png"], r.get("ventanas", 0), (ui or _resumen_captura(r)), aviso))
        except ValueError as exc:
            return _err("mesa_lanzar", exc)
        except Exception as exc:
            return _err("mesa_lanzar", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_ver --------------------------------------------------------
    @tool("mesa_ver",
          "mesa_ver [| salida=X.png] [| escala=0.5]  -- compone la pantalla de la mesa (lo que ve el dueno) y la resume",
          desc="Fotografia la MESA entera: compone todas sus ventanas sobre un lienzo del tamano de la "
               "pantalla y dibuja el puntero virtual de Cognia. Es exactamente lo que muestra la pantallita "
               "en vivo. Devuelve la ruta del PNG, cuantas ventanas pinto y el texto de la interfaz activa.",
          params=[{"nombre": "salida", "tipo": "string", "requerido": False, "clave": True, "descripcion": "ruta del PNG"},
                  {"nombre": "escala", "tipo": "number", "requerido": False, "clave": True, "descripcion": "factor de escala (def 1.0)"}],
          timeout_s=60)
    def _mesa_ver(args, ctx):
        _t, o = PC.partir_args(args, _CL_VER)
        try:
            escala = float(o.get("escala") or 1.0)
        except Exception:
            escala = 1.0
        try:
            r = _ver(ctx, o.get("salida", ""), escala=escala)
            return "RESULTADO mesa_ver: %s · %d ventana(s) · %s\n%s" % (
                r["png"], r.get("ventanas", 0), _resumen_captura(r), _texto_ui_activa())
        except Exception as exc:
            return _err("mesa_ver", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_raton ------------------------------------------------------
    @tool("mesa_raton",
          "mesa_raton <accion> <args>  -- puntero virtual: mover X Y | clic X Y | doble X Y | derecho X Y | "
          "arrastrar X0 Y0 X1 Y1 | rueda X Y PASOS",
          desc="Mueve y acciona el PUNTERO VIRTUAL de Cognia en coordenadas de PANTALLA (las mismas que ves "
               "en mesa_ver). El puntero se ve moverse en la pantallita; NUNCA toca el cursor del dueno. "
               "'clic' resuelve el control bajo el punto por UI Automation (Invoke) y si no cae a un clic por "
               "mensajes (esto ultimo no vale en Tk/pygame/juegos: para clicar de verdad un boton usa "
               "mesa_invocar por su etiqueta). Ejemplos: mesa_raton mover 640 400 · mesa_raton clic 640 400 · "
               "mesa_raton rueda 640 400 -3 (baja).",
          params=[{"nombre": "accion", "tipo": "string", "requerido": True, "descripcion": "mover|clic|doble|derecho|arrastrar|rueda y sus coordenadas"}],
          timeout_s=40)
    def _mesa_raton(args, ctx):
        toks = (args or "").replace(",", " ").split()
        if not toks:
            return _err("mesa_raton", "falta la accion (mover|clic|doble|derecho|arrastrar|rueda)")
        acc = toks[0].lower()
        nums = []
        for t in toks[1:]:
            try:
                nums.append(int(round(float(t))))
            except Exception:
                pass
        try:
            if acc in ("mover", "move"):
                if len(nums) < 2:
                    return _err("mesa_raton", "mover X Y")
                r = M.mover(nums[0], nums[1])
                return "RESULTADO mesa_raton mover: puntero en %d,%d" % (r["x"], r["y"])
            if acc in ("clic", "click", "izquierdo", "doble", "derecho", "der"):
                if len(nums) < 2:
                    return _err("mesa_raton", "%s X Y" % acc)
                boton = "derecho" if acc in ("derecho", "der") else "izquierdo"
                doble = acc == "doble"
                r = M.clic(nums[0], nums[1], boton=boton, doble=doble)
                if r.get("error"):
                    return _err("mesa_raton", r["error"])
                return "RESULTADO mesa_raton %s @%d,%d: %s%s" % (
                    acc, nums[0], nums[1], r.get("metodo", "?"),
                    (" en %r" % r["control"]) if r.get("control") else "")
            if acc in ("arrastrar", "drag"):
                if len(nums) < 4:
                    return _err("mesa_raton", "arrastrar X0 Y0 X1 Y1")
                r = M.arrastrar(nums[0], nums[1], nums[2], nums[3])
                return ("RESULTADO mesa_raton arrastrar %d,%d -> %d,%d" % (nums[0], nums[1], nums[2], nums[3])) if r.get("ok") else _err("mesa_raton", r.get("error"))
            if acc in ("rueda", "wheel", "scroll"):
                if len(nums) < 3:
                    return _err("mesa_raton", "rueda X Y PASOS (PASOS<0 baja)")
                r = M.rueda(nums[0], nums[1], nums[2])
                return ("RESULTADO mesa_raton rueda %d pasos @%d,%d" % (nums[2], nums[0], nums[1])) if r.get("ok") else _err("mesa_raton", r.get("error"))
            return _err("mesa_raton", "accion desconocida %r (mover|clic|doble|derecho|arrastrar|rueda)" % acc)
        except Exception as exc:
            return _err("mesa_raton", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_invocar ----------------------------------------------------
    @tool("mesa_invocar",
          "mesa_invocar <etiqueta>  -- clica el control (boton, menu, enlace...) cuyo nombre contiene la etiqueta, en la ventana activa",
          desc="La forma MAS FIABLE de 'pulsar' algo: busca por UI Automation un control cuyo nombre contiene "
               "el texto y lo invoca (no depende del pixel ni del tipo de app). Mueve el puntero virtual encima "
               "para que se vea en la pantallita. Ejemplo: mesa_invocar Guardar · mesa_invocar Aceptar.",
          params=[{"nombre": "etiqueta", "tipo": "string", "requerido": True, "descripcion": "texto del boton/menu/control"}],
          timeout_s=40)
    def _mesa_invocar(args, ctx):
        texto = (args or "").strip().strip("\"'")
        if not texto:
            return _err("mesa_invocar", "falta la etiqueta")
        try:
            r = M.invocar(texto)
            if not r.get("ok"):
                return _err("mesa_invocar", r.get("error"))
            return "RESULTADO mesa_invocar: %s %r (%s)" % (r.get("metodo", ""), r.get("encontrado", texto), r.get("tipo", ""))
        except Exception as exc:
            return _err("mesa_invocar", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_teclear ----------------------------------------------------
    @tool("mesa_teclear",
          "mesa_teclear <texto> | tecla=intro | atajo=ctrl+s [| veces=N]  -- teclea en la ventana activa de la mesa",
          desc="Escribe texto, pulsa una tecla (tecla=intro|escape|tab|arriba|abajo|f1..f12...) o intenta una "
               "combinacion (atajo=ctrl+s). El texto y las teclas van por mensajes (funcionan sin robar el "
               "teclado del dueno). AVISO: los atajos con modificadores no siempre los ve la app (miran el "
               "teclado fisico); si un atajo no hace nada, usa mesa_invocar con la etiqueta del menu.",
          params=[{"nombre": "texto", "tipo": "string", "requerido": False, "descripcion": "texto a escribir"},
                  {"nombre": "tecla", "tipo": "string", "requerido": False, "clave": True, "descripcion": "una tecla con nombre"},
                  {"nombre": "atajo", "tipo": "string", "requerido": False, "clave": True, "descripcion": "combinacion tipo ctrl+s"},
                  {"nombre": "veces", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "repeticiones de la tecla"}],
          timeout_s=40)
    def _mesa_teclear(args, ctx):
        texto, o = PC.partir_args(args, _CL_TECLEAR)
        try:
            if o.get("atajo"):
                r = M.atajo(o["atajo"])
                if not r.get("ok"):
                    return _err("mesa_teclear", r.get("error"))
                return "RESULTADO mesa_teclear atajo %s%s" % (o["atajo"], (" · " + r["aviso"]) if r.get("aviso") else "")
            if o.get("tecla"):
                r = M.tecla(o["tecla"], veces=PC.entero(o.get("veces"), 1, 1, 200))
                if not r.get("ok"):
                    return _err("mesa_teclear", r.get("error"))
                return "RESULTADO mesa_teclear tecla %s x%d" % (o["tecla"], r["pulsaciones"])
            if not texto:
                return _err("mesa_teclear", "da <texto>, o tecla=<nombre>, o atajo=<combo>")
            r = M.escribir(texto)
            if not r.get("ok"):
                return _err("mesa_teclear", r.get("error"))
            return "RESULTADO mesa_teclear: %d caracteres escritos en la ventana activa" % r["chars"]
        except Exception as exc:
            return _err("mesa_teclear", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_ventanas ---------------------------------------------------
    @tool("mesa_ventanas",
          "mesa_ventanas [activar <hwnd>]  -- lista las ventanas de la mesa (o activa una para teclear/clicar)",
          desc="Lista las ventanas que viven en la mesa (escritorio propio) con su hwnd, titulo y rectangulo. "
               "Con 'activar <hwnd>' fija cual recibe el teclado y es el foco de mesa_teclear.",
          params=[{"nombre": "accion", "tipo": "string", "requerido": False, "descripcion": "activar <hwnd> (opcional)"}],
          timeout_s=30)
    def _mesa_ventanas(args, ctx):
        toks = (args or "").split()
        try:
            if toks and toks[0].lower() == "activar" and len(toks) > 1:
                try:
                    h = int(toks[1])
                except Exception:
                    return _err("mesa_ventanas", "activar <hwnd numerico>")
                if not EP.ventana_viva(h):
                    return _err("mesa_ventanas", "hwnd %d no esta vivo" % h)
                if h not in {w["hwnd"] for w in M._ventanas_dict()}:
                    # solo ventanas de la mesa: un hwnd del terminal o del
                    # navegador del dueno pasaba y mesa_teclear le escribia
                    return _err("mesa_ventanas", "hwnd %d no es una ventana de la mesa (solo se activan "
                                "las del escritorio propio, nunca las del usuario)" % h)
                M.fijar_activa(h)
                M.guardar_estado()
                return "RESULTADO mesa_ventanas: activa ahora hwnd %d (%r)" % (h, EP.titulo_ventana(h))
            vs = M._ventanas_dict()
            act = M.activa()
            if not vs:
                return "RESULTADO mesa_ventanas: la mesa esta vacia (lanza algo con mesa_lanzar)"
            lineas = []
            for w in vs:
                marca = " *ACTIVA*" if w["hwnd"] == act else ""
                r = w["rect"]
                lineas.append("hwnd %d%s · %r · %dx%d @%d,%d" % (w["hwnd"], marca, w["titulo"], r[2], r[3], r[0], r[1]))
            return "RESULTADO mesa_ventanas (%d):\n%s" % (len(vs), "\n".join(lineas))
        except Exception as exc:
            return _err("mesa_ventanas", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_pantalla ---------------------------------------------------
    @tool("mesa_pantalla",
          "mesa_pantalla [abrir | cerrar] [| fps=6] [| escala=0.42]  -- la pantallita en vivo del segundo puesto",
          desc="Abre o cierra la PANTALLITA en vivo: una ventana pequena, siempre encima, en el escritorio del "
               "dueno, que muestra a unos fps lo que hace el puntero virtual de Cognia en la mesa. Sin argumento, "
               "abre. Se abre sola con mesa_lanzar.",
          params=[{"nombre": "accion", "tipo": "string", "requerido": False, "descripcion": "abrir (def) | cerrar"},
                  {"nombre": "fps", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "cuadros por segundo (def 6)"},
                  {"nombre": "escala", "tipo": "number", "requerido": False, "clave": True, "descripcion": "escala de la pantallita (def 0.42)"}],
          timeout_s=30)
    def _mesa_pantalla(args, ctx):
        accion, o = PC.partir_args(args, _CL_PANTALLA)
        accion = (accion or "abrir").strip().lower()
        try:
            if accion in ("cerrar", "off", "quitar"):
                r = M.pantalla_cerrar()
                return "RESULTADO mesa_pantalla: %s" % ("cerrada" if r.get("cerrada") else "no habia ninguna abierta")
            fps = PC.entero(o.get("fps"), 6, 1, 20)
            try:
                escala = float(o.get("escala") or 0.42)
            except Exception:
                escala = 0.42
            r = M.pantalla_abrir(fps=fps, escala=escala)
            if not r.get("ok"):
                return _err("mesa_pantalla", r.get("error"))
            return "RESULTADO mesa_pantalla: %s (pid %s) — el dueno ya ve la mesa en vivo" % (
                "ya estaba abierta" if r.get("ya") else "abierta", r.get("pid"))
        except Exception as exc:
            return _err("mesa_pantalla", "%s: %s" % (type(exc).__name__, exc))

    # ---- mesa_estado -----------------------------------------------------
    @tool("mesa_estado",
          "mesa_estado  -- puntero, ventanas de la mesa y si la pantallita esta abierta",
          desc="Estado del segundo puesto: disponibilidad, posicion del puntero virtual, ventanas de la mesa, "
               "cual esta activa y si la pantallita en vivo esta abierta.",
          params=[], timeout_s=20)
    def _mesa_estado(args, ctx):
        try:
            e = M.estado()
            if not e["disponible"]:
                return "mesa: NO disponible — %s" % e.get("motivo", "")
            vs = e.get("ventanas", [])
            lin = "; ".join("%r (hwnd %d)" % (w["titulo"], w["hwnd"]) for w in vs) or "vacia"
            u = e.get("ultimo") or {}
            return ("RESULTADO mesa_estado: %s · escritorio '%s' · puntero %d,%d · pantallita %s · "
                    "%d ventana(s): %s%s"
                    % ("activa" if e["activo"] else "escritorio apagado", e.get("escritorio"),
                       e["puntero"]["x"], e["puntero"]["y"],
                       "ABIERTA (pid %s)" % e["pantalla_pid"] if e["pantalla_abierta"] else "cerrada",
                       len(vs), lin,
                       ("\nultimo: %s %s" % (u.get("accion"), u.get("detalle", "")) if u.get("accion") else "")))
        except Exception as exc:
            return _err("mesa_estado", "%s: %s" % (type(exc).__name__, exc))
