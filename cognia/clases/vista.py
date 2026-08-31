# -*- coding: utf-8 -*-
"""
cognia/clases/vista.py
======================
EL CUADERNO VIRTUAL: un solo HTML donde el duenio ve todo lo que ha dado en
clase, por materia, y lo lee como un cuaderno de verdad.

POR QUE UN FICHERO SUELTO Y NO UN SERVIDOR. Es el patron de vista de la casa
(memory/memorias_view.py, agent/flujoteca_view.py): se escribe a ~/.cognia/ y
se abre con webbrowser, sin CDN ni red. Aqui ademas ese formato es el PRODUCTO
y no una comodidad: el cuaderno de un curso se manda por correo, se guarda en
un pendrive y se abre dentro de dos anios en otro ordenador. Por eso las
imagenes y los clips viajan EMBEBIDOS como data: URI -- un <img src="fisica/
pizarra_0003.png"> convierte el cuaderno en una carpeta que se rompe en cuanto
alguien mueve un fichero.

EL LIMITE DE ESO, DECLARADO. base64 engorda 4/3, y una jornada con 40 fotos de
pizarra a 3 MB seria un HTML de 160 MB que ningun navegador abre comodo. Hay
dos topes (TOPE_ADJUNTO por fichero y TOPE_TOTAL para la pagina entera) y lo
que no cabe NO desaparece: se enlaza con file:// y la propia pagina dice, en
esa entrada, que ese adjunto no viaja con el HTML y por que. El fallo tipico de
este repo es el vacio silencioso; una foto que falta y no se explica es
exactamente eso.

APUNTES vs TRANSCRIPCION. El cuaderno son los APUNTES; la transcripcion es la
FUENTE. Por eso el resumen, las claves, las formulas y lo que entra en examen
se ven abiertos y la transcripcion entera va en un <details> plegado. Aun asi
la transcripcion cuenta para el buscador: el duenio busca "efecto Doppler" y
tiene que caer la clase donde el profesor lo dijo, aunque no lo apuntara nadie.

SEGURIDAD. Todo lo que se pinta viaja como DATO en un JSON embebido y se mete
en el DOM con textContent o con setAttribute sobre plantillas <template>: la
pagina no tiene ni un innerHTML. Y el JSON va con TODOS los "<" escapados como
\\u003c, no solo el "</" -- medido en este repo el 2026-08-29: "<!--" y
"<script" meten al tokenizador en 'script data escaped' y en ese estado el
</script> de la plantilla ya no cierra el bloque, se traga el resto del
documento y la pagina queda muda. Una nota de clase que copie codigo HTML es
el caso NORMAL, no un ataque.

Sin modelo. Esta vista no llama al LLM: pinta lo que ya hay en el cuaderno.
Los apuntes (titulo, resumen, claves) los produce quien los escribio en
apuntes.json; aqui si no estan, la sesion se ve igual con su linea de tiempo.
"""

from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
import time
from pathlib import Path

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua

log = logging.getLogger(__name__)

__all__ = ["render_html", "construir", "export",
           "TOPE_ADJUNTO", "TOPE_TOTAL"]

# Topes de embebido, en bytes del fichero ORIGINAL (el data: URI ocupa ~4/3).
# 4 MB cubre de sobra una foto de pizarra del movil ya recortada y un clip de
# voz de varios minutos; 64 MB de presupuesto total deja un curso entero
# dentro de un HTML que Chrome y Firefox abren sin pelear.
TOPE_ADJUNTO = 4 * 1024 * 1024
TOPE_TOTAL = 64 * 1024 * 1024

# Extensiones que se embeben, con su MIME. Es una lista CERRADA a proposito:
# el src de un <img>/<audio> se construye con esto, y adivinar el MIME con
# mimetypes (que en Windows sale del registro y varia entre maquinas) haria
# que el mismo cuaderno se viera distinto en dos ordenadores.
_MIME_IMAGEN = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
_MIME_AUDIO = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
               ".oga": "audio/ogg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
               ".flac": "audio/flac", ".webm": "audio/webm"}

# Etiqueta legible por tipo de entrada. El duenio no tiene por que saber que
# 'referencia' es un tipo del modelo de datos.
_ETIQUETA_TIPO = {
    cua.TIPO_NOTA: "Nota",
    cua.TIPO_IMAGEN: "Imagen",
    cua.TIPO_AUDIO: "Clip",
    cua.TIPO_REFERENCIA: "Referencia",
    cua.TIPO_MARCA: "Marca",
}

_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")

