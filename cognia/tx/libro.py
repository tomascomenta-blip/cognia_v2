# -*- coding: utf-8 -*-
"""LIBRO -- el almacen append-only del subsistema TX (ESPEC 1.1, 3.x, 8.4).

UN evento JSON por linea, cadena `prev`-sha, `fsync`. No existe `delete` ni
`update`: retractar es APENDAR un `invalidate`. Esa es la propiedad que hace
que `bandas.proyectar()` pueda ser una funcion pura del LIBRO (invariante I2) y
que el rollback sea "reproyectar un prefijo", no "volver a un resumen viejo".

LO QUE ESTE MODULO SE NIEGA A HACER EN SILENCIO (P0-2): si no puede dejar
constancia lanza `LibroCaido`. El resto del arnes degrada a no hacer nada y eso
esta bien para hooks; para la MEMORIA no lo esta -- disco lleno seria la
memoria apagada sin que nadie emita un error, que es el fallo tipico de este
sistema (el vacio silencioso, no la excepcion).

CORRUPCION (ESPEC 8.4): una linea truncada por un corte a mitad de escritura no
se esconde ni tumba el arranque. `leer()` devuelve el PREFIJO VALIDO MAS LARGO
y deja en el diagnostico cuantos bytes se descartaron; `append()` sanea la cola
parcial antes de escribir para que la cadena `prev` siga cerrando.
"""

import json
import os
import threading
import time

from cognia.tx.claves import sha14
from cognia.tx.errores import EventoInvalido, LibroCaido

# Los campos que entran en el sha del evento. NO entran `n`, `ts` ni `prev`:
# el sha es CONTENT-ADDRESSED (ESPEC 3.2), asi que el mismo hecho escrito dos
# veces da el mismo sha y el append es idempotente. Si `ts` entrara, dos
# corridas identicas darian libros distintos y `proyectar` dejaria de ser
# comparable entre corridas.
#
# LA FIRMA v1 NO CUBRIA LO QUE DECIDE SI UNA FILA VALE (arreglado 2026-08-19).
# Medido: el evento {origen:'modelo', conf:0.30, estado:'hipotesis'} y el mismo
# con {origen:'medido', conf:1.00, estado:'verificado'} daban EL MISMO sha
# (a93202b17ca912 los dos) y los dos pasaban `validar()`. Es decir: cambiando
# dos palabras en una linea del fichero, una frase del modelo se convertia en
# base MEDIDA para `tool.decidir` sin que `_parsear` ni `fsck` vieran nada --
# justo el techo de conf que este modulo llama "DURO. No asciende por
# repeticion. Jamas". La firma v2 mete `quien`, `origen`, `conf` y `estado`, y
# mete tambien `v`: quitar el "v":2 para que el evento se valide con la firma
# vieja cambia el sha bajo v2, asi que la degradacion tambien es DETECTABLE.
_CAMPOS_SHA = ("t", "op", "id", "banda", "clave", "valor", "texto", "prov")
_CAMPOS_SHA_V2 = _CAMPOS_SHA + ("quien", "origen", "conf", "estado", "v")

# La version que se escribe hoy. Los libros ya escritos (sin `v`) siguen
# leyendose con la firma vieja; `fsck` los marca como FIRMA DEBIL en vez de
# darlos por buenos en silencio.
VERSION_EVENTO = 2

TIPOS = ("objetivo", "restriccion", "definicion", "criterio", "trazador",
         "fichero", "comando", "verificador", "verificacion",
         "hecho", "decision", "leccion", "pendiente", "afirmacion",
         "contradiccion", "tx")

OPS = ("add", "supersede", "amend", "invalidate", "resolve", "stale")

BANDAS = ("P", "T", "N", "D", "F", "A", "E", "Q", "X")

QUIEN = ("usuario", "harness", "ejecutor", "critico", "sub")

ORIGENES = ("usuario", "medido", "citado", "derivado", "modelo")

ESTADOS = ("hipotesis", "verificado", "sospechoso", "invalidado")

