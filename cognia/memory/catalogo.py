# -*- coding: utf-8 -*-
"""
cognia/memory/catalogo.py
=========================
El CATALOGO UNIFICADO de lo que Cognia produce y conserva: una vista, no un
almacen nuevo.

POR QUE EXISTE (2026-08-28)
---------------------------
Cognia guarda cosas en once sitios distintos y con tres formatos de indice:
tablas SQLite en `~/.cognia/cognia_memory.db`, ficheros JSON de indice por
carpeta (`generated_programs/index.json`, `~/.cognia/flujos/indice.json`,
`.skill_usage.json`) y JSONL append-only (papelera, checkpoints, journal de
workflows). Los identificadores no son homogeneos (rowid, slug de directorio,
nombre de fichero, uuid de sesion, lote HHMMSS-hex) y las fechas tampoco (ISO,
epoch float y epoch int conviven). Resultado: el dueno no tiene UN sitio donde
ver "lo que hice", y el mejorador de prompts no puede saber que artefactos
existen ya cuando le piden algo parecido a lo de ayer.

LO QUE ESTE MODULO NO HACE, A PROPOSITO
---------------------------------------
No crea una base nueva, no migra nada y no reescribe ningun indice. Cada
familia se lee con la funcion que YA existe y esta probada
(`storage.list_programs`, `generalizador.listar_flujos`, `skills.load_skills`,
`checkpoints.listar`, `papelera.lotes`...) y se PROYECTA a una fila comun.
Un almacen nuevo aqui seria una cuarta fuente de verdad que se desincroniza
con las otras tres; el propio repo ya documenta que `index.json` de programas
no coincide con el disco (`autoprueba.py:125-129`). La vista no puede
desincronizarse porque no guarda nada.

CONSECUENCIA HONESTA: el catalogo es tan bueno como sus fuentes. Si un indice
miente, el catalogo repite la mentira. Por eso cada fila lleva `fuente` (de
donde salio) y cada familia que falla al leerse deja un aviso VISIBLE en
`Catalogo.avisos` en vez de aparecer como "cero artefactos", que es el fallo
tipico de esta casa: el vacio silencioso.

LA FILA COMUN
-------------
    id          identificador estable DENTRO de su familia (str)
    familia     'programa'|'flujo'|'corrida'|'skill'|'sesion'|'memoria'|
                'nota'|'documento'|'checkpoint'|'papelera'
    titulo      lo que el dueno leeria para reconocerlo
    resumen     una linea de que es
    ruta        ruta en disco si la tiene (str vacio si vive en SQLite)
    creado      ISO 8601 o "" si la fuente no lo guarda
    modificado  ISO 8601 o "" (varias fuentes solo tienen creado: se dice)
    bytes       tamano en disco, o 0
    etiquetas   lista de str
    estado      libre por familia ('verificado', 'cuarentena', 'borrado'...)
    relaciones  [{'familia','id','via'}] hacia otros artefactos
    fuente      que funcion/fichero produjo la fila (para auditar)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["Fila", "Catalogo", "FAMILIAS", "construir", "familias_disponibles",
           "buscar"]

# Orden de presentacion. Es tambien el orden de prioridad cuando hay que
# recortar por presupuesto (el mejorador de prompts pide pocas filas).
FAMILIAS = ("programa", "flujo", "corrida", "skill", "documento", "sesion",
            "nota", "memoria", "checkpoint", "papelera")


def _iso(valor) -> str:
    """Normaliza a ISO 8601 los TRES formatos que conviven en el repo:
    string ISO, epoch float y epoch int. Devuelve "" si no se puede.

    Sin esto el dashboard ordena por fecha mezclando '2026-08-01T10:00' con
    1756... y el orden sale al azar, que es peor que no ordenar."""
    if valor in (None, "", 0):
        return ""
    if isinstance(valor, (int, float)):
        try:
            # Epoch en segundos; los ms se detectan por magnitud (un epoch en
            # segundos del ano 2100 sigue siendo < 4.1e9).
            seg = float(valor)
            if seg > 4.1e12:
                return ""
            if seg > 4.1e9:
                seg = seg / 1000.0
            return datetime.fromtimestamp(seg).isoformat(timespec="seconds")
        except Exception:
            return ""
    texto = str(valor).strip()
    if not texto:
        return ""
    # Ya viene ISO (con o sin zona): se deja tal cual, recortado a segundos.
    try:
        d = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return d.isoformat(timespec="seconds")
    except Exception:
        return texto[:19]


def _parece_vector(texto: str) -> bool:
    """True si el texto es un embedding serializado y no prosa.

    NO es paranoia: medido el 2026-08-28 en la base del dueno,
    `semantic_memory.description` del concepto 'agente_tarea_completada'
    contiene un vector de 384 floats. Algun escritor puso el embedding en la
    columna de la descripcion. El catalogo no puede arreglar eso desde aqui,
    pero tampoco puede volcarle al dueno '[-0.02832898135596632, 0.0523...'
    como si fuera el resumen de un artefacto. Se sustituye por una marca
    honesta Y se avisa: el dato roto tiene que verse, no taparse.
    """
    t = (texto or "").strip()
    if not (t.startswith("[") and len(t) > 40):
        return False
    muestra = t[:200]
    digitos = sum(c.isdigit() or c in "-.,eE " for c in muestra)
    return digitos / len(muestra) > 0.9


def _texto_util(texto: str, avisos: list, que: str) -> str:
    """El texto tal cual, o una marca legible si lo que hay es un vector."""
    if _parece_vector(texto):
        avisos.append(
            "{}: la descripcion guardada es un vector de embeddings, no "
            "texto (bug de datos preexistente en la base). Se muestra una "
            "marca en su lugar.".format(que))
        return "(sin descripcion: la base guardo un vector aqui)"
    return texto or ""


def _mtime_iso(ruta) -> str:
    try:
        p = Path(ruta)
        if p.exists():
            return datetime.fromtimestamp(p.stat().st_mtime).isoformat(
                timespec="seconds")
    except Exception:
        pass
    return ""


# Tope de ficheros que se recorren para pesar un directorio. Un artefacto de
# Cognia (un programa generado, una carpeta de skill) tiene decenas de
# ficheros, no miles: pasar de aqui significa que la ruta NO es un artefacto.
_TOPE_ENTRADAS_DIR = 400


def _bytes_de(ruta) -> int:
    """Tamano en disco, con dos guardas que no son paranoia sino cicatriz.

    (1) Una ruta VACIA no se toca. `Path("")` resuelve a `.`, o sea el cwd:
        pesar un artefacto con la ruta mal leida se convertia en un rglob del
        repositorio entero. Medido aqui: 13 skills con ruta vacia costaban
        44,9 s de los 46 s del catalogo, y el sintoma llegaba como "el
        catalogo es lento", no como "hay una ruta mal".
    (2) El recorrido de directorios esta ACOTADO. Si un directorio pasa el
        tope se devuelve lo sumado hasta ahi en vez de seguir: un numero
        aproximado a tiempo es mejor producto que uno exacto que congela el
        REPL, y esto lo llama el mejorador entre el Enter y el envio.
    """
    texto = str(ruta or "").strip()
    if not texto or texto in (".", ".."):
        return 0
    try:
        p = Path(texto)
        if p.is_file():
            return p.stat().st_size
        if p.is_dir():
            total = 0
            for i, f in enumerate(p.rglob("*")):
                if i >= _TOPE_ENTRADAS_DIR:
                    break
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    continue
            return total
    except Exception:
        pass
    return 0


@dataclass
class Fila:
    id: str
    familia: str
    titulo: str
    resumen: str = ""
    ruta: str = ""
    creado: str = ""
    modificado: str = ""
    bytes: int = 0
    etiquetas: list = field(default_factory=list)
    estado: str = ""
    relaciones: list = field(default_factory=list)
    fuente: str = ""

    def a_dict(self) -> dict:
        return {"id": self.id, "familia": self.familia, "titulo": self.titulo,
                "resumen": self.resumen, "ruta": self.ruta,
                "creado": self.creado, "modificado": self.modificado,
                "bytes": self.bytes, "etiquetas": list(self.etiquetas),
                "estado": self.estado, "relaciones": list(self.relaciones),
                "fuente": self.fuente}


@dataclass
class Catalogo:
    filas: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    ms: int = 0
    familias_ok: list = field(default_factory=list)
    familias_fallidas: list = field(default_factory=list)

    def por_familia(self) -> dict:
        out = {}
        for f in self.filas:
            out.setdefault(f.familia, []).append(f)
        return out

    def conteo(self) -> dict:
        return {fam: len(v) for fam, v in self.por_familia().items()}

    def a_dict(self) -> dict:
        return {"filas": [f.a_dict() for f in self.filas],
                "avisos": list(self.avisos), "ms": self.ms,
                "conteo": self.conteo(),
                "familias_ok": list(self.familias_ok),
                "familias_fallidas": list(self.familias_fallidas)}


# ---------------------------------------------------------------------------
# Lectores por familia. Cada uno: (avisos) -> list[Fila]. NINGUNO lanza; el
# que no puede leer su fuente lo dice en `avisos` y devuelve [].
# ---------------------------------------------------------------------------

def _leer_programas(avisos: list) -> list:
    """Programas generados. Fuente: program_creator/storage.list_programs, que
    ya tolera claves nuevas en el index (fix medido 2026-07-23)."""
    from cognia.program_creator import storage as _st
    filas = []
    for meta in _st.list_programs():
        d = meta.__dict__ if hasattr(meta, "__dict__") else dict(meta)
        directorio = d.get("directory") or d.get("id") or ""
        ruta = ""
        try:
            ruta = str(Path(_st.DEFAULT_STORAGE_DIR) / directorio)
        except Exception:
            pass
        filas.append(Fila(
            id=str(d.get("id") or directorio),
            familia="programa",
            titulo=str(d.get("title") or d.get("id") or directorio),
            resumen=str(d.get("description") or "")[:280],
            ruta=ruta,
            creado=_iso(d.get("created_at")),
            modificado=_mtime_iso(ruta),
            bytes=_bytes_de(ruta),
            etiquetas=[t for t in [d.get("category")] if t],
            # El sello del juez, si verificacion.reflejar_en_index lo dejo.
            estado=("verificado" if d.get("verificado")
                    else ("puntuado" if d.get("total_score") else "")),
            fuente="program_creator/storage.list_programs"))
    return filas


def _leer_flujos(avisos: list) -> list:
    """Flujos aprendidos (recetas). Fuente: flujos.generalizador.listar_flujos
    + el indice de examen, que aporta estado/tasa_exito/ultimo_uso."""
    from cognia.flujos import generalizador as _g
    filas = []
    indice = {}
    try:
        ruta_idx = Path(_g.dir_flujos()) / "indice.json"
        if ruta_idx.exists():
            crudo = json.loads(ruta_idx.read_text(encoding="utf-8"))
            # El indice ha vivido como dict-de-nombres y como lista; se
            # aceptan las dos formas en vez de romper por la que no toque.
            if isinstance(crudo, dict):
                indice = crudo
            elif isinstance(crudo, list):
                indice = {str(e.get("nombre")): e for e in crudo
                          if isinstance(e, dict)}
    except Exception as exc:
        avisos.append("indice de flujos ilegible ({}: {}): las recetas salen "
                      "sin estado de examen".format(type(exc).__name__, exc))
    for d in _g.listar_flujos():
        nombre = str(d.get("nombre") or "")
        extra = indice.get(nombre) or {}
        ruta = str(d.get("ruta") or "")
        etiquetas = [f"{d.get('n_pasos', 0)} pasos"]
        if d.get("n_params"):
            etiquetas.append(f"{d['n_params']} params")
        if extra.get("tasa_exito") is not None:
            etiquetas.append(f"exito {extra['tasa_exito']}")
        filas.append(Fila(
            id=nombre, familia="flujo", titulo=nombre,
            resumen=str(d.get("descripcion") or "")[:280],
            ruta=ruta,
            creado=_iso(extra.get("creado") or extra.get("ts")),
            modificado=_mtime_iso(ruta), bytes=_bytes_de(ruta),
            etiquetas=etiquetas,
            estado=str(extra.get("estado") or d.get("estado") or ""),
            fuente="flujos.generalizador.listar_flujos"))
    return filas


def _leer_corridas(avisos: list, limite: int = 60) -> list:
    """Corridas del motor de workflows: `~/.cognia/workflows/<run_id>/`.

    Se leen del DIRECTORIO y no de un indice porque no hay indice: el motor
    solo escribe el journal. Se toma la primera linea (tipo 'corrida') para
    el nombre y se cuenta el resto para saber cuantos agentes hubo.
    """
    from cognia.agent import workflows as _wf
    filas = []
    try:
        base = Path(_wf._dir_base())
    except Exception as exc:
        avisos.append("no pude localizar el directorio de corridas "
                      "({}: {})".format(type(exc).__name__, exc))
        return filas
    if not base.is_dir():
        return filas
    dirs = sorted((d for d in base.iterdir() if d.is_dir()),
                  key=lambda d: d.name, reverse=True)[:limite]
    for d in dirs:
        journal = d / "journal.jsonl"
        nombre, n_agentes, ts = d.name, 0, ""
        if journal.exists():
            try:
                with journal.open(encoding="utf-8") as fh:
                    for linea in fh:
                        linea = linea.strip()
                        if not linea:
                            continue
                        try:
                            reg = json.loads(linea)
                        except Exception:
                            # Ultima linea truncada por un crash: el formato
                            # es append-only justamente para tolerarlo.
                            continue
                        if reg.get("tipo") == "corrida":
                            nombre = str(reg.get("nombre") or d.name)
                            ts = _iso(reg.get("ts"))
                        elif reg.get("tipo") == "agente":
                            n_agentes += 1
            except Exception as exc:
                avisos.append("journal de {} ilegible ({}: {})".format(
                    d.name, type(exc).__name__, exc))
        filas.append(Fila(
            id=d.name, familia="corrida", titulo=nombre,
            resumen=f"{n_agentes} agentes",
            ruta=str(d), creado=ts or _iso(d.name[:15].replace("-", "T")),
            modificado=_mtime_iso(d), bytes=_bytes_de(d),
            etiquetas=[f"{n_agentes} agentes"],
            fuente="agent/workflows journal"))
    return filas


def _leer_skills(avisos: list) -> list:
    """Skills. Fuente: agent.skills.load_skills (cachea por firma de disco)."""
    from cognia.agent import skills as _sk
    filas = []
    for aviso in (_sk.avisos_de_carga() or []):
        avisos.append("skills: {}".format(aviso))
    for nombre, spec in (_sk.load_skills() or {}).items():
        # `source`, no `path`: SkillSpec no tiene `path` y el getattr con
        # default "" devolvia vacio -> Path("") == "." == el repo entero.
        ruta = str(getattr(spec, "source", "") or "")
        uso = {}
        try:
            uso = _sk._usage_for(spec) or {}
        except Exception as exc:
            avisos.append("uso de la skill {} ilegible ({}: {})".format(
                nombre, type(exc).__name__, exc))
        etiquetas = [str(getattr(spec, "kind", "") or "")]
        if uso.get("ok") or uso.get("fail"):
            etiquetas.append("{} ok / {} fallo".format(
                uso.get("ok", 0), uso.get("fail", 0)))
        filas.append(Fila(
            id=str(nombre), familia="skill", titulo=str(nombre),
            resumen=str(getattr(spec, "description", "") or "")[:280],
            ruta=ruta, creado="", modificado=_mtime_iso(ruta),
            bytes=_bytes_de(ruta),
            etiquetas=[e for e in etiquetas if e],
            fuente="agent.skills.load_skills"))
    return filas


def _leer_documentos(avisos: list) -> list:
    """Artefactos sueltos que Cognia escribe en `~/.cognia/`: los HTML que ya
    genera (grafo.html, flujo.html, y el memorias.html de este mismo trabajo)
    y los exports. No se escanea el disco entero: solo el directorio propio."""
    filas = []
    base = Path.home() / ".cognia"
    if not base.is_dir():
        return filas
    for patron in ("*.html", "*.md", "*.csv"):
        for f in sorted(base.glob(patron)):
            filas.append(Fila(
                id=f.name, familia="documento", titulo=f.name,
                resumen="artefacto generado en ~/.cognia",
                ruta=str(f), creado="", modificado=_mtime_iso(f),
                bytes=_bytes_de(f), etiquetas=[f.suffix.lstrip(".")],
                fuente="escaneo de ~/.cognia"))
    return filas


def _leer_sesiones(avisos: list, limite: int = 40) -> list:
    """Sesiones de chat. Fuente: tabla chat_history de la DB principal,
    agrupada por session_id. Acceso por db_pool (regla dura del repo: nada
    de sqlite3.connect directo)."""
    from cognia.config import DB_PATH
    from storage.db_pool import db_connect_pooled
    filas = []
    with db_connect_pooled(str(DB_PATH)) as conn:
        cur = conn.execute(
            "SELECT session_id, COUNT(*) n, MIN(timestamp) t0, "
            "       MAX(timestamp) t1, MAX(cwd) cwd "
            "FROM chat_history WHERE session_id IS NOT NULL AND session_id != '' "
            "GROUP BY session_id ORDER BY MAX(timestamp) DESC LIMIT ?",
            (limite,))
        for sid, n, t0, t1, cwd in cur.fetchall():
            filas.append(Fila(
                id=str(sid), familia="sesion",
                titulo=f"sesion {str(sid)[:8]}",
                resumen=f"{n} mensajes" + (f" en {cwd}" if cwd else ""),
                creado=_iso(t0), modificado=_iso(t1),
                etiquetas=[f"{n} mensajes"],
                fuente="chat_history"))
    return filas


def _leer_memorias(avisos: list, limite: int = 60) -> list:
    """Memorias episodicas y conceptos semanticos, las mas importantes
    primero. Es la unica familia que se recorta por relevancia y no por
    fecha: hay 935 episodios y volcarlos todos no es un catalogo, es un
    dump."""
    from cognia.config import DB_PATH
    from storage.db_pool import db_connect_pooled
    filas = []
    with db_connect_pooled(str(DB_PATH)) as conn:
        cur = conn.execute(
            "SELECT id, timestamp, observation, label, importance, "
            "       context_tags FROM episodic_memory "
            "WHERE COALESCE(forgotten,0)=0 "
            "ORDER BY COALESCE(importance,0) DESC, id DESC LIMIT ?", (limite,))
        for rid, ts, obs, label, imp, tags in cur.fetchall():
            etiquetas = [t for t in [label] if t]
            try:
                if tags:
                    etiquetas += [str(t) for t in json.loads(tags)][:4]
            except Exception:
                pass
            texto = _texto_util(str(obs or ""), avisos,
                                "episodio {}".format(rid))
            filas.append(Fila(
                id=f"ep{rid}", familia="memoria",
                titulo=texto[:80] or (str(label or "") or f"episodio {rid}"),
                resumen=texto[:280],
                creado=_iso(ts), modificado=_iso(ts),
                etiquetas=etiquetas, estado="episodica",
                fuente="episodic_memory"))
        cur = conn.execute(
            "SELECT concept, description, confidence, last_updated "
            "FROM semantic_memory ORDER BY COALESCE(confidence,0) DESC "
            "LIMIT ?", (max(10, limite // 3),))
        for concepto, desc, conf, upd in cur.fetchall():
            limpio = _texto_util(str(desc or ""), avisos,
                                 "concepto '{}'".format(concepto))
            filas.append(Fila(
                id=f"sem:{concepto}", familia="memoria",
                titulo=str(concepto), resumen=limpio[:280],
                creado="", modificado=_iso(upd),
                etiquetas=["concepto"], estado="semantica",
                fuente="semantic_memory"))
    return filas


def _leer_checkpoints(avisos: list) -> list:
    from cognia.harness import checkpoints as _ck
    filas = []
    for e in (_ck.listar() or []):
        filas.append(Fila(
            id=str(e.get("n")), familia="checkpoint",
            titulo="checkpoint {}".format(e.get("n")),
            resumen=str(e.get("motivo") or e.get("tool") or "")[:280],
            ruta=str(e.get("ruta") or ""), creado=_iso(e.get("ts")),
            modificado=_iso(e.get("ts")),
            estado="deshecho" if e.get("deshecho") else "vigente",
            fuente="harness.checkpoints.listar"))
    return filas


def _leer_papelera(avisos: list) -> list:
    from cognia.harness import papelera as _pp
    filas = []
    for e in (_pp.lotes() or []):
        filas.append(Fila(
            id=str(e.get("lote")), familia="papelera",
            titulo="borrado {}".format(e.get("lote")),
            resumen="{} ficheros, {} bytes — {}".format(
                e.get("n", 0), e.get("bytes", 0), e.get("motivo") or ""),
            creado=_iso(e.get("ts")), modificado=_iso(e.get("ts")),
            bytes=int(e.get("bytes") or 0),
            estado="restaurado" if e.get("restaurados") else "restaurable",
            fuente="harness.papelera.lotes"))
    return filas


_LECTORES = {
    "programa": _leer_programas,
    "flujo": _leer_flujos,
    "corrida": _leer_corridas,
    "skill": _leer_skills,
    "documento": _leer_documentos,
    "sesion": _leer_sesiones,
    "memoria": _leer_memorias,
    "checkpoint": _leer_checkpoints,
    "papelera": _leer_papelera,
}


def familias_disponibles() -> tuple:
    """Las familias que este catalogo sabe leer. Punto de extension: para
    anadir una mas se escribe su lector y se registra en _LECTORES; ningun
    consumidor cambia."""
    return tuple(f for f in FAMILIAS if f in _LECTORES)


def construir(familias=None, *, limite_por_familia: int = 0) -> Catalogo:
    """Lee todas las familias pedidas y devuelve el catalogo. NUNCA lanza.

    Una familia que falla NO deja el catalogo vacio ni desaparece en
    silencio: se anota en `avisos` y en `familias_fallidas`. Es la
    distincion que este repo paga cara cuando se pierde — "no lo cablearon"
    y "se rompio" tienen que verse distinto desde afuera.
    """
    inicio = time.monotonic()
    pedidas = [f for f in (familias or familias_disponibles())
               if f in _LECTORES]
    cat = Catalogo()
    for fam in pedidas:
        try:
            filas = _LECTORES[fam](cat.avisos) or []
        except Exception as exc:
            cat.avisos.append("familia '{}' no se pudo leer ({}: {})".format(
                fam, type(exc).__name__, exc))
            cat.familias_fallidas.append(fam)
            continue
        if limite_por_familia:
            filas = filas[:limite_por_familia]
        cat.filas.extend(filas)
        cat.familias_ok.append(fam)
    cat.ms = int((time.monotonic() - inicio) * 1000)
    return cat


# ---------------------------------------------------------------------------
# Busqueda lexica sobre el catalogo. Deliberadamente SIN embeddings: esto lo
# llama el mejorador de prompts entre el Enter del usuario y el envio, y
# cargar sentence-transformers ahi costaria mas que toda la mejora. Para
# busqueda semantica ya estan memory/semantic_search.py y el ContextMap.
# ---------------------------------------------------------------------------

_STOP = frozenset("""
de la que el en y a los se del las un por con no una su para es al lo como mas
pero sus le ya o este si porque esta entre cuando muy sin sobre tambien me
hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese
eso ante ellos e esto mi antes algunos que unos yo otro otras otra el tanto esa
estos mucho quienes nada muchos cual sea poco ella estar haber estas estaba
estamos algunas algo nosotros the of and to in for on with is a an
""".split())


def _tokens(texto: str) -> set:
    import re
    return {w for w in re.findall(r"[a-zA-Z0-9áéíóúñü]{3,}", (texto or "").lower())
            if w not in _STOP}


def buscar(cat: Catalogo, consulta: str, *, tope: int = 8,
           familias=None, minimo: int = 1) -> list:
    """Las `tope` filas mas parecidas a `consulta`, por solapamiento de
    palabras contra titulo + resumen + etiquetas.

    `minimo` es cuantas palabras tienen que coincidir para que una fila
    cuente. Con minimo=1 y una consulta de una palabra comun, esto devuelve
    ruido; el llamador que quiere precision sube el minimo. El mejorador de
    prompts usa minimo=2 justamente para no meter artefactos irrelevantes en
    el contexto solo para engordarlo.
    """
    pal = _tokens(consulta)
    if not pal:
        return []
    candidatas = [f for f in cat.filas
                  if not familias or f.familia in familias]
    puntuadas = []
    for f in candidatas:
        campo = " ".join([f.titulo, f.resumen, " ".join(f.etiquetas)])
        comunes = pal & _tokens(campo)
        if len(comunes) < minimo:
            continue
        # El titulo pesa doble: que una palabra aparezca en el NOMBRE del
        # artefacto es mucha mas senal que aparecer en su descripcion.
        bonus = len(pal & _tokens(f.titulo))
        puntuadas.append((len(comunes) + bonus, f.modificado or f.creado, f))
    puntuadas.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [f for _p, _fecha, f in puntuadas[:tope]]