# Como se leen los apuntes. Los escribe OTRO modulo (apuntes.json), asi que
# aqui se aceptan varias ortografias por campo: si manianas alguien guarda
# "puntos_clave" en vez de "claves", una tabla de un solo nombre dejaria la
# ficha vacia SIN decir nada -- otra vez el vacio silencioso. Y lo que no
# encaje en ninguna fila no se tira: cae en 'otros' y se ve igual.
_CAMPOS_APUNTES = (
    ("titulo", ("titulo", "title"), "texto"),
    ("resumen", ("resumen", "sumario", "summary"), "texto"),
    ("claves", ("claves", "puntos_clave", "puntos", "clave", "ideas"), "lista"),
    ("definiciones", ("definiciones", "conceptos", "vocabulario"), "lista"),
    ("formulas", ("formulas", "ecuaciones"), "lista"),
    ("deberes", ("deberes", "tareas", "ejercicios", "homework"), "lista"),
    ("examen", ("examen", "entra_en_examen", "evaluable", "para_el_examen"), "lista"),
    ("dudas", ("dudas", "preguntas"), "lista"),
)

# Titulo visible de cada ficha de apuntes, en el orden en que se pintan.
_ORDEN_FICHAS = (("claves", "Puntos clave"), ("definiciones", "Definiciones"),
                 ("formulas", "Formulas"), ("examen", "Entra en el examen"),
                 ("deberes", "Deberes"), ("dudas", "Dudas"))


# ── formato de tiempos ───────────────────────────────────────────────────────

