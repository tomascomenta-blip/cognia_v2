"""
servidor.py — la API del control remoto (FastAPI + WebSocket).

Sirve la app movil (static/) y expone:
  proyectos/sesiones (CRUD), mensajes (stdin del REPL real), stream por WS,
  comandos con descripciones (para las sugerencias del "/"), saludo por hora,
  output images de los programas generados, estado de la oficina, grafo de
  conocimiento, y los "monitores" (sesiones/REPLs vivos con su PID).
"""

from __future__ import annotations

import json
import queue
import random
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .sesiones import (GestorSesiones, RAIZ_DATOS, cargar_proyectos,
                       guardar_proyectos, registrar_proyecto)

ESTATICOS = Path(__file__).parent / "static"

# Saludos por franja horaria; uno al azar en cada arranque de la app.
_SALUDOS = {
    "madrugada": [
        "¿Trasnochando? Cognia también. ¿En qué trabajamos?",
        "Las mejores ideas salen de madrugada. Cuéntame.",
        "Silencio, café y Cognia. Combinación ganadora.",
    ],
    "manana": [
        "Buenos días. ¿Qué construimos hoy?",
        "Café en mano y a darle. ¿Por dónde empezamos?",
        "Buenos días. Los REPLs están calientes.",
    ],
    "tarde": [
        "Buenas tardes. ¿Seguimos donde lo dejamos?",
        "La tarde rinde si la empujamos. ¿Qué toca?",
        "Buenas tardes. Cognia lista para trabajar.",
    ],
    "noche": [
        "Buenas noches. ¿Un último empujón al proyecto?",
        "La noche es buena para el código. ¿Qué hacemos?",
        "Cognia de guardia nocturna. Tú dirás.",
    ],
}


def _franja() -> str:
    h = time.localtime().tm_hour
    if h < 6:
        return "madrugada"
    if h < 13:
        return "manana"
    if h < 20:
        return "tarde"
    return "noche"


def _comandos() -> list[dict]:
    """Todos los comandos del REPL con su descripcion, para las sugerencias."""
    try:
        from cognia.cli import _CMD_DESCRIPTIONS
        return [{"cmd": c, "desc": d} for c, d in
                sorted(_CMD_DESCRIPTIONS.items())]
    except Exception:
        return []


def _imagenes_recientes(limite: int = 30) -> list[dict]:
    """Las output/input images de los programas generados, mas nuevas primero."""
    try:
        from cognia.program_creator.storage import DEFAULT_STORAGE_DIR
        raiz = Path(DEFAULT_STORAGE_DIR)
    except Exception:
        return []
    encontradas = []
    for png in raiz.glob("*/*/*.png"):
        encontradas.append(png)
    encontradas.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"programa": p.parent.parent.name, "tipo": p.parent.name,
             "nombre": p.name, "ruta": str(p),
             "url": f"/api/imagen?ruta={p}"}
            for p in encontradas[:limite]]


