# -*- coding: utf-8 -*-
"""
cognia/multiverso/instantanea.py
================================
Instantaneas BARATAS de un workspace en Windows/NTFS: tomar, restaurar,
diferenciar y FUSIONAR el arbol de ficheros de una rama del agente.

QUE RESUELVE
------------
Ramificar el trabajo del agente (probar dos caminos y quedarse con el bueno)
solo es viable si volver atras es barato. Hoy Cognia tiene `harness/checkpoints`
(deshacer POR FICHERO, solo texto, solo donde la tool escribe) pero NO tiene
"deja el workspace exactamente como estaba": nadie borra lo que la rama creo,
nadie recupera lo que borro, y nadie sabe decir "entre A y B cambio esto".
Esta pieza es esa mitad.

POR QUE EXISTE
--------------
DeltaBox (arXiv 2605.22781) restaura el estado de un paso de agente en 5 ms
con delta de ficheros + CRIU. CRIU no existe en Windows: no hay checkpoint del
PROCESO. Aca se hace la mitad que SI se puede -- el arbol de ficheros -- y se
DECLARA la que no (ver LIMITES). La mitad que se puede es la que decide si
ramificar es viable, y para eso hace falta un NUMERO, no fe.

EVIDENCIA MEDIDA EN ESTA MAQUINA (Windows 11 Pro 26200, NTFS, venv312)
----------------------------------------------------------------------
Sondas ejecutadas ANTES de escribir este modulo (scratchpad/probe.py):

  os.link sobre NTFS                                -> OK, st_nlink 2
  write_text() in-place sobre el fichero original   -> EL OBJETO ENLAZADO
                                                       CAMBIA (queda corrupto)
  tmp + os.replace() sobre el original              -> el objeto enlazado
                                                       CONSERVA su contenido
  chmod(S_IREAD) sobre el objeto del almacen        -> el GEMELO del workspace
                                                       queda de solo lectura
                                                       (PermissionError al
                                                       escribirlo)
  unlink de un fichero de solo lectura              -> PermissionError
  unlink de un fichero ABIERTO (lectura o escritura)-> PermissionError

Consecuencia de diseno, no opinion: **enlazar el fichero vivo al almacen es
inseguro en esta plataforma**, porque el escritor tipico de Cognia
(`agent/tools.py::escribir_archivo` hace `wpath.write_text(...)`) escribe
IN-PLACE y eso muta el objeto compartido. Y no se puede blindar el objeto con
el atributo de solo-lectura porque en NTFS los atributos son del INODO: eso
dejaria el fichero del workspace sin escritura. Por eso:

  * `enlaces=False` (DEFECTO): el ingreso al almacen es COPIA. Seguro siempre.
  * `enlaces=True` (opt-in, o COGNIA_MULTIVERSO_ENLACES=1): ingreso por os.link.
    Solo es correcto si TODO escritor del workspace usa tmp+replace. El modulo
    no confia en eso: un almacen que haya enlazado alguna vez queda MARCADO
    (fichero `ENLACES_USADOS`) y desde entonces restaurar verifica el sha256 de
    cada objeto; si no cuadra va a `corruptos` y ese fichero NO se restaura.

    El disparador de la verificacion fue st_nlink > 1 hasta que el
    contrafactual de esta sesion lo tumbo: en la secuencia (enlazar -> escribir
    IN-PLACE -> borrar/reemplazar) la corrupcion ocurre con nlink=2 pero el
    nlink baja a 1 antes de que nadie mire, y se restauraba 'XXXXXXXXXXX' con
    ok=True y cero corruptos (salida pegada en el informe de entrega). De ahi
    la marca por almacen: caro pero sonoro, y solo lo paga quien opta por los
    enlaces.

Los ms y los bytes de las dos vias se miden con `scripts/medir_instantanea.py`
(sale del propio modulo, no de un numero escrito a mano aca).

API PUBLICA
-----------
    tomar(workspace, etiqueta="", **opciones)      -> Instantanea
    restaurar(instantanea, workspace=None)         -> dict {ok, restaurados,
                                                      borrados, recuperados,
                                                      ..., ms}
    diferencia(a, b)                               -> {creados, modificados,
                                                       borrados, ...}
    aplicar_diferencia(dif, origen_ws, destino_ws) -> dict   (el MERGE)
    estadisticas_almacen(almacen=None)             -> {objetos, bytes}
    Instantanea.guardar(ruta) / Instantanea.cargar(ruta)      (JSON atomico)
    Instantanea.manifiesto_corto() -> {ruta: (mtime, tam, sha256_corto)}

ALMACEN (direccionable por contenido, compartido entre instantaneas)
--------------------------------------------------------------------
    ~/.cognia/multiverso/objetos/<2 primeros del sha>/<sha256 completo>
Override por `almacen=` o COGNIA_MULTIVERSO_DIR, leido a CALL-TIME para que los
tests aislen con tmp_path. Dedup total: dos instantaneas del mismo contenido no
escriben bytes dos veces, y `bytes_nuevos` lo reporta.

EXCLUSIONES POR DEFECTO (una instantanea que tarda mas que la tarea no sirve)
-----------------------------------------------------------------------------
    directorios: .git __pycache__ node_modules venv* .venv* .pytest_cache
                 .mypy_cache .ruff_cache .tox .idea
    ficheros:    *.pyc *.pyo *.pyd
    TOPE DE TAMANO: 8 MB por fichero (COGNIA_MULTIVERSO_MAX_MB o tope_mb=).
Lo excluido y lo que pasa el tope quedan listados en `Instantanea.omitidos` con
su motivo: NO se copian, NO se restauran y NO se borran al restaurar. Un
fichero grande que la rama creo SOBREVIVE a restaurar(); es un limite
declarado, no un descuido.

LIMITES DECLARADOS (lo que esta pieza NO hace)
----------------------------------------------
- NO es CRIU: no captura el PROCESO (memoria, descriptores, hijos vivos, un
  puerto escuchando). Solo ficheros.
- NO revierte efectos EXTERNOS al workspace: un `git push`, un correo, una fila
  en una BD remota siguen ahi. Ese es el hueco abierto del campo y este modulo
  no lo tapa; cubre el disco local del workspace y nada mas.
- NO versiona permisos POSIX ni ACLs de Windows. Solo el bit de SOLO LECTURA
  (que en NTFS es un atributo y si decide si se puede reescribir/borrar).
- NO sigue enlaces simbolicos ni junctions: se registran como omitidos con
  motivo 'enlace' (evita ciclos y copiar un arbol ajeno entero).
- El atajo `base=` (el delta de DeltaBox aplicado a lo que Windows si permite)
  confia en (tamano, mtime_ns): una escritura que preserve ambos pasa
  desapercibida. Sin `base=` se hashea todo y ese riesgo no existe.
- Ficheros ABIERTOS por otro proceso: en Windows no se pueden borrar ni
  sobrescribir (medido arriba). Se reportan en `fallos` con su motivo y ponen
  ok=False; nunca se traga la excepcion.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

# -- Configuracion por defecto -----------------------------------------
DIRS_EXCLUIDOS = (
    ".git", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".idea", "venv*", ".venv*",
)
FICHEROS_EXCLUIDOS = ("*.pyc", "*.pyo", "*.pyd")
TOPE_MB_DEFECTO = 8            # tope POR FICHERO; por encima -> omitido
_TROZO = 1024 * 1024           # lectura de 1 MiB al hashear


# -- El objeto instantanea ---------------------------------------------
@dataclass
class Instantanea:
    """Manifiesto de un arbol + puntero al almacen. Serializable a JSON.

    `manifiesto` es {ruta_relativa_posix: {"sha","tam","mtime","ns","ro"}}.
    `directorios` guarda los directorios, para poder restaurar uno VACIO que
    existia y borrar uno que la rama creo.
    """
    id: str
    workspace: str
    etiqueta: str = ""
    creada: float = 0.0
    manifiesto: dict = field(default_factory=dict)
    directorios: list = field(default_factory=list)
    omitidos: list = field(default_factory=list)
    almacen: str = ""
    modo_contenido: str = "copia"     # "copia" | "enlace" | "dedup" | "mixto"
    ms: float = 0.0
    bytes_nuevos: int = 0             # bytes escritos AL ALMACEN en esta toma
    bytes_totales: int = 0            # bytes del arbol capturado
    tope_bytes: int = TOPE_MB_DEFECTO * 1024 * 1024
    excluir_dirs: list = field(default_factory=lambda: list(DIRS_EXCLUIDOS))
    excluir_ficheros: list = field(
        default_factory=lambda: list(FICHEROS_EXCLUIDOS))

    def manifiesto_corto(self) -> dict:
        """{ruta: (mtime, tamano, sha256_corto)} -- la forma compacta."""
        return {r: (e["mtime"], e["tam"], e["sha"][:12])
                for r, e in self.manifiesto.items()}

    def a_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: dict) -> "Instantanea":
        campos = {k: v for k, v in d.items()
                  if k in Instantanea.__dataclass_fields__}
        return Instantanea(**campos)

    def guardar(self, ruta) -> str:
        """Persiste el manifiesto en JSON de forma atomica (tmp + replace):
        un corte a mitad deja el anterior legible, nunca un JSON truncado."""
        p = Path(ruta)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(self.a_dict(), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(str(tmp), str(p))
        return str(p)

    @staticmethod
    def cargar(ruta) -> "Instantanea":
        return Instantanea.de_dict(
            json.loads(Path(ruta).read_text(encoding="utf-8")))


# -- Almacen direccionable por contenido -------------------------------
def _dir_almacen(almacen=None) -> Path:
    """Raiz del almacen, resuelta a CALL-TIME (los tests aislan con env)."""
    if almacen:
        return Path(almacen)
    env = os.environ.get("COGNIA_MULTIVERSO_DIR", "").strip()
    return Path(env) if env else (Path.home() / ".cognia" / "multiverso")


def _ruta_objeto(almacen: Path, sha: str) -> Path:
    # Dos niveles: un solo directorio con 100k entradas se arrastra en NTFS.
    return almacen / "objetos" / sha[:2] / sha


def estadisticas_almacen(almacen=None) -> dict:
    """{objetos, bytes, ruta} del almacen: el coste ACUMULADO de ramificar."""
    raiz = _dir_almacen(almacen) / "objetos"
    n = tot = 0
    if raiz.exists():
        for sub in raiz.iterdir():
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                try:
                    tot += f.stat().st_size
                    n += 1
                except OSError:
                    pass
    return {"objetos": n, "bytes": tot, "ruta": str(raiz)}


_MARCA_ENLACES = "ENLACES_USADOS"
# Respaldo en memoria de la marca: si el fichero no se pudo escribir, al menos
# ESTE proceso sigue verificando. Entre procesos, sin fichero, no hay marca:
# limite declarado en la cabecera.
_ENLACES_EN_PROCESO = set()


def _marcar_enlaces(almacen: Path):
    """Deja constancia PERMANENTE de que este almacen tuvo algun objeto
    ingresado por os.link.

    POR QUE una marca y no mirar st_nlink: el contrafactual de esta sesion lo
    destapo. La secuencia (1) tomar con enlaces, (2) el agente escribe IN-PLACE
    -> el objeto queda mutado con nlink=2, (3) el fichero se borra o se
    reemplaza por os.replace -> nlink baja a 1. En el paso 3 la corrupcion ya
    ocurrio y st_nlink ya no la delata: medido, se restauraba 'XXXXXXXXXXX'
    con ok=True y cero corruptos. Con la marca, TODO objeto de un almacen que
    alguna vez enlazo se verifica por sha al restaurar. El almacen por defecto
    (solo copia) no lleva marca y no paga nada.
    """
    _ENLACES_EN_PROCESO.add(str(almacen))
    m = almacen / _MARCA_ENLACES
    if not m.exists():
        try:
            almacen.mkdir(parents=True, exist_ok=True)
            m.write_text("os.link usado en este almacen\n", encoding="utf-8")
        except OSError:
            pass          # queda al menos el respaldo en memoria


def _hubo_enlaces(almacen: Path) -> bool:
    return (str(almacen) in _ENLACES_EN_PROCESO
            or (almacen / _MARCA_ENLACES).exists())


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(str(ruta), "rb") as f:
        while True:
            b = f.read(_TROZO)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _ingresar(src: Path, sha: str, almacen: Path, enlaces: bool):
    """Mete el contenido en el almacen. Devuelve (modo, bytes_escritos).

    modo: 'dedup' (ya estaba, coste 0), 'enlace' (os.link) o 'copia'. El enlace
    es opt-in y su riesgo esta en la cabecera; si falla (otro volumen, FS sin
    hardlinks, carrera con EEXIST) cae a copia sin avisar al llamador porque el
    resultado observable es identico -- lo que cambia es el coste, y eso queda
    en `modo_contenido`.
    """
    obj = _ruta_objeto(almacen, sha)
    if obj.exists():
        return "dedup", 0
    obj.parent.mkdir(parents=True, exist_ok=True)
    tam = src.stat().st_size
    if enlaces:
        try:
            os.link(str(src), str(obj))
            _marcar_enlaces(almacen)
            return "enlace", 0          # el enlace no copia datos
        except OSError:
            pass                        # cross-volume / FS sin links -> copia
    # Copia ATOMICA: un corte a mitad no puede dejar un objeto truncado con
    # nombre de hash valido (seria veneno silencioso para toda instantanea
    # futura que lo reutilice por dedup).
    tmp = obj.parent / (sha + "." + uuid.uuid4().hex[:8] + ".tmp")
    try:
        shutil.copyfile(str(src), str(tmp))
        os.replace(str(tmp), str(obj))
    except OSError:
        try:
            if tmp.exists():
                os.chmod(str(tmp), stat.S_IWRITE)
                tmp.unlink()
        except OSError:
            pass
        raise
    return "copia", tam


# -- Recorrido del arbol con exclusiones -------------------------------
def _casa(nombre: str, patrones) -> bool:
    return any(fnmatch.fnmatch(nombre, p) for p in patrones)


def _es_reparse(p: Path) -> bool:
    """Junction de Windows: no es symlink para Python pero tampoco un dir
    normal, y seguirla copiaria un arbol ajeno entero."""
    try:
        return bool(p.lstat().st_file_attributes & 0x400)  # REPARSE_POINT
    except (OSError, AttributeError):
        return False


def _solo_lectura(st) -> bool:
    return not bool(st.st_mode & stat.S_IWRITE)


def _recorrer(ws: Path, tope_bytes: int, ex_dirs, ex_fich):
    """Devuelve (ficheros, directorios, omitidos).

    ficheros: [(rel_posix, Path, st)]; directorios: [rel_posix] ordenado;
    omitidos: [{"ruta","motivo","tam"}]. No sigue symlinks ni junctions.
    """
    ficheros, dirs, omitidos = [], [], []
    for raiz, subdirs, nombres in os.walk(str(ws)):
        praiz = Path(raiz)
        # Poda IN-PLACE: os.walk respeta la mutacion de `subdirs`, asi que ni
        # se entra a .git -- que es el grueso del coste en un repo.
        podados = [d for d in subdirs if _casa(d, ex_dirs)]
        for d in podados:
            rel = (praiz / d).relative_to(ws).as_posix()
            omitidos.append({"ruta": rel, "motivo": "dir_excluido", "tam": 0})
        subdirs[:] = [d for d in subdirs if d not in podados]
        reales = []
        for d in subdirs:
            p = praiz / d
            rel = p.relative_to(ws).as_posix()
            if p.is_symlink() or _es_reparse(p):
                omitidos.append({"ruta": rel, "motivo": "enlace", "tam": 0})
                continue
            reales.append(d)
            dirs.append(rel)
        subdirs[:] = reales
        for n in nombres:
            p = praiz / n
            rel = p.relative_to(ws).as_posix()
            if _casa(n, ex_fich):
                omitidos.append({"ruta": rel, "motivo": "fichero_excluido",
                                 "tam": 0})
                continue
            if p.is_symlink():
                omitidos.append({"ruta": rel, "motivo": "enlace", "tam": 0})
                continue
            try:
                st = p.stat()
            except OSError as e:
                omitidos.append({"ruta": rel,
                                 "motivo": "stat:" + type(e).__name__,
                                 "tam": 0})
                continue
            if st.st_size > tope_bytes:
                omitidos.append({"ruta": rel, "motivo": "supera_tope",
                                 "tam": st.st_size})
                continue
            ficheros.append((rel, p, st))
    return ficheros, sorted(dirs), omitidos


# -- TOMAR -------------------------------------------------------------
def tomar(workspace, etiqueta: str = "", tope_mb=None, almacen=None,
          enlaces=None, excluir_dirs=None, excluir_ficheros=None,
          base=None) -> Instantanea:
    """Captura el arbol de `workspace`. Ver la cabecera del modulo.

    `base`: instantanea previa del MISMO workspace. Si se pasa, los ficheros
    con (tamano, mtime_ns) identicos NO se re-hashean ni se re-ingresan: es el
    delta de DeltaBox aplicado a lo que Windows si permite. Su limite esta
    declarado en la cabecera.
    """
    t0 = time.perf_counter()
    ws = Path(workspace).resolve()
    if not ws.is_dir():
        raise NotADirectoryError("workspace inexistente: %s" % ws)
    if tope_mb is None:
        try:
            tope_mb = float(os.environ.get("COGNIA_MULTIVERSO_MAX_MB",
                                           TOPE_MB_DEFECTO))
        except ValueError:
            tope_mb = TOPE_MB_DEFECTO
    tope_bytes = int(float(tope_mb) * 1024 * 1024)
    if enlaces is None:
        enlaces = os.environ.get(
            "COGNIA_MULTIVERSO_ENLACES", "0").strip().lower() in (
                "1", "on", "true", "si", "yes")
    ex_dirs = list(excluir_dirs) if excluir_dirs is not None \
        else list(DIRS_EXCLUIDOS)
    ex_fich = list(excluir_ficheros) if excluir_ficheros is not None \
        else list(FICHEROS_EXCLUIDOS)
    alm = _dir_almacen(almacen)

    ficheros, dirs, omitidos = _recorrer(ws, tope_bytes, ex_dirs, ex_fich)
    prev = base.manifiesto if (base is not None) else {}

    manifiesto, modos, nuevos, totales = {}, set(), 0, 0
    for rel, p, st in ficheros:
        totales += st.st_size
        ant = prev.get(rel)
        if (ant and ant.get("tam") == st.st_size
                and ant.get("ns") == st.st_mtime_ns
                and _ruta_objeto(alm, ant["sha"]).exists()):
            # Delta: ni hash ni copia. Es lo que abarata la instantanea N+1.
            ent = dict(ant)
            ent["ro"] = _solo_lectura(st)
            manifiesto[rel] = ent
            modos.add("dedup")
            continue
        try:
            sha = _sha256(p)
            modo, esc = _ingresar(p, sha, alm, bool(enlaces))
        except OSError as e:
            # Fichero en uso / sin permiso: se OMITE con su motivo. No se
            # inventa una entrada de manifiesto que luego restauraria mal.
            omitidos.append({"ruta": rel,
                             "motivo": "lectura:" + type(e).__name__,
                             "tam": st.st_size})
            continue
        modos.add(modo)
        nuevos += esc
        manifiesto[rel] = {"sha": sha, "tam": st.st_size,
                           "mtime": st.st_mtime, "ns": st.st_mtime_ns,
                           "ro": _solo_lectura(st)}

    if len(modos) == 1:
        modo_final = modos.pop()
    else:
        modo_final = "mixto" if modos else "vacio"
    return Instantanea(
        id=uuid.uuid4().hex[:12],
        workspace=str(ws),
        etiqueta=etiqueta,
        creada=time.time(),
        manifiesto=manifiesto,
        directorios=dirs,
        omitidos=omitidos,
        almacen=str(alm),
        modo_contenido=modo_final,
        ms=round((time.perf_counter() - t0) * 1000.0, 3),
        bytes_nuevos=nuevos,
        bytes_totales=totales,
        tope_bytes=tope_bytes,
        excluir_dirs=ex_dirs,
        excluir_ficheros=ex_fich,
    )


# -- Escritura / borrado defensivos (Windows) --------------------------
def _forzar_escritura(p: Path):
    """Quita el atributo de solo lectura. Sin esto, en Windows el fichero ni
    se borra ni se sobrescribe (medido: PermissionError)."""
    try:
        os.chmod(str(p), stat.S_IWRITE)
    except OSError:
        pass


def _borrar(p: Path):
    """Borra reintentando UNA vez sin el bit de solo lectura. Si vuelve a
    fallar (tipico: fichero ABIERTO por otro proceso) la excepcion SUBE: el
    llamador la reporta, nadie se la traga."""
    try:
        p.unlink()
    except PermissionError:
        _forzar_escritura(p)
        p.unlink()


def _materializar(sha: str, tam: int, destino: Path, alm: Path,
                  enlaces: bool) -> str:
    """Deja el contenido `sha` en `destino`. Devuelve 'enlace' o 'copia'.

    VERIFICACION: se re-hashea el objeto si el almacen alguna vez uso os.link
    (marca `ENLACES_USADOS`) o si el objeto tiene st_nlink > 1 ahora mismo. El
    almacen por defecto -- solo copia -- no cumple ninguna de las dos y no paga
    el hash. Un objeto que no cuadra levanta ValueError: no se restaura basura.
    """
    obj = _ruta_objeto(alm, sha)
    if not obj.exists():
        raise FileNotFoundError("objeto ausente del almacen: %s" % sha[:12])
    st = obj.stat()
    if st.st_size != tam:
        raise ValueError("objeto %s con tamano %d != %d"
                         % (sha[:12], st.st_size, tam))
    if (st.st_nlink > 1 or _hubo_enlaces(alm)) and _sha256(obj) != sha:
        raise ValueError("objeto %s CORRUPTO (mutado por un gemelo enlazado)"
                         % sha[:12])
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        _borrar(destino)
    if enlaces:
        try:
            os.link(str(obj), str(destino))
            return "enlace"
        except OSError:
            pass
    tmp = destino.parent / ("." + destino.name + "."
                            + uuid.uuid4().hex[:8] + ".tmp")
    shutil.copyfile(str(obj), str(tmp))
    os.replace(str(tmp), str(destino))
    return "copia"


# -- RESTAURAR ---------------------------------------------------------
def restaurar(instantanea: Instantanea, workspace=None, enlaces=False,
              verificar=False) -> dict:
    """Deja el workspace EXACTAMENTE como estaba en la instantanea.

    Borra lo que la rama creo, reescribe lo modificado, recupera lo borrado,
    repone los directorios vacios y el bit de solo lectura.

    Devuelve {ok, restaurados, borrados, recuperados, sin_cambio, dirs_creados,
    dirs_borrados, fallos, corruptos, ms}. `ok` es False con UN SOLO fallo: un
    restaurar a medias no es un restaurar, y en este repo lo que degrada en
    silencio es el enemigo.

    `verificar=False` (defecto): un fichero se da por intacto si coinciden
    (tamano, mtime_ns, bit RO) -- sin leerlo. Es lo que hace que restaurar sea
    barato. LIMITE: una escritura que preserve tamano Y mtime_ns exacto pasa
    desapercibida. `verificar=True` compara por sha256 leyendo cada fichero:
    correcto siempre, y varias veces mas caro (esta medido en
    scripts/medir_instantanea.py).
    """
    t0 = time.perf_counter()
    ws = Path(workspace).resolve() if workspace else Path(instantanea.workspace)
    alm = _dir_almacen(instantanea.almacen or None)
    ws.mkdir(parents=True, exist_ok=True)

    actuales, dirs_ahora, _om = _recorrer(
        ws, instantanea.tope_bytes,
        list(instantanea.excluir_dirs or DIRS_EXCLUIDOS),
        list(instantanea.excluir_ficheros or FICHEROS_EXCLUIDOS))
    ahora = {rel: (p, st) for rel, p, st in actuales}
    antes = instantanea.manifiesto

    res = {"ok": True, "restaurados": [], "borrados": [], "recuperados": [],
           "sin_cambio": 0, "dirs_creados": [], "dirs_borrados": [],
           "fallos": [], "corruptos": [], "ms": 0.0}

    # 1) lo que la rama CREO despues -> fuera
    for rel in sorted(set(ahora) - set(antes)):
        p = ahora[rel][0]
        try:
            _borrar(p)
            res["borrados"].append(rel)
        except OSError as e:
            res["fallos"].append({"ruta": rel, "op": "borrar",
                                  "error": "%s: %s" % (type(e).__name__, e)})

    # 2) lo que existia -> reponer contenido si cambio
    for rel, ent in sorted(antes.items()):
        destino = ws / rel
        vivo = ahora.get(rel)
        if vivo is not None:
            st = vivo[1]
            if _solo_lectura(st) == bool(ent.get("ro")):
                intacto = False
                if verificar:
                    try:
                        intacto = (st.st_size == ent["tam"]
                                   and _sha256(destino) == ent["sha"])
                    except OSError:
                        intacto = False     # ilegible -> se intenta restaurar
                else:
                    intacto = (st.st_size == ent["tam"]
                               and st.st_mtime_ns == ent["ns"])
                if intacto:
                    res["sin_cambio"] += 1
                    continue
        try:
            if vivo is not None and _solo_lectura(vivo[1]):
                _forzar_escritura(destino)
            _materializar(ent["sha"], ent["tam"], destino, alm, bool(enlaces))
            os.utime(str(destino), ns=(ent["ns"], ent["ns"]))
            if ent.get("ro"):
                os.chmod(str(destino), stat.S_IREAD)
            if vivo is not None:
                res["restaurados"].append(rel)
            else:
                res["recuperados"].append(rel)
        except ValueError as e:      # objeto corrupto o tamano != manifiesto
            res["corruptos"].append({"ruta": rel, "error": str(e)})
        except OSError as e:         # en uso, sin permiso, disco lleno
            res["fallos"].append({"ruta": rel, "op": "restaurar",
                                  "error": "%s: %s" % (type(e).__name__, e)})

    # 3) directorios: reponer los vacios que existian, quitar los que se crearon
    for rel in instantanea.directorios:
        d = ws / rel
        if not d.exists():
            try:
                d.mkdir(parents=True, exist_ok=True)
                res["dirs_creados"].append(rel)
            except OSError as e:
                res["fallos"].append({"ruta": rel, "op": "mkdir",
                                      "error": "%s: %s" % (type(e).__name__, e)})
    # De mas profundo a menos: un dir sobrante solo se vacia tras vaciar su hijo
    sobrantes = sorted(set(dirs_ahora) - set(instantanea.directorios),
                       key=lambda r: r.count("/"), reverse=True)
    for rel in sobrantes:
        d = ws / rel
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                res["dirs_borrados"].append(rel)
        except OSError as e:
            res["fallos"].append({"ruta": rel, "op": "rmdir",
                                  "error": "%s: %s" % (type(e).__name__, e)})

    res["ok"] = not res["fallos"] and not res["corruptos"]
    res["ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    return res


# -- DIFERENCIA --------------------------------------------------------
def diferencia(a: Instantanea, b: Instantanea) -> dict:
    """Que cambio al pasar de `a` a `b`. Es lo que permite JUZGAR una rama.

    Devuelve {creados, modificados, borrados, n_iguales, shas} con listas de
    rutas relativas ordenadas. `shas` mapea ruta -> sha en `b` (None si se
    borro) y es de donde `aplicar_diferencia` tira del almacen cuando el
    workspace de la rama ya no existe.
    """
    ma, mb = a.manifiesto, b.manifiesto
    creados = sorted(set(mb) - set(ma))
    borrados = sorted(set(ma) - set(mb))
    comunes = set(ma) & set(mb)
    modificados = sorted(r for r in comunes if ma[r]["sha"] != mb[r]["sha"])
    shas = {r: mb[r]["sha"] for r in creados + modificados}
    for r in borrados:
        shas[r] = None
    return {"creados": creados, "modificados": modificados,
            "borrados": borrados,
            "n_iguales": len(comunes) - len(modificados),
            "shas": shas}


# -- APLICAR DIFERENCIA (el MERGE) -------------------------------------
def aplicar_diferencia(dif: dict, origen_ws, destino_ws, almacen=None,
                       instantanea=None, enlaces=False) -> dict:
    """Mueve el EFECTO de una rama al workspace real.

    Fuente de la verdad, en este orden: (1) el fichero vivo en `origen_ws`;
    (2) si ya no esta, el objeto del almacen via `dif["shas"]` -- asi el merge
    sigue funcionando aunque la rama ya se haya limpiado del disco.

    Devuelve {ok, escritos, borrados, fallos, ausentes, ms}. Un fichero que no
    se pudo tomar de NINGUNA de las dos fuentes va a `ausentes`, no cuenta como
    escrito y pone ok=False: un merge parcial que se declara completo es
    exactamente el fallo silencioso que este repo persigue.
    """
    t0 = time.perf_counter()
    org = Path(origen_ws).resolve() if origen_ws else None
    dst = Path(destino_ws).resolve()
    dst.mkdir(parents=True, exist_ok=True)
    alm = _dir_almacen(
        almacen or (instantanea.almacen if instantanea is not None else None))
    shas = dict(dif.get("shas") or {})
    if instantanea is not None:
        for r, e in instantanea.manifiesto.items():
            shas.setdefault(r, e["sha"])

    res = {"ok": True, "escritos": [], "borrados": [], "fallos": [],
           "ausentes": [], "ms": 0.0}

    for rel in list(dif.get("creados", [])) + list(dif.get("modificados", [])):
        destino = dst / rel
        fuente = (org / rel) if org is not None else None
        try:
            if fuente is not None and fuente.is_file():
                destino.parent.mkdir(parents=True, exist_ok=True)
                if destino.exists():
                    _forzar_escritura(destino)
                tmp = destino.parent / ("." + destino.name + "."
                                        + uuid.uuid4().hex[:8] + ".tmp")
                shutil.copyfile(str(fuente), str(tmp))
                os.replace(str(tmp), str(destino))
                res["escritos"].append(rel)
            elif shas.get(rel):
                sha = shas[rel]
                obj = _ruta_objeto(alm, sha)
                if not obj.exists():
                    res["ausentes"].append(rel)
                    continue
                _materializar(sha, obj.stat().st_size, destino, alm,
                              bool(enlaces))
                res["escritos"].append(rel)
            else:
                res["ausentes"].append(rel)
        except (OSError, ValueError) as e:
            res["fallos"].append({"ruta": rel, "op": "escribir",
                                  "error": "%s: %s" % (type(e).__name__, e)})

    for rel in dif.get("borrados", []):
        destino = dst / rel
        if not destino.exists():
            continue
        try:
            _borrar(destino)
            res["borrados"].append(rel)
        except OSError as e:
            res["fallos"].append({"ruta": rel, "op": "borrar",
                                  "error": "%s: %s" % (type(e).__name__, e)})

    res["ok"] = not res["fallos"] and not res["ausentes"]
    res["ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    return res