def _duracion(segundos: float) -> str:
    """'1 h 05 min' / '42 min' / '38 s'. Se redondea a la unidad que el duenio
    usa para hablar de una clase; poner '3245 s' seria exacto e inutil."""
    s = int(max(0.0, segundos))
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%d min" % (s // 60)
    return "%d h %02d min" % (s // 3600, (s % 3600) // 60)


def _fecha_de(jornada: cua.Jornada) -> tuple:
    """(texto legible, epoch de inicio). El epoch de la jornada manda; si
    vale 0 (una jornada importada o a medio cerrar) se cae al NOMBRE, que es
    la fecha en ISO. Preferir el nombre siempre seria peor: la jornada '-2'
    del mismo dia perderia su hora."""
    epoch = float(getattr(jornada, "inicio_epoch", 0.0) or 0.0)
    if epoch > 0:
        tm = time.localtime(epoch)
        return "%s %s" % (_DIAS[tm.tm_wday], time.strftime("%d/%m/%Y", tm)), epoch
    try:
        tm = time.strptime(jornada.nombre[:10], "%Y-%m-%d")
        return "%s %s" % (_DIAS[tm.tm_wday], time.strftime("%d/%m/%Y", tm)), 0.0
    except ValueError:
        # Nombre de jornada que no es una fecha: se ensenia crudo antes que
        # inventar un dia que el duenio no reconoceria.
        return jornada.nombre, 0.0


def _reloj(epoch: float, t: float) -> str:
    """Hora de pared de un instante de la jornada, o '' si no hay epoch. Los
    't' del cuaderno son segundos desde el inicio, no horas: sin el epoch no
    se puede inventar una hora."""
    if epoch <= 0:
        return ""
    return time.strftime("%H:%M", time.localtime(epoch + t))


def _desplazamiento(t: float) -> str:
    """'+12:34' desde el inicio de la sesion. Es lo unico que siempre existe,
    y es lo que cuadra con el audio guardado."""
    s = int(max(0.0, t))
    return "+%d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60) if s >= 3600 \
        else "+%02d:%02d" % (s // 60, s % 60)


# ── apuntes ──────────────────────────────────────────────────────────────────

def _lista(valor) -> list:
    """Un campo de apuntes normalizado a lista de lineas. Puede llegar como
    lista (lo normal), como parrafo con saltos, o como dict {concepto: def}
    -- las tres formas son razonables y las tres se han visto al generar
    apuntes con un modelo."""
    if valor is None or valor == "":
        return []
    if isinstance(valor, dict):
        return ["%s: %s" % (k, v) for k, v in valor.items()]
    if isinstance(valor, (list, tuple)):
        fuera = []
        for v in valor:
            if isinstance(v, dict):
                fuera += ["%s: %s" % (k, x) for k, x in v.items()]
            elif str(v).strip():
                fuera.append(str(v).strip())
        return fuera
    return [ln.strip() for ln in str(valor).splitlines() if ln.strip()]


def _leer_apuntes(crudo: dict) -> dict:
    """Los apuntes de una sesion, con los nombres de campo unificados y SIN
    perder nada: lo que no reconozco va a 'otros' con su clave original."""
    crudo = crudo if isinstance(crudo, dict) else {}
    fuera = {"titulo": "", "resumen": "", "otros": []}
    usadas = set()
    for destino, alias, forma in _CAMPOS_APUNTES:
        valor = None
        for a in alias:
            usadas.add(a)
            if a in crudo and crudo[a] not in (None, "", [], {}):
                valor = crudo[a]
                # Se para en el PRIMER alias con contenido; si por lo que sea
                # vinieran dos rellenos, el segundo no se pierde: no queda
                # marcado como usado y cae en 'otros' con su nombre.
                break
        if forma == "texto":
            fuera[destino] = str(valor).strip() if valor else ""
        else:
            fuera[destino] = _lista(valor)
    for k, v in crudo.items():
        if k in usadas or v in (None, "", [], {}):
            continue
        fuera["otros"].append({"k": str(k), "v": _lista(v)})
    return fuera


# ── adjuntos ─────────────────────────────────────────────────────────────────

def _embeber(jornada: str, nombre: str, tipo: str, gasto: dict) -> dict:
    """{'src','enlace','aviso'} para una imagen o un clip.

    Devuelve SIEMPRE algo pintable: o el data: URI, o un enlace file:// con el
    motivo por el que no viaja dentro. Ninguna rama se traga el fallo en
    silencio -- la pagina ensenia el aviso y ademas queda en el log.
    """
    fuera = {"src": "", "enlace": "", "aviso": "", "bytes": 0}
    ruta = alm.ruta_adjunto(jornada, nombre)   # _seguro() ya impide salir de la carpeta
    if not ruta.is_file():
        fuera["aviso"] = "el adjunto '%s' ya no esta en disco" % nombre
        log.warning("clases.vista: adjunto ausente %s", ruta)
        return fuera
    tabla = _MIME_IMAGEN if tipo == cua.TIPO_IMAGEN else _MIME_AUDIO
    mime = tabla.get(ruta.suffix.lower())
    try:
        tam = ruta.stat().st_size
    except OSError as exc:
        fuera["aviso"] = "no pude medir '%s': %s" % (nombre, exc)
        log.warning("clases.vista: stat fallo en %s: %s", ruta, exc)
        return fuera
    fuera["enlace"] = ruta.as_uri()
    if mime is None:
        fuera["aviso"] = ("'%s' no es un formato que sepa embeber (%s); queda "
                          "como enlace a este ordenador" % (nombre, ruta.suffix or "sin extension"))
        return fuera
    if tam > TOPE_ADJUNTO:
        fuera["aviso"] = ("'%s' pesa %.1f MB y el tope por adjunto son %.0f MB: "
                          "no viaja dentro del HTML, solo el enlace"
                          % (nombre, tam / 1048576.0, TOPE_ADJUNTO / 1048576.0))
        return fuera
    if gasto["usado"] + tam > TOPE_TOTAL:
        fuera["aviso"] = ("la pagina ya lleva %.0f MB embebidos (tope %.0f MB): "
                          "'%s' queda como enlace"
                          % (gasto["usado"] / 1048576.0, TOPE_TOTAL / 1048576.0, nombre))
        return fuera
    try:
        crudo = ruta.read_bytes()
    except OSError as exc:
        fuera["aviso"] = "no pude leer '%s': %s" % (nombre, exc)
        log.warning("clases.vista: lectura fallo en %s: %s", ruta, exc)
        return fuera
    gasto["usado"] += len(crudo)
    fuera["bytes"] = len(crudo)
    fuera["src"] = "data:%s;base64,%s" % (mime, base64.b64encode(crudo).decode("ascii"))
    fuera["enlace"] = ""   # esta dentro: el enlace al disco solo confundiria
    return fuera


# ── construccion de los datos ────────────────────────────────────────────────

def _sesion_a_dict(s: cua.Sesion, jor: cua.Jornada, gasto: dict, avisos: list) -> dict:
    fecha, epoch = _fecha_de(jor)
    ap = _leer_apuntes(s.apuntes)
    linea, dicho, busca = [], [], [s.materia, jor.nombre, fecha]

    for e in s.entradas:
        rel = max(0.0, e.t - s.t0)
        if e.tipo == cua.TIPO_TRANSCRIPCION:
            if e.texto:
                dicho.append({"hora": _reloj(epoch, e.t), "marca": _desplazamiento(rel),
                              "texto": e.texto})
                busca.append(e.texto)
            continue
        item = {"tipo": e.tipo, "etiqueta": _ETIQUETA_TIPO.get(e.tipo, e.tipo),
                "hora": _reloj(epoch, e.t), "marca": _desplazamiento(rel),
                "texto": e.texto, "importante": bool(e.importante),
                "fuente": e.fuente, "src": "", "enlace": "", "aviso": ""}
        if e.adjunto and e.tipo in (cua.TIPO_IMAGEN, cua.TIPO_AUDIO):
            medio = _embeber(s.jornada or jor.nombre, e.adjunto, e.tipo, gasto)
            item.update({k: medio[k] for k in ("src", "enlace", "aviso")})
            item["adjunto"] = e.adjunto
            if medio["aviso"]:
                avisos.append("%s · %s" % (s.materia, medio["aviso"]))
        busca.append(e.texto)
        linea.append(item)

    busca += [ap["titulo"], ap["resumen"]]
    for clave, _ in _ORDEN_FICHAS:
        busca += ap[clave]
    for otro in ap["otros"]:
        busca += otro["v"]

    return {
        "materia": s.materia, "jornada": s.jornada or jor.nombre,
        "fecha": fecha, "hora": _reloj(epoch, s.t0), "hora_fin": _reloj(epoch, s.t1),
        "duracion": _duracion(s.duracion), "segundos": s.duracion,
        "confianza": round(float(s.confianza or 0.0), 2), "por": s.por,
        "apuntes": ap, "linea": linea, "dicho": dicho,
        "n_dicho": len(dicho),
        # El heno del buscador se calcula AQUI y no en JS: asi la busqueda
        # alcanza la transcripcion aunque este plegada, y cuesta lo mismo
        # buscar en un cuaderno de un dia que en el de un curso entero.
        "busca": " ".join(x for x in busca if x).lower(),
    }


def construir(materias=None) -> dict:
    """El dict que se embebe en la pagina: el cuaderno entero, por materia.

    `materias` es una lista de nombres para filtrar (se la pasa tal cual a
    cuaderno.cuaderno). None = todo.
    """
    t0 = time.time()
    avisos: list = []
    gasto = {"usado": 0}
    try:
        agrupado = cua.cuaderno(materias)
    except Exception as exc:
        # La vista tiene que ABRIR aunque el cuaderno este roto: es justo la
        # herramienta a la que el duenio va cuando algo no cuadra. Se abre
        # vacia DICIENDO por que, que no es lo mismo que abrirse vacia.
        log.warning("clases.vista: no pude leer el cuaderno: %s", exc)
        return {"materias": [], "total_sesiones": 0, "bytes_embebidos": 0,
                "avisos": ["no pude leer el cuaderno: %s: %s"
                           % (type(exc).__name__, exc)],
                "generado": time.strftime("%d/%m/%Y %H:%M"), "ms": 0}

    jornadas: dict = {}   # cache: una jornada la comparten todas sus sesiones
    materias_out = []
    total = 0
    for nombre_materia in sorted(agrupado, key=lambda m: m.lower()):
        sesiones = []
        for s in agrupado[nombre_materia]:
            clave = s.jornada
            if clave not in jornadas:
                try:
                    jornadas[clave] = cua.cargar_jornada(clave)
                except Exception as exc:
                    log.warning("clases.vista: jornada %s ilegible: %s", clave, exc)
                    avisos.append("no pude leer el estado de la jornada %s: %s"
                                  % (clave, exc))
                    jornadas[clave] = cua.Jornada(nombre=clave)
            sesiones.append(_sesion_a_dict(s, jornadas[clave], gasto, avisos))
        segundos = sum(x["segundos"] for x in sesiones)
        total += len(sesiones)
        materias_out.append({
            "nombre": nombre_materia, "n": len(sesiones),
            "segundos": segundos, "horas": _duracion(segundos),
            "sesiones": sesiones,
        })
    # La materia con mas horas primero: es la que el duenio abre mas veces.
    materias_out.sort(key=lambda m: (-m["segundos"], m["nombre"].lower()))
    return {"materias": materias_out, "total_sesiones": total,
            "bytes_embebidos": gasto["usado"], "avisos": avisos,
            "generado": time.strftime("%d/%m/%Y %H:%M"),
            "ms": int((time.time() - t0) * 1000)}


# ── la pagina ────────────────────────────────────────────────────────────────

_HTML = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title>
<style>
/* Claro por defecto (un cuaderno se lee sobre papel) y oscuro cuando el
   sistema lo pide. Los tokens se REDEFINEN, no se invierten: los contrastes
   estan elegidos uno a uno en los dos modos. El boton de tema manda sobre el
   sistema y se recuerda en localStorage. */
:root{
  --fondo:#fbfaf7; --papel:#ffffff; --panel:#f2f1ec; --borde:#dcd9d0;
  --texto:#1f2328; --texto2:#6b6a63; --acento:#0969da; --acento2:#0550ae;
  --marca:#9a6700; --marcafondo:#fff4d6; --sombra:0 1px 3px rgba(31,35,40,.10);
}
@media (prefers-color-scheme: dark){
  :root:not([data-tema="claro"]){
    --fondo:#0d1117; --papel:#161b22; --panel:#1c2128; --borde:#30363d;
    --texto:#e6edf3; --texto2:#9198a1; --acento:#58a6ff; --acento2:#79c0ff;
    --marca:#e3b341; --marcafondo:#332a10; --sombra:0 1px 3px rgba(0,0,0,.45);
  }
}
:root[data-tema="oscuro"]{
  --fondo:#0d1117; --papel:#161b22; --panel:#1c2128; --borde:#30363d;
  --texto:#e6edf3; --texto2:#9198a1; --acento:#58a6ff; --acento2:#79c0ff;
  --marca:#e3b341; --marcafondo:#332a10; --sombra:0 1px 3px rgba(0,0,0,.45);
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--fondo);color:var(--texto);display:flex;flex-direction:column;
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:12px 20px;
  background:var(--panel);border-bottom:1px solid var(--borde);position:sticky;top:0;z-index:10}