def crear_app() -> FastAPI:
    app = FastAPI(title="Cognia Remoto")
    gestor = GestorSesiones()

    def _proyecto(pid: str) -> dict:
        for pr in cargar_proyectos():
            if pr["id"] == pid:
                return pr
        raise ValueError(f"proyecto desconocido: {pid}")

    # ── app movil ──
    @app.get("/")
    def raiz():
        return FileResponse(ESTATICOS / "index.html")

    # ── saludo por hora ──
    @app.get("/api/saludo")
    def saludo():
        franja = _franja()
        return {"franja": franja, "texto": random.choice(_SALUDOS[franja])}

    # ── proyectos ──
    @app.get("/api/proyectos")
    def proyectos():
        vivos = {v["proyecto"] for v in gestor.vivas()}
        salida = []
        for pr in cargar_proyectos():
            salida.append({**pr,
                           "sesiones": len(gestor.indice(pr["id"])),
                           "activo": pr["id"] in vivos})
        return salida

    @app.post("/api/proyectos")
    def alta_proyecto(cuerpo: dict):
        try:
            return registrar_proyecto(cuerpo.get("ruta", ""))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.delete("/api/proyectos/{pid}")
    def baja_proyecto(pid: str):
        proyectos = [p for p in cargar_proyectos() if p["id"] != pid]
        guardar_proyectos(proyectos)
        return {"ok": True}

    # ── sesiones ──
    @app.get("/api/proyectos/{pid}/sesiones")
    def sesiones(pid: str):
        return gestor.indice(pid)

    @app.post("/api/proyectos/{pid}/sesiones")
    def nueva_sesion(pid: str, cuerpo: dict | None = None):
        s = gestor.crear(_proyecto(pid), (cuerpo or {}).get("titulo", ""))
        return {"id": s.id, "titulo": s.titulo}

    @app.delete("/api/proyectos/{pid}/sesiones/{sid}")
    def borrar_sesion(pid: str, sid: str):
        return {"ok": gestor.borrar(pid, sid)}

    @app.get("/api/proyectos/{pid}/sesiones/{sid}/transcripcion")
    def transcripcion(pid: str, sid: str):
        return gestor.obtener(_proyecto(pid), sid).transcripcion()

    @app.post("/api/proyectos/{pid}/sesiones/{sid}/mensaje")
    def mensaje(pid: str, sid: str, cuerpo: dict):
        texto = (cuerpo.get("texto") or "").strip()
        if not texto:
            return JSONResponse({"error": "mensaje vacio"}, status_code=400)
        gestor.obtener(_proyecto(pid), sid).enviar(texto)
        return {"ok": True}

    # ── stream en vivo ──
    @app.websocket("/ws/{pid}/{sid}")
    async def ws(websocket: WebSocket, pid: str, sid: str):
        await websocket.accept()
        s = gestor.obtener(_proyecto(pid), sid)
        q: queue.Queue = queue.Queue()
        with s.lock:
            s.suscriptores.append(q)
        try:
            import asyncio
            while True:
                try:
                    evento = q.get_nowait()
                    await websocket.send_text(
                        json.dumps(evento, ensure_ascii=False))
                except queue.Empty:
                    await asyncio.sleep(0.15)
        except WebSocketDisconnect:
            pass
        finally:
            with s.lock:
                if q in s.suscriptores:
                    s.suscriptores.remove(q)

    # ── comandos y sugerencias ──
    @app.get("/api/comandos")
    def comandos():
        return _comandos()

    # ── imagenes ──
    @app.get("/api/imagenes")
    def imagenes():
        return _imagenes_recientes()

    @app.get("/api/imagen")
    def imagen(ruta: str):
        p = Path(ruta)
        # solo PNGs de la biblioteca de programas: nada de leer discos ajenos
        try:
            from cognia.program_creator.storage import DEFAULT_STORAGE_DIR
            raiz = Path(DEFAULT_STORAGE_DIR).resolve()
            if raiz not in p.resolve().parents or p.suffix != ".png":
                raise ValueError
        except Exception:
            return JSONResponse({"error": "ruta fuera de la biblioteca"},
                                status_code=403)
        return FileResponse(p)

    # ── paneles: oficina, grafo, monitores ──
    @app.get("/api/oficina")
    def oficina():
        """La oficina vive por-proyecto (oficina_estado.json en su carpeta):
        se agregan los snapshots de todos los proyectos que tengan una."""
        salida = []
        try:
            from cognia.oficina.estado import Oficina
            for pr in cargar_proyectos():
                f = Path(pr["ruta"]) / "oficina_estado.json"
                if f.is_file():
                    snap = Oficina(str(f)).snapshot()
                    salida.append({"proyecto": pr["nombre"],
                                   "metas": snap.get("metas", []),
                                   "tareas": snap.get("tareas", {})})
        except Exception:
            pass
        return salida

    @app.get("/api/grafo")
    def grafo(tema: str = ""):
        try:
            from cognia.knowledge.graph import KnowledgeGraph
            kg = KnowledgeGraph()
            if tema:
                hechos = kg.get_facts(tema)[:30]
                vecinos = kg.get_neighbors(tema)[:30]
                return {"tema": tema, "hechos": hechos, "vecinos": vecinos}
            st = kg.stats()
            recientes = kg.get_all_triples(limit=40)
            return {"stats": st, "triples": recientes}
        except Exception as e:
            return {"error": f"grafo no disponible: {e}"}

    @app.get("/api/monitores")
    def monitores():
        return gestor.vivas()

    # ── grafo VISUAL: nodos+aristas con componentes coloreados por tema ──
    @app.get("/api/grafo_visual")
    def grafo_visual(limite: int = 80):
        try:
            from cognia.knowledge.graph import KnowledgeGraph
            crudos = KnowledgeGraph().get_all_triples(limit=1000)
        except Exception as e:
            return {"error": str(e), "nodos": [], "aristas": []}

        # Muestreo ESTRATIFICADO por relacion: sin esto, un KG dominado por
        # una relacion (665 related_to vs 9 is_a) llenaba el cupo con una
        # sola y los temas por tipo desaparecian del dibujo.
        por_rel: dict[str, list] = {}
        for t in crudos:
            por_rel.setdefault(str(t[1]), []).append(t)
        triples = []
        i = 0
        while len(triples) < limite and any(por_rel.values()):
            for rel in list(por_rel):
                if i < len(por_rel[rel]):
                    triples.append(por_rel[rel][i])
                    if len(triples) >= limite:
                        break
            i += 1

        nombres: dict[str, int] = {}
        aristas = []
        padre: list[int] = []

        def nodo(n: str) -> int:
            if n not in nombres:
                nombres[n] = len(nombres)
                padre.append(nombres[n])
            return nombres[n]

        def raiz(i: int) -> int:
            while padre[i] != i:
                padre[i] = padre[padre[i]]
                i = padre[i]
            return i

        pares = []
        for t in triples:
            s, p, o = str(t[0]), str(t[1]), str(t[2])
            a, b = nodo(s), nodo(o)
            pares.append((a, b))
            aristas.append({"de": a, "a": b, "rel": p})

        # Un super-hub (p. ej. "default", conectado a todo) colapsaria TODOS
        # los temas en uno. Los hubs no fusionan componentes: los temas salen
        # de la estructura real, y el hub se pinta neutro.
        grado: dict[int, int] = {}
        for a, b in pares:
            grado[a] = grado.get(a, 0) + 1
            grado[b] = grado.get(b, 0) + 1
        umbral_hub = max(6, len(pares) // 6)
        hubs = {i for i, g in grado.items() if g >= umbral_hub}
        for a, b in pares:
            if a in hubs or b in hubs:
                continue
            padre[raiz(a)] = raiz(b)

        # Tamano de cada componente sin contar hubs
        tam: dict[int, int] = {}
        for i in range(len(padre)):
            if i not in hubs:
                r = raiz(i)
                tam[r] = tam.get(r, 0) + 1

        # Un KG en estrella (todo colgando de un hub) deja puros singletons:
        # ahi el tema honesto es el TIPO DE RELACION con el hub (is_a,
        # capable_of...), que si agrupa por significado.
        rel_al_hub: dict[int, str] = {}
        for ar in aristas:
            a, b = ar["de"], ar["a"]
            if a in hubs and b not in hubs:
                rel_al_hub.setdefault(b, ar["rel"])
            elif b in hubs and a not in hubs:
                rel_al_hub.setdefault(a, ar["rel"])

        comp_idx: dict = {}
        nodos = []
        for nombre, i in nombres.items():
            if i in hubs:
                nodos.append({"id": i, "nombre": nombre, "tema": -1,
                              "hub": True})
                continue
            r = raiz(i)
            if tam.get(r, 1) > 1:
                clave = ("comp", r)
            else:
                clave = ("rel", rel_al_hub.get(i, "otros"))
            comp = comp_idx.setdefault(clave, len(comp_idx))
            etiqueta = clave[1] if clave[0] == "rel" else ""
            nodos.append({"id": i, "nombre": nombre, "tema": comp,
                          **({"grupo": etiqueta} if etiqueta else {})})
        return {"nodos": nodos, "aristas": aristas,
                "n_temas": len(comp_idx), "hubs": len(hubs)}

    # ── flujos de trabajo (skills del agente): ver y editar ──
    _DIR_FLUJOS = Path(__file__).resolve().parent.parent / "skills"

    @app.get("/api/flujos")
    def flujos():
        salida = []
        for f in sorted(_DIR_FLUJOS.glob("*.md")):
            salida.append({"nombre": f.stem,
                           "contenido": f.read_text(encoding="utf-8")})
        return salida

    @app.put("/api/flujos/{nombre}")
    def guardar_flujo(nombre: str, cuerpo: dict):
        # nombre saneado: solo el stem, sin rutas — el movil no escribe fuera
        # de la carpeta de skills.
        limpio = "".join(c for c in nombre if c.isalnum() or c in "-_")
        if not limpio:
            return JSONResponse({"error": "nombre invalido"}, status_code=400)
        destino = _DIR_FLUJOS / f"{limpio}.md"
        destino.write_text(cuerpo.get("contenido", ""), encoding="utf-8")
        return {"ok": True, "nombre": limpio}

    # ── oficina 3D isometrica: lanzarla para un proyecto y embeberla ──
    _oficina3d: dict = {"proc": None, "puerto": 8766}

    @app.get("/api/oficina3d")
    def oficina3d_estado():
        p = _oficina3d["proc"]
        viva = p is not None and p.poll() is None
        return {"viva": viva, "puerto": _oficina3d["puerto"]}

    @app.post("/api/oficina3d")
    def oficina3d_arrancar(cuerpo: dict):
        import subprocess
        import sys
        p = _oficina3d["proc"]
        if p is not None and p.poll() is None:
            return {"ok": True, "puerto": _oficina3d["puerto"]}
        pid = cuerpo.get("proyecto_id", "")
        try:
            ruta = Path(_proyecto(pid)["ruta"]) if pid else Path.cwd()
        except Exception:
            ruta = Path.cwd()
        estado = ruta / "oficina_estado.json"
        raiz_repo = str(Path(__file__).resolve().parent.parent.parent)
        import os as _os
        env = dict(_os.environ, PYTHONUTF8="1",
                   PYTHONPATH=raiz_repo + _os.pathsep +
                   _os.environ.get("PYTHONPATH", ""))
        # --sin-modelo: el panel es para VER la oficina; el motor con modelo
        # se maneja desde el chat (/oficina) si se quiere.
        # --host 0.0.0.0: el iframe lo abre el MOVIL con la IP del PC en la LAN,
        # no localhost; sin esto la oficina quedaba invisible desde el telefono.
        # stderr a un log (no DEVNULL) para no perder el motivo si el arranque
        # falla en silencio (familia de degradacion silenciosa de Cognia).
        log_ofi = ruta / "oficina3d.log"
        _oficina3d["proc"] = subprocess.Popen(
            [sys.executable, "-m", "cognia.oficina",
             "--puerto", str(_oficina3d["puerto"]), "--host", "0.0.0.0",
             "--estado", str(estado), "--sin-modelo"],
            cwd=str(ruta), env=env,
            stdout=subprocess.DEVNULL,
            stderr=open(log_ofi, "w", encoding="utf-8"))
        return {"ok": True, "puerto": _oficina3d["puerto"]}

    app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")
    return app


def main() -> int:
    import uvicorn
    app = crear_app()
    print("Cognia Remoto en http://0.0.0.0:8777  "
          "(desde el celular: http://<IP-del-PC>:8777)")
    uvicorn.run(app, host="0.0.0.0", port=8777, log_level="warning")
    return 0