# conf = f(origen). FUNCION PURA (ESPEC 3.3). Un LLM no emite este campo nunca:
# si la confianza la firmase el mismo modelo cuyo juicio esta medido en el azar
# (0,517), el resultado son hechos falsos con etiqueta creible.
CONF_POR_ORIGEN = {
    "usuario": 1.00,
    "medido": 1.00,
    "citado": 0.90,
    "derivado": 1.00,
    "modelo": 0.30,      # techo DURO. No asciende por repeticion. Jamas.
}

# Las bandas que persisten a traves del reset. Lo que el modelo DIJO
# (prov.tipo == 'dicha') no puede entrar aqui: vive en X y muere en el reset.
# Es la clausula allOf de la ESPEC 3.2, y es el corazon anti-alucinacion.
BANDAS_PERSISTENTES = ("P", "T", "D", "F", "A")

_LOCK = threading.Lock()
_ACTIVO = {"libro": None}          # el LIBRO de la tarea en curso, o None
_AVISADO = {"sin_tarea": False}


# ----------------------------------------------------------------- rutas

def dir_tarea(task_id):
    """~/.cognia/data/tareas/<task_id> -- la misma raiz que estado_tarea."""
    try:
        from cognia.agent.estado_tarea import dir_tareas
        raiz = dir_tareas()
    except Exception:
        from pathlib import Path
        raiz = Path.home() / ".cognia" / "data" / "tareas"
    return os.path.join(str(raiz), str(task_id))


# ------------------------------------------------------------- validacion

def _falta(evento, campo):
    return campo not in evento or evento[campo] is None


def validar(evento):
    """Comprueba el esquema de la ESPEC 3.2. Lanza `EventoInvalido`.

    POR QUE UNA EXCEPCION Y NO UN BOOL: un `add` rechazado tiene que volver al
    modelo COMO ERROR DE TOOL (invariante I3). Un False que el llamador ignora
    convierte "lo rechace" en "no se escribio y nadie lo sabe": el vacio
    silencioso otra vez, esta vez en la puerta de entrada.
    """
    if not isinstance(evento, dict):
        raise EventoInvalido("el evento no es un dict: %r" % type(evento))
    for campo in ("t", "op", "banda", "quien", "origen", "texto", "prov"):
        if _falta(evento, campo):
            raise EventoInvalido("falta el campo obligatorio '%s'" % campo)
    if evento["t"] not in TIPOS:
        raise EventoInvalido("t='%s' fuera del vocabulario" % evento["t"])
    if evento["op"] not in OPS:
        raise EventoInvalido("op='%s' fuera del vocabulario (no existe update "
                             "ni delete)" % evento["op"])
    if evento["banda"] not in BANDAS:
        raise EventoInvalido("banda='%s' fuera del vocabulario" % evento["banda"])
    if evento["quien"] not in QUIEN:
        raise EventoInvalido("quien='%s' fuera del vocabulario" % evento["quien"])
    if evento["origen"] not in ORIGENES:
        raise EventoInvalido("origen='%s' fuera del vocabulario" % evento["origen"])
    if not isinstance(evento["prov"], dict) or not evento["prov"].get("tipo"):
        raise EventoInvalido("prov sin 'tipo': la provenance la escribe la "
                             "maquina, no puede faltar")
    if len(str(evento.get("texto") or "")) > 400:
        raise EventoInvalido("texto de %d chars: el tope de la ESPEC 3.2 es 400"
                             % len(str(evento["texto"])))
    if evento.get("estado") is not None and evento["estado"] not in ESTADOS:
        raise EventoInvalido("estado='%s' fuera del vocabulario" % evento["estado"])
    clave = evento.get("clave")
    if clave is not None:
        from cognia.tx.claves import valida as _clave_valida
        if not _clave_valida(clave):
            raise EventoInvalido("clave='%s' fuera del vocabulario CERRADO "
                                 "(ESPEC 3.4)" % clave)

    # --- las dos clausulas allOf de la ESPEC 3.2: el corazon anti-alucinacion
    if (evento["prov"].get("tipo") == "dicha"
            and evento["banda"] in BANDAS_PERSISTENTES):
        raise EventoInvalido(
            "prov.tipo='dicha' en banda %s: lo que el modelo DIJO no puede "
            "tocar una banda persistente. Vive en X y muere en el reset"
            % evento["banda"])
    conf = evento.get("conf")
    if conf is None:
        evento["conf"] = CONF_POR_ORIGEN[evento["origen"]]
    else:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            raise EventoInvalido("conf='%r' no es un numero" % conf)
        if not (0.0 <= conf <= 1.0):
            raise EventoInvalido("conf=%r fuera de [0,1]" % conf)
        if evento["origen"] == "modelo" and conf > 0.30 + 1e-9:
            raise EventoInvalido(
                "conf=%.2f con origen='modelo': el techo es 0,30 y es DURO. "
                "La confianza es funcion pura del origen, no la emite el LLM"
                % conf)
        evento["conf"] = conf
    return evento