h1{margin:0;font-size:16px;font-weight:600;letter-spacing:-.01em}
h1 span{color:var(--texto2);font-weight:400;font-size:13px;margin-left:8px}
#buscar{flex:1;min-width:200px;max-width:480px;padding:7px 12px;border-radius:6px;
  border:1px solid var(--borde);background:var(--papel);color:var(--texto);font-size:14px}
#buscar:focus{outline:none;border-color:var(--acento)}
button.btn{padding:7px 12px;border-radius:6px;border:1px solid var(--borde);
  background:var(--papel);color:var(--texto);font-size:13px;cursor:pointer}
button.btn:hover{border-color:var(--acento);color:var(--acento)}
#avisos{padding:8px 20px;background:var(--marcafondo);color:var(--texto);
  border-bottom:1px solid var(--borde);font-size:13px}
#avisos ul{margin:6px 0 0;padding-left:20px}
main{flex:1;display:flex;min-height:0}
nav{width:230px;flex:0 0 230px;overflow-y:auto;padding:14px 10px;
  background:var(--panel);border-right:1px solid var(--borde)}
nav h2{margin:0 0 8px 8px;font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--texto2)}
.mat{display:block;width:100%;text-align:left;margin-bottom:3px;padding:7px 10px;
  border:1px solid transparent;border-radius:7px;background:none;color:var(--texto);
  font:inherit;cursor:pointer}
.mat:hover{background:var(--papel)}
.mat[aria-pressed="true"]{background:var(--papel);border-color:var(--acento);color:var(--acento)}
.mat .mn{display:block;font-weight:600;font-size:14px}
.mat .mc{display:block;font-size:12px;color:var(--texto2)}
#hojas{flex:1;overflow-y:auto;padding:18px 24px 60px}
.sesion{background:var(--papel);border:1px solid var(--borde);border-radius:10px;
  box-shadow:var(--sombra);padding:16px 18px;margin:0 auto 16px;max-width:900px}
.sesion h3{margin:0 0 2px;font-size:17px;line-height:1.35}
.meta{display:flex;flex-wrap:wrap;gap:12px;color:var(--texto2);font-size:12.5px;
  font-variant-numeric:tabular-nums;margin-bottom:10px}
.resumen{margin:0 0 12px;font-size:15px}
.fichas{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));margin-bottom:14px}
.ficha{border:1px solid var(--borde);border-radius:8px;padding:8px 12px;background:var(--fondo)}
.ficha h5{margin:0 0 4px;font-size:11px;font-weight:600;letter-spacing:.05em;
  text-transform:uppercase;color:var(--texto2)}
.ficha ul{margin:0;padding-left:18px;font-size:14px}
.ficha.examen{border-color:var(--marca);background:var(--marcafondo)}
h4.th{margin:14px 0 6px;font-size:11px;font-weight:600;letter-spacing:.05em;
  text-transform:uppercase;color:var(--texto2)}