def campos_firmados(evento):
    """Los campos que cubre la firma de ESTE evento. Depende de su `v`."""
    try:
        version = int((evento or {}).get("v") or 1)
    except (TypeError, ValueError):
        version = 1
    return _CAMPOS_SHA_V2 if version >= 2 else _CAMPOS_SHA


def firma_debil(evento):
    """True si el evento se firmo con la version vieja (no cubre origen, conf,
    estado ni quien). No es corrupcion: es un libro escrito antes del arreglo,
    y `fsck` lo dice en vez de darlo por bueno."""
    return campos_firmados(evento) is _CAMPOS_SHA


def sha_evento(evento):
    """El sha content-addressed del evento (ESPEC 3.2). Determinista."""
    cuerpo = {k: evento.get(k) for k in campos_firmados(evento)}
    canon = json.dumps(cuerpo, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"))
    return sha14(canon)


# -------------------------------------------------------------- el almacen

class Libro:
    """El fichero `libro.jsonl` de UNA tarea. Un solo escritor por proceso."""

    def __init__(self, directorio):
        self.dir = str(directorio)
        self.ruta = os.path.join(self.dir, "libro.jsonl")
        self.cabecera = os.path.join(self.dir, "cabecera.txt")
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception as exc:
            raise LibroCaido("no pude crear %s" % self.dir, exc)
        # Estado en RAM que se DERIVA del fichero al abrir. No es fuente de
        # verdad: si el proceso muere, se reconstruye leyendo.
        self._n = 0
        self._prev = None
        self.bytes_descartados = 0
        self._recargar()

    # -- lectura -----------------------------------------------------------

    def _crudo(self):
        """Los BYTES del fichero. Binario y no texto a proposito: la
        contabilidad de `bytes_validos` la usa `_sanear` para truncar, y en
        Windows el modo texto cuenta 1 byte donde el disco tiene 2 ('\\r\\n').
        Con esa diferencia, sanear se comia el salto de linea del ultimo evento
        valido y lo convertia en una linea truncada -- una corrupcion CREADA
        por el que venia a repararla."""
        try:
            with open(self.ruta, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return b""
        except Exception as exc:
            raise LibroCaido("no pude leer %s" % self.ruta, exc)

    def _recargar(self):
        eventos, diag = self._parsear()
        self.bytes_descartados = diag["bytes_descartados"]
        if eventos:
            self._n = int(eventos[-1]["n"])
            self._prev = eventos[-1]["sha"]
        else:
            self._n = 0
            self._prev = None
        return diag

    def _parsear(self):
        """Prefijo valido mas largo + diagnostico. NUNCA lanza por corrupcion.

        Se para en la PRIMERA linea que no cierra: seguir leyendo detras de una
        linea rota daria eventos cuyo `prev` apunta a algo que ya no existe, y
        el fold los proyectaria como si nada. Un prefijo corto y dicho en voz
        alta es mejor que un libro completo y mentiroso.
        """
        eventos = []
        diag = {"lineas": 0, "truncadas": 0, "ilegibles": 0, "cadena_rota": 0,
                "bytes_descartados": 0, "bytes_validos": 0, "motivo": ""}
        prev = None
        datos = self._crudo()
        pos = 0
        while pos < len(datos):
            diag["lineas"] += 1
            corte = datos.find(b"\n", pos)
            cerrada = corte >= 0
            fin = (corte + 1) if cerrada else len(datos)
            crudo = datos[pos:fin]
            if not cerrada:
                # Escritura cortada a mitad (el proceso murio). No es basura:
                # es el borde del ultimo `append` que no llego a cerrar.
                diag["truncadas"] += 1
                diag["bytes_descartados"] += len(crudo)
                diag["motivo"] = "linea sin salto final (escritura cortada)"
                break
            texto = crudo.decode("utf-8", "replace").strip()
            if not texto:
                diag["bytes_descartados"] += len(crudo)
                pos = fin
                continue
            try:
                ev = json.loads(texto)
            except Exception:
                diag["ilegibles"] += 1
                diag["bytes_descartados"] += len(crudo)
                diag["motivo"] = "linea %d ilegible" % diag["lineas"]
                break
            if not isinstance(ev, dict) or "sha" not in ev:
                diag["ilegibles"] += 1
                diag["bytes_descartados"] += len(crudo)
                diag["motivo"] = "linea %d sin sha" % diag["lineas"]
                break
            if ev.get("prev") != prev:
                # Dos escritores concurrentes o un fichero editado a mano. El
                # lock deberia impedirlo; que sea DETECTABLE es el punto.
                diag["cadena_rota"] += 1
                diag["bytes_descartados"] += len(crudo)
                diag["motivo"] = ("cadena prev rota en n=%s (esperaba %s, vino %s)"
                                  % (ev.get("n"), prev, ev.get("prev")))
                break
            if ev.get("sha") != sha_evento(ev):
                diag["ilegibles"] += 1
                diag["bytes_descartados"] += len(crudo)
                diag["motivo"] = "sha no casa en n=%s" % ev.get("n")
                break
            prev = ev["sha"]
            diag["bytes_validos"] += len(crudo)
            eventos.append(ev)
            pos = fin
        return eventos, diag

    def leer(self, hasta_tx=None, hasta_n=None, diag=None):
        """Los eventos del LIBRO, prefijo valido mas largo.

        `diag` es un dict OPCIONAL que el llamador pasa para enterarse de la
        corrupcion. Se rellena in-place en vez de devolverse aparte para no
        romper a los llamadores que solo quieren la lista -- pero enterarse es
        posible SIEMPRE, que es la diferencia con esconderlo.
        """
        eventos, d = self._parsear()
        if isinstance(diag, dict):
            diag.clear()
            diag.update(d)
        if hasta_n is not None:
            eventos = [e for e in eventos if int(e["n"]) <= int(hasta_n)]
        if hasta_tx:
            corte = None
            for e in eventos:
                if e.get("t") == "tx" and e.get("id") == hasta_tx:
                    corte = int(e["n"])
            if corte is None:
                raise LibroCaido("no existe el punto de rollback '%s'" % hasta_tx)
            eventos = [e for e in eventos if int(e["n"]) <= corte]
        return eventos

    # -- escritura ---------------------------------------------------------

    def _lineas_recuperables(self, cola):
        """Las lineas de `cola` que son JSON con `sha` propio VALIDO.

        Detras de una corrupcion EN MEDIO puede haber eventos intactos: su
        cadena `prev` ya no cierra (por eso `_parsear` se para), pero su
        contenido no se ha perdido. Se sacan aparte para que "reparar" no
        signifique "borrar lo que habia detras".
        """
        recuperables, perdidas = [], 0
        for cruda in cola.split(b"\n"):
            texto = cruda.decode("utf-8", "replace").strip()
            if not texto:
                continue
            try:
                ev = json.loads(texto)
            except Exception:
                perdidas += 1
                continue
            if isinstance(ev, dict) and ev.get("sha") == sha_evento(ev):
                recuperables.append(texto)
            else:
                perdidas += 1
        return recuperables, perdidas

    def _sanear(self):
        """Recorta lo que impide que el siguiente append cierre la cadena.

        Devuelve un dict con lo que paso. Sin esto, apendar detras de una linea
        cortada deja un fichero cuyo prefijo valido no crece nunca: el LIBRO
        seguiria aceptando escrituras y `leer()` seguiria devolviendo lo de
        antes. Escribir y que no se lea es peor que no escribir.

        TRES COSAS QUE ANTES NO HACIA, Y LAS TRES COSTABAN MEMORIA (2026-08-19):

        1. NO DISTINGUIA LA COLA DE LA CORRUPCION EN MEDIO. Medido: un libro de
           5 eventos con la linea 3 corrompida perdia 757 bytes -- los eventos
           3, 4 y 5, DOS DE ELLOS con JSON y sha perfectos -- y el CLI lo
           anunciaba como "cola parcial recortada". Ahora lo posterior que
           parsea y tiene sha propio valido se extrae a `libro.jsonl.huerfanos`
           y se cuentan EVENTOS, no bytes.
        2. NO HACIA COPIA. El fichero original desaparecia. Ahora se copia
           entero a `libro.jsonl.corrupto-<ts>` ANTES de tocar nada.
        3. TRUNCABA CON open('wb'). Ese modo pone el fichero a cero ANTES de
           escribir: un Ctrl-C en esa ventana dejaba la memoria de la tarea en
           0 bytes. Y no es un camino raro -- `append` llama aqui en CADA
           escritura. Ahora es tmp + fsync + os.replace, igual que
           `escribir_cabecera` 40 lineas mas abajo.
        """
        eventos, d = self._parsear()
        vacio = {"bytes": 0, "eventos_perdidos": 0, "eventos_rescatados": 0,
                 "motivo": "", "respaldo": "", "huerfanos": "", "solo_cola": True}
        if not (d["truncadas"] or d["ilegibles"] or d["cadena_rota"]):
            return vacio
        solo_cola = bool(d["truncadas"]) and not (d["ilegibles"] or d["cadena_rota"])
        marca = time.strftime("%Y%m%d-%H%M%S")
        respaldo = self.ruta + ".corrupto-" + marca
        huerfanos = ""
        try:
            with open(self.ruta, "rb") as fh:
                crudo = fh.read()
            cola = crudo[d["bytes_validos"]:]
            # 1) la copia ENTERA, antes de tocar nada.
            with open(respaldo, "wb") as fh:
                fh.write(crudo)
                fh.flush()
                os.fsync(fh.fileno())
            # 2) lo que se pueda salvar de detras del corte.
            rescatadas, perdidas = ([], 0) if solo_cola else \
                self._lineas_recuperables(cola)
            if rescatadas:
                huerfanos = self.ruta + ".huerfanos-" + marca
                with open(huerfanos, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write("\n".join(rescatadas) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            # 3) tmp + replace. NUNCA open(self.ruta, 'wb').
            tmp = self.ruta + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(crudo[:d["bytes_validos"]])
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.ruta)
        except Exception as exc:
            raise LibroCaido("no pude sanear la cola de %s" % self.ruta, exc)
        return {
            "bytes": len(crudo) - d["bytes_validos"],
            "eventos_perdidos": int(perdidas),
            "eventos_rescatados": len(rescatadas),
            "motivo": d["motivo"],
            "respaldo": respaldo,
            "huerfanos": huerfanos,
            "solo_cola": solo_cola,
        }

    def append(self, evento, ciclo=None):
        """Apendea UN evento y devuelve su `n`. Lanza `LibroCaido` o
        `EventoInvalido`; NUNCA devuelve en silencio."""
        with _LOCK:
            evento = dict(evento or {})
            evento.pop("n", None)
            evento.pop("sha", None)
            evento.pop("prev", None)
            recortado = self._sanear()
            self._recargar()
            if ciclo is not None:
                evento["ciclo"] = int(ciclo)
            evento.setdefault("ciclo", 0)
            evento.setdefault("refs", [])
            evento.setdefault("ts", time.time())
            evento.setdefault("id", "%s-%04X" % (evento.get("banda", "E"),
                                                 (self._n + 1) & 0xFFFF))
            # La version va ANTES de validar y de firmar: `conf` la rellena
            # `validar` y tiene que quedar dentro de la firma v2.
            evento["v"] = VERSION_EVENTO
            validar(evento)
            evento["n"] = self._n + 1
            evento["sha"] = sha_evento(evento)
            evento["prev"] = self._prev
            linea = json.dumps(evento, ensure_ascii=True,
                               separators=(",", ":")) + "\n"
            try:
                # O_BINARY es OBLIGATORIO en Windows: sin el, os.write traduce
                # cada '\n' a '\r\n' y el fichero deja de coincidir byte a byte
                # con lo que se firmo. En POSIX el flag no existe y vale 0.
                fd = os.open(self.ruta,
                             os.O_WRONLY | os.O_CREAT | os.O_APPEND
                             | getattr(os, "O_BINARY", 0), 0o600)
                try:
                    # UNA sola escritura y un fsync: un corte a mitad deja una
                    # linea sin salto final que `_parsear` reconoce y descarta,
                    # no un evento a medias que parece valido.
                    os.write(fd, linea.encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except Exception as exc:
                raise LibroCaido("no pude apendar el evento n=%d" % evento["n"], exc)
            self._n = evento["n"]
            self._prev = evento["sha"]
            n_escrito = evento["n"]
        if recortado.get("bytes"):
            # Se apenda DESPUES del evento y FUERA del lock: primero se salva
            # lo que el llamador queria escribir, luego se deja la constancia.
            self._contradiccion_por_corte(recortado, evento["ciclo"])
        return n_escrito

    def _contradiccion_por_corte(self, saneo, ciclo):
        """Deja en el propio LIBRO que se recorto algo (ESPEC 8.4: 'lo dice, no
        lo esconde').

        Y dice QUE fue: 'cola parcial' solo cuando de verdad hubo una escritura
        cortada. Llamar 'cola parcial' a una corrupcion en medio hacia que el
        dueno leyera 'el prefijo valido queda intacto' dos lineas despues de
        haber perdido tres eventos.
        """
        if saneo.get("solo_cola"):
            texto = ("se descartaron %d bytes de cola parcial del libro "
                     "(escritura cortada). El prefijo valido queda intacto."
                     % int(saneo.get("bytes") or 0))
        else:
            texto = ("CORRUPCION EN MEDIO (%s): se recortaron %d bytes desde "
                     "ahi. %d evento(s) intactos rescatados a %s, %d "
                     "irrecuperables. Copia entera en %s"
                     % (saneo.get("motivo") or "?", int(saneo.get("bytes") or 0),
                        int(saneo.get("eventos_rescatados") or 0),
                        os.path.basename(saneo.get("huerfanos") or "-"),
                        int(saneo.get("eventos_perdidos") or 0),
                        os.path.basename(saneo.get("respaldo") or "-")))
        self.append({
            "t": "contradiccion", "op": "add", "banda": "E",
            "quien": "harness", "origen": "medido",
            "clave": "cfg:libro.cola_parcial",
            "valor": int(saneo.get("bytes") or 0),
            "texto": texto[:400],
            "prov": {"tipo": "derivada", "fn": "libro._sanear",
                     "base": ["libro.jsonl"],
                     "eventos_rescatados": int(saneo.get("eventos_rescatados") or 0),
                     "eventos_perdidos": int(saneo.get("eventos_perdidos") or 0),
                     "respaldo": saneo.get("respaldo") or "",
                     "huerfanos": saneo.get("huerfanos") or ""},
        }, ciclo=ciclo)

    def escribir_cabecera(self, texto):
        """Doble soporte de la banda P (ESPEC 8.4): si el JSONL se vuelve
        ilegible entero, se pierde el historial pero NO el contrato."""
        try:
            tmp = self.cabecera + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(texto)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.cabecera)
        except Exception as exc:
            raise LibroCaido("no pude escribir cabecera.txt", exc)

    # -- fsck --------------------------------------------------------------

    def fsck(self):
        """El informe de `/libro fsck` (ESPEC 8.4). No repara: informa."""
        eventos, d = self._parsear()
        informe = {
            "eventos": len(eventos),
            "lineas": d["lineas"],
            "truncadas": d["truncadas"],
            "ilegibles": d["ilegibles"],
            "cadena_rota": d["cadena_rota"],
            "bytes_descartados": d["bytes_descartados"],
            "motivo": d["motivo"],
            "esquema_malo": [],
            "verificado_sin_prov": [],
            "firma_debil": [],
            "cabecera_ok": None,
        }
        for e in eventos:
            try:
                validar(dict(e))
            except EventoInvalido as exc:
                informe["esquema_malo"].append((e.get("n"), str(exc)))
            if e.get("estado") == "verificado" and \
                    (e.get("prov") or {}).get("tipo") in (None, "dicha"):
                informe["verificado_sin_prov"].append(e.get("n"))
            if firma_debil(e):
                # Firmado con la version vieja: su sha NO cubre origen, conf,
                # estado ni quien, asi que una edicion a mano de esos cuatro
                # campos es INDETECTABLE en esa fila. No es corrupcion; es una
                # garantia mas floja, y decirlo es la diferencia con esconderlo.
                informe["firma_debil"].append(e.get("n"))
        if os.path.exists(self.cabecera):
            try:
                from cognia.tx.bandas import render_banda_permanente
                with open(self.cabecera, "r", encoding="utf-8") as fh:
                    guardada = fh.read()
                informe["cabecera_ok"] = (
                    sha14(guardada) == sha14(render_banda_permanente(eventos)))
            except Exception:
                informe["cabecera_ok"] = False
        informe["ok"] = (not informe["truncadas"] and not informe["ilegibles"]
                         and not informe["cadena_rota"]
                         and not informe["esquema_malo"])
        return informe


# ------------------------------------------------- el LIBRO de la tarea viva

def abrir(task_id):
    """Abre (o crea) el LIBRO de `task_id` y lo deja como el activo."""
    lib = Libro(dir_tarea(task_id))
    _ACTIVO["libro"] = lib
    _AVISADO["sin_tarea"] = False
    return lib


def activo():
    return _ACTIVO["libro"]


def cerrar():
    _ACTIVO["libro"] = None


def _aviso_degradado(motivo):
    """Un aviso UNA vez por proceso, por stderr. No se traga.

    El unico `pass` de este fichero, y es el del propio canal de avisos: si
    stderr esta cerrado no queda ningun sitio donde quejarse de que no se puede
    uno quejar. Todo lo demas -- disco, permisos, cadena rota -- sube como
    `LibroCaido`.
    """
    try:
        import sys
        sys.stderr.write("[TX] LIBRO degradado: %s\n" % motivo)
    except Exception:
        pass


def registrar_tool(evento, ctx=None):
    """EL HUECO QUE `harness/interceptor._libro` LLAMA. Apendea y devuelve `n`.

    Si no hay tarea abierta el resultado es 0 y se AVISA una vez: con
    COGNIA_TX=1 y sin `/tx iniciar` no hay ningun libro contra el que escribir,
    y eso es un estado legitimo -- distinto de "no pude escribir", que lanza.
    """
    lib = _ACTIVO["libro"]
    if lib is None:
        if not _AVISADO["sin_tarea"]:
            _AVISADO["sin_tarea"] = True
            _aviso_degradado("COGNIA_TX=1 pero no hay tarea abierta "
                             "(/tx iniciar); las llamadas no se registran")
        return 0
    ciclo = None
    try:
        ciclo = (ctx or {}).get("_tx_ciclo")
    except Exception:
        ciclo = None
    ev = dict(evento or {})
    ev.setdefault("banda", "E")
    # `ok`, `exit_code` y `ruta_destino` los pone el envelope del interceptor
    # para el resto del arnes; el esquema del LIBRO no los tiene. Se guardan
    # dentro de `prov`, donde SI son provenance, en vez de tirarlos.
    prov = dict(ev.get("prov") or {})
    for campo in ("ok", "exit_code", "ruta_destino"):
        if campo in ev:
            prov.setdefault(campo, ev.pop(campo))
    ev["prov"] = prov
    return lib.append(ev, ciclo=ciclo)