ol.linea{list-style:none;margin:0;padding:0}
.ent{display:flex;gap:12px;padding:7px 8px;border-left:2px solid var(--borde);margin-bottom:4px}
.ent .marca{flex:0 0 96px;color:var(--texto2);font-size:12px;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.ent .cuerpo{flex:1;min-width:0}
.ent .tipo{display:inline-block;font-size:11px;padding:0 7px;border-radius:20px;
  border:1px solid var(--borde);color:var(--texto2);margin-right:6px}
.ent .txt{white-space:pre-wrap;word-break:break-word}
.ent.imp{border-left-color:var(--marca);background:var(--marcafondo)}
.ent.imp .tipo{border-color:var(--marca);color:var(--marca)}
.aviso{color:var(--marca);font-size:12.5px;margin-top:4px}
.aviso a{color:inherit}
img.adj{display:block;max-width:100%;height:auto;margin-top:6px;border-radius:8px;
  border:1px solid var(--borde)}
audio.adj{display:block;width:100%;max-width:420px;margin-top:6px}
details.trans{margin-top:12px;border-top:1px dashed var(--borde);padding-top:8px}
details.trans summary{cursor:pointer;color:var(--texto2);font-size:13px}
.tt{margin-top:8px;font-size:13.5px;color:var(--texto2);max-height:60vh;overflow-y:auto}
.tt p{margin:0 0 4px;display:flex;gap:10px}
.tt .m{flex:0 0 88px;font-variant-numeric:tabular-nums}
.vacio{max-width:900px;margin:40px auto;text-align:center;color:var(--texto2)}
footer{padding:7px 20px;background:var(--panel);border-top:1px solid var(--borde);
  color:var(--texto2);font-size:12px;display:flex;gap:16px;flex-wrap:wrap}
@media(max-width:820px){
  main{flex-direction:column}
  nav{width:auto;flex:0 0 auto;border-right:none;border-bottom:1px solid var(--borde);
    display:flex;flex-wrap:wrap;gap:4px}
  nav h2{display:none} .mat{width:auto}
}
/* Imprimir: el cuaderno en papel es un caso de uso real (llevarlo a un examen).
   Se va todo lo que no es contenido, se quitan las sombras y ninguna sesion se
   parte por la mitad entre dos hojas. */
@media print{
  header,nav,footer,#avisos{display:none!important}
  body,#hojas{display:block;overflow:visible}
  #hojas{padding:0}
  .sesion{break-inside:avoid;page-break-inside:avoid;box-shadow:none;
    border-color:#bbb;max-width:none;margin-bottom:10px}
  .tt{max-height:none;overflow:visible}
  a[href^="file:"]::after{content:" (" attr(href) ")";font-size:10px;color:#666}
}
</style></head><body>
<header>
  <h1>Cuaderno de clase <span id="sub"></span></h1>
  <input id="buscar" type="search" placeholder="Buscar en todo el cuaderno (tecla /)" autocomplete="off">
  <button class="btn" id="btnabrir" type="button">Abrir transcripciones</button>
  <button class="btn" id="btnimp" type="button">Imprimir</button>
  <button class="btn" id="btntema" type="button">Tema</button>
</header>
<div id="avisos" hidden></div>
<main>
  <nav id="materias"><h2>Materias</h2></nav>
  <div id="hojas"></div>
</main>
<footer><span id="pie"></span><span>Se graba y se corrige desde el CLI de Cognia</span></footer>
<noscript><p style="padding:20px">Este cuaderno pinta su contenido con JavaScript
(los datos van dentro del propio fichero). Abrilo en un navegador con JS activado.</p></noscript>

<!-- Plantillas. Todo lo que se pinta se clona de aqui y se rellena con
     textContent / setAttribute: en esta pagina no hay ni un innerHTML, asi que
     una nota de clase con HTML dentro se lee como texto y nunca como etiqueta. -->
<template id="t-materia"><button class="mat" type="button">
  <span class="mn"></span><span class="mc"></span></button></template>
<template id="t-sesion"><article class="sesion">
  <h3 class="tit"></h3>
  <div class="meta"><span class="fecha"></span><span class="hora"></span>
    <span class="dur"></span><span class="jor"></span><span class="conf"></span></div>
  <p class="resumen"></p>
  <div class="fichas"></div>
  <h4 class="th">Linea de tiempo</h4>
  <ol class="linea"></ol>
  <details class="trans"><summary></summary><div class="tt"></div></details>
</article></template>
<template id="t-ficha"><section class="ficha"><h5></h5><ul></ul></section></template>
<template id="t-entrada"><li class="ent"><span class="marca"></span>
  <div class="cuerpo"><div class="cab"><span class="tipo"></span></div>
    <div class="txt"></div><div class="medio"></div><div class="aviso"></div></div></li></template>
<template id="t-imagen"><img class="adj" alt="Imagen del cuaderno" loading="lazy"></template>
<template id="t-audio"><audio class="adj" controls preload="none"></audio></template>
<template id="t-dicho"><p><span class="m"></span><span class="x"></span></p></template>

<script>
const D = __DATOS__;
const $ = s => document.querySelector(s);
const tpl = id => document.getElementById(id).content.firstElementChild.cloneNode(true);

/* Tema: el sistema manda al arrancar (@media prefers-color-scheme cubre el
   caso de que el JS ni corra), el usuario manda despues. */
(function(){
  let t = null; try{ t = localStorage.getItem("cognia_cuaderno_tema"); }catch(e){}
  if(t) document.documentElement.setAttribute("data-tema", t);
})();
$("#btntema").onclick = () => {
  const actual = document.documentElement.getAttribute("data-tema");
  const sistema = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const nuevo = (actual || (sistema ? "oscuro" : "claro")) === "oscuro" ? "claro" : "oscuro";
  document.documentElement.setAttribute("data-tema", nuevo);
  try{ localStorage.setItem("cognia_cuaderno_tema", nuevo); }catch(e){}
};

/* Un src solo puede ser lo que ESTE fichero genero: un data: URI o un file://
   a un adjunto. Filtrarlo aqui cuesta una linea y cierra la unica via por la
   que un dato del cuaderno llega a un atributo en vez de a un textContent. */
function urlSegura(u){ return /^(data:|file:)/i.test(u || "") ? u : ""; }

let materiaActiva = null;

function pintarMaterias(){
  const nav = $("#materias");
  nav.querySelectorAll(".mat").forEach(b => b.remove());
  const todas = tpl("t-materia");
  todas.querySelector(".mn").textContent = "Todas";
  todas.querySelector(".mc").textContent = D.total_sesiones + " sesiones";
  todas.setAttribute("aria-pressed", materiaActiva === null);
  todas.onclick = () => { materiaActiva = null; pintarMaterias(); pintar(); };
  nav.appendChild(todas);
  D.materias.forEach(m => {
    const b = tpl("t-materia");
    b.querySelector(".mn").textContent = m.nombre;
    b.querySelector(".mc").textContent = m.n + (m.n === 1 ? " sesion · " : " sesiones · ") + m.horas;
    b.setAttribute("aria-pressed", materiaActiva === m.nombre);
    b.onclick = () => { materiaActiva = m.nombre; pintarMaterias(); pintar(); };
    nav.appendChild(b);
  });
}

function pintarFichas(cont, ap){
  const filas = __FICHAS__;
  filas.forEach(([clave, titulo]) => {
    const v = ap[clave] || [];
    if(!v.length) return;
    const f = tpl("t-ficha");
    if(clave === "examen") f.classList.add("examen");
    f.querySelector("h5").textContent = titulo;
    const ul = f.querySelector("ul");
    v.forEach(x => { const li = document.createElement("li"); li.textContent = x; ul.appendChild(li); });
    cont.appendChild(f);
  });
  /* Un campo de apuntes que no reconozco se pinta igual con su nombre crudo:
     que apuntes.json cambie una clave no puede borrar contenido de la vista. */
  (ap.otros || []).forEach(o => {
    const f = tpl("t-ficha");
    f.querySelector("h5").textContent = o.k;
    const ul = f.querySelector("ul");
    o.v.forEach(x => { const li = document.createElement("li"); li.textContent = x; ul.appendChild(li); });
    cont.appendChild(f);
  });
}

function pintarEntrada(e){
  const li = tpl("t-entrada");
  if(e.importante) li.classList.add("imp");
  li.querySelector(".marca").textContent = (e.hora ? e.hora + "  " : "") + e.marca;
  li.querySelector(".tipo").textContent = e.etiqueta + (e.importante ? " · importante" : "");
  li.querySelector(".txt").textContent = e.texto || "";
  const medio = li.querySelector(".medio");
  const src = urlSegura(e.src);
  if(e.tipo === "imagen" && src){
    const img = tpl("t-imagen"); img.setAttribute("src", src);
    if(e.texto) img.setAttribute("alt", e.texto);
    medio.appendChild(img);
  } else if(e.tipo === "audio" && src){
    const au = tpl("t-audio"); au.setAttribute("src", src); medio.appendChild(au);
  }
  const av = li.querySelector(".aviso");
  if(e.aviso){
    av.appendChild(document.createTextNode(e.aviso));
    const en = urlSegura(e.enlace);
    if(en){
      av.appendChild(document.createTextNode(" · "));
      const a = document.createElement("a");
      a.setAttribute("href", en); a.textContent = "abrir desde el disco";
      av.appendChild(a);
    }
  }
  return li;
}

function pintarSesion(s){
  const art = tpl("t-sesion");
  art.querySelector(".tit").textContent = s.apuntes.titulo || (s.materia + " · " + s.fecha);
  art.querySelector(".fecha").textContent = s.fecha;
  art.querySelector(".hora").textContent = s.hora ? (s.hora + (s.hora_fin ? "-" + s.hora_fin : "")) : s.materia;
  art.querySelector(".dur").textContent = s.duracion;
  art.querySelector(".jor").textContent = "jornada " + s.jornada;
  /* De donde salio el corte de materia: si lo puso el detector con poca
     confianza, el duenio tiene que poder desconfiar de la etiqueta. */
  art.querySelector(".conf").textContent = s.por
    ? ("materia por " + s.por + (s.confianza ? " (" + s.confianza + ")" : "")) : "";
  const res = art.querySelector(".resumen");
  if(s.apuntes.resumen) res.textContent = s.apuntes.resumen; else res.remove();
  pintarFichas(art.querySelector(".fichas"), s.apuntes);
  const ol = art.querySelector(".linea");
  if(s.linea.length) s.linea.forEach(e => ol.appendChild(pintarEntrada(e)));
  else { art.querySelector("h4.th").remove(); ol.remove(); }
  const det = art.querySelector("details.trans");
  if(s.dicho.length){
    det.querySelector("summary").textContent =
      "Transcripcion de la clase (" + s.n_dicho + " fragmentos)";
    const tt = det.querySelector(".tt");
    s.dicho.forEach(d => {
      const p = tpl("t-dicho");
      p.querySelector(".m").textContent = d.hora || d.marca;
      p.querySelector(".x").textContent = d.texto;
      tt.appendChild(p);
    });
  } else det.remove();
  return art;
}

function pintar(){
  const q = $("#buscar").value.trim().toLowerCase();
  const cont = $("#hojas");
  cont.textContent = "";
  let n = 0;
  D.materias.forEach(m => {
    if(materiaActiva && m.nombre !== materiaActiva) return;
    m.sesiones.forEach(s => {
      if(q && s.busca.indexOf(q) < 0) return;
      cont.appendChild(pintarSesion(s)); n++;
    });
  });
  if(!n){
    const v = document.createElement("div");
    v.className = "vacio";
    v.textContent = D.total_sesiones
      ? "Nada que coincida con lo que buscaste."
      : "El cuaderno esta vacio todavia: graba una clase y vuelve.";
    cont.appendChild(v);
  }
  $("#sub").textContent = n + (n === 1 ? " sesion" : " sesiones") +
    (materiaActiva ? " de " + materiaActiva : "") + (q ? " que coinciden" : "");
}

/* Avisos arriba del todo: un adjunto que no viaja dentro del HTML tiene que
   verse ANTES de que el duenio mande el fichero por correo. */
if((D.avisos || []).length){
  const av = $("#avisos"); av.hidden = false;
  const p = document.createElement("div");
  p.textContent = "Avisos (" + D.avisos.length + "):";
  av.appendChild(p);
  const ul = document.createElement("ul");
  D.avisos.forEach(a => { const li = document.createElement("li"); li.textContent = a; ul.appendChild(li); });
  av.appendChild(ul);
}

$("#buscar").oninput = pintar;
$("#btnabrir").onclick = () => {
  const abrir = document.querySelector("details.trans:not([open])") !== null;
  document.querySelectorAll("details.trans").forEach(d => { d.open = abrir; });
  $("#btnabrir").textContent = abrir ? "Cerrar transcripciones" : "Abrir transcripciones";
};
$("#btnimp").onclick = () => window.print();
/* Imprimir un <details> cerrado imprime solo el titulo: el navegador no
   renderiza el contenido plegado. Se abren antes de imprimir y se deja como
   estaba despues, que es la unica forma de que el papel lleve la clase entera. */
let plegadosAntes = [];
window.addEventListener("beforeprint", () => {
  plegadosAntes = Array.from(document.querySelectorAll("details.trans:not([open])"));
  plegadosAntes.forEach(d => { d.open = true; });
});
window.addEventListener("afterprint", () => { plegadosAntes.forEach(d => { d.open = false; }); });
document.addEventListener("keydown", e => {
  if(e.key === "/" && document.activeElement !== $("#buscar")){ e.preventDefault(); $("#buscar").focus(); }
  if(e.key === "Escape"){ $("#buscar").value = ""; $("#buscar").blur(); pintar(); }
});
/* El peso embebido se dice en la unidad que toca: "0.0 MB" en un cuaderno de
   7 KB parece que las fotos no viajaron, que es exactamente la duda que este
   pie existe para quitar antes de mandar el fichero por correo. */
const emb = D.bytes_embebidos < 1048576
  ? (D.bytes_embebidos / 1024).toFixed(0) + " KB"
  : (D.bytes_embebidos / 1048576).toFixed(1) + " MB";
$("#pie").textContent = D.materias.length + " materias · " + D.total_sesiones +
  " sesiones · " + emb + " de fotos y audio dentro del fichero · generado el " + D.generado;
pintarMaterias(); pintar();
</script></body></html>"""


def render_html(datos, titulo: str = "Cuaderno de clase") -> str:
    """El HTML entero, autocontenido. `datos` es lo que devuelve construir()."""
    if not isinstance(datos, dict):
        raise TypeError("render_html espera el dict de construir(), no %r" % type(datos))
    datos = dict(datos)
    datos.setdefault("materias", [])
    datos.setdefault("total_sesiones", 0)
    datos.setdefault("avisos", [])
    datos.setdefault("bytes_embebidos", 0)
    datos.setdefault("generado", time.strftime("%d/%m/%Y %H:%M"))

    # TODOS los "<" escapados, no solo "</" (ver la cabecera del modulo). Como
    # la sintaxis JSON no usa "<", cada uno esta dentro de una cadena, y ahi
    # < es la MISMA cadena para el parser: el dato no cambia, solo deja
    # de poder tocar al tokenizador de HTML.
    crudo = json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")
    fichas = json.dumps(list(_ORDEN_FICHAS), ensure_ascii=False).replace("<", "\\u003c")
    # El titulo cae dentro de <title>: ahi manda el escape de HTML, no el de JS.
    tit = _html.escape(str(titulo or "Cuaderno de clase"))
    # UNA sola pasada. Encadenar .replace() deja que lo ya sustituido se
    # reinterprete despues: un titulo que contenga "__DATOS__" se comeria el
    # JSON entero (el mismo bug que ya se pago en flujoteca_view).
    trozos = {"__TITULO__": tit, "__DATOS__": crudo, "__FICHAS__": fichas}
    return re.sub("__TITULO__|__DATOS__|__FICHAS__",
                  lambda m: trozos[m.group(0)], _HTML)


def export(path=None, open_browser: bool = True, materias=None) -> Path:
    """Escribe el cuaderno y (por defecto) lo abre. Devuelve la ruta.

    Por defecto va a ~/.cognia/cuaderno.html, como el resto de vistas de la
    casa: un sitio fijo que el duenio ya conoce y del que puede arrastrar el
    fichero a un correo.
    """
    datos = construir(materias)
    destino = Path(path).expanduser() if path else (Path.home() / ".cognia" / "cuaderno.html")
    destino.parent.mkdir(parents=True, exist_ok=True)
    sufijo = (" · " + ", ".join(materias)) if materias else ""
    destino.write_text(render_html(datos, "Cuaderno de clase" + sufijo),
                       encoding="utf-8")
    if open_browser:
        import webbrowser
        try:
            webbrowser.open(destino.as_uri())
        except Exception as exc:
            # El fichero YA esta escrito: que no haya navegador por defecto no
            # puede parecer que la exportacion fallo.
            log.warning("clases.vista: no pude abrir el navegador: %s", exc)
    return destino


if __name__ == "__main__":
    import sys
    ruta = export(open_browser="--no-open" not in sys.argv)
    print("cuaderno -> %s" % ruta)
