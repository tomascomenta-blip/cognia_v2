# -*- coding: utf-8 -*-
"""Las TOOLS que ve el modelo (ESPEC 14.2, bloque M3; matriz 4.2).

LA REGLA QUE GOBIERNA ESTE FICHERO: el modelo NO escribe en el LIBRO en prosa
libre. Escribe por siete puertas tipadas, y cada una tiene un rechazo. La
matriz normativa de la ESPEC 4.2 dice exactamente que puede tocar el ejecutor:

    banda P  ...... NO           banda T ....... NO
    banda N  ...... via `leccion`      (imperativa POSITIVA, o se rechaza)
    banda D  ...... via `decidir`      (estado `hipotesis` + base MEDIDA)
    banda F  ...... via `afirmar`      (con VERIFICADOR que se EJECUTA)
    banda A  ...... NO           banda E ....... via `pendiente`/`resolver`
    banda X  ...... libre (y muere en el reset)

POR QUE CADA RECHAZO EXISTE, y no son manias:

- `decidir` sin base medida: una decision cuya base es una frase del modelo es
  una conclusion sostenida por nada. La poda por dependencia de `bandas.fold`
  la mataria sola si la base se invalidase... pero una base que nunca fue un
  hecho no se puede invalidar: no esta. Ese es el agujero por el que entra la
  alucinacion PERSISTENTE (ESPEC 7.3).
- `afirmar` sin verificador que corra: un critico que solo opina esta medido en
  el azar (0,517). Lo unico que asciende un hecho es un EXIT CODE.
- `leccion` en forma negativa: "no uses pickle" condiciona hacia pickle (por
  ahi entra el self-conditioning) y ademas no dice que hacer. La forma que
  vale es imperativa positiva: "serializar con json.dumps".

TODAS son opt-in: sin COGNIA_TX y sin tarea abierta devuelven un ERROR que
dice cual de los dos falta. Un ERROR y no un silencio: el modelo tiene que
poder distinguir "no esta encendido" de "lo escribi y no paso nada".
"""

import os
import re

MAX_GREP = 40
MAX_TEXTO = 400

# Verificadores que NO pueden fallar. `err:verificador_nulo` de la ESPEC 7.x:
# un `afirmar --verificador "echo ok" --espera exit==0` asciende cualquier
# mentira a hecho verificado con conf 1,00. La lista es corta y literal a
# proposito: detectar "este comando siempre da 0" en general es indecidible, y
# un heuristico que se pase rechazaria verificadores buenos.
VERIFICADORES_NULOS = (
    "true", "exit 0", "echo", "echo ok", "echo si", "cd .", ":", "rem",
    "python -c pass", "python -c ''", 'python -c ""',
)

# La forma negativa que se rechaza en `leccion`. Se compara contra el texto SIN
# diacriticos (`_sin_tildes`) para no tener que escribir la forma con tilde en un fichero
# que es ASCII puro por regla del repo -- y de paso caza 'jamas' sin tilde.
_RE_NEGATIVA = re.compile(
    r"(?i)(?:^|[\s.;,:!?()\"'-])(no|nunca|jamas|evita|evitar|evites|"
    r"prohibido|prohibida|deja\s+de|dejar\s+de|nada\s+de|abstente|"
    r"abstenerse|dont|don t)(?:$|[\s.;,:!?()\"'-])")


def _sin_tildes(texto):
    """NFD + descarte de combinantes. No baja a minusculas: de eso se encarga
    el (?i) del regex, y bajarlo aqui esconderia el texto que se le devuelve
    al modelo en el mensaje de rechazo."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or ""))
                   if not unicodedata.combining(c))


def _partes(args, n):
    """El protocolo texto del repo: 'a | b | c'. Rellena con '' lo que falte."""
    trozos = [t.strip() for t in str(args or "").split("|")]
    while len(trozos) < n:
        trozos.append("")
    return trozos[:n]


def _sesion():
    """(sesion, error). El error dice CUAL de las dos condiciones falta."""
    # `flag.activo()` y no el env pelado: el CLI enciende el subsistema en la
    # config, y leer solo el env hacia que estas 7 puertas dijeran "TX esta
    # apagado" en un REPL cuyo /tx estado decia ACTIVO.
    from cognia.tx.flag import activo as _flag_tx
    if not _flag_tx():
        return None, ("ERROR: el subsistema TX esta apagado. Activalo con "
                      "COGNIA_TX=1 (o /tx on en el REPL).")
    try:
        from cognia.tx import driver
    except Exception as exc:
        return None, "ERROR: no pude importar cognia.tx.driver: %r" % exc
    ses = driver.activa()
    if ses is None:
        return None, ("ERROR: no hay tarea TX abierta. Abrela con "
                      "/tx iniciar \"<objetivo>\" --criterio \"<cmd>\".")
    return ses, ""


def _siguiente(eventos, patron):
    """El siguiente indice libre para una familia de ids. Ver `_pendiente`."""
    tope = 0
    rx = re.compile(patron)
    for e in eventos or []:
        m = rx.match(str(e.get("id") or ""))
        if m:
            tope = max(tope, int(m.group(1)))
    return tope + 1


def _evento_n(eventos, n):
    for e in eventos:
        if int(e.get("n") or 0) == int(n):
            return e
    return None


def _linea(e):
    txt = re.sub(r"\s+", " ", str(e.get("texto") or "")).strip()
    cola = ""
    if e.get("clave"):
        cola = "  [%s=%s]" % (e.get("clave"), e.get("valor"))
    return "n=%s c%s %s %s/%s %s%s" % (
        e.get("n"), e.get("ciclo"), e.get("banda"), e.get("t"),
        e.get("origen"), txt[:200], cola)


# ------------------------------------------------------------- lectura

def _libro_grep(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    patron, banda = _partes(args, 2)
    if not patron:
        return "ERROR: uso libro_grep <patron> [| <banda>]"
    try:
        rx = re.compile(patron, re.IGNORECASE)
    except re.error as exc:
        return "ERROR: patron invalido (%s)" % exc
    eventos = ses["libro"].leer()
    hits = []
    for e in eventos:
        if banda and str(e.get("banda")) != banda.upper():
            continue
        heno = " ".join(str(e.get(k) or "") for k in ("texto", "clave", "valor",
                                                      "id", "t"))
        if rx.search(heno):
            hits.append(e)
    if not hits:
        return ("libro_grep '%s'%s: 0 de %d eventos. NO significa que el hecho "
                "sea falso, significa que no esta en el LIBRO."
                % (patron, (" banda " + banda.upper()) if banda else "",
                   len(eventos)))
    recorte = hits[-MAX_GREP:]
    out = ["libro_grep '%s': %d hits (muestro los %d ultimos)"
           % (patron, len(hits), len(recorte))]
    out += [_linea(e) for e in recorte]
    return "\n".join(out)


def _libro_ver(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    sn, sk = _partes(args, 2)
    try:
        n = int(sn)
    except (TypeError, ValueError):
        return "ERROR: uso libro_ver <n> [| <contexto>]"
    try:
        k = max(0, int(sk)) if sk else 0
    except ValueError:
        k = 0
    eventos = ses["libro"].leer()
    e = _evento_n(eventos, n)
    if e is None:
        return ("ERROR: no existe el evento n=%d (el LIBRO tiene %d)"
                % (n, len(eventos)))
    out = ["evento n=%d  id=%s  banda=%s  t=%s  op=%s  ciclo=%s"
           % (n, e.get("id"), e.get("banda"), e.get("t"), e.get("op"),
              e.get("ciclo")),
           "origen=%s conf=%s estado=%s" % (e.get("origen"), e.get("conf"),
                                            e.get("estado")),
           "texto: " + str(e.get("texto") or ""),
           "prov: " + str(e.get("prov") or {})]
    if k:
        out.append("-- vecinos --")
        for v in eventos:
            vn = int(v.get("n") or 0)
            if vn != n and abs(vn - n) <= k:
                out.append(_linea(v))
    base = [str(b) for b in ((e.get("prov") or {}).get("base") or [])]
    if base:
        out.append("-- cadena de base --")
        for b in base:
            m = re.match(r"^n:(\d+)$", b)
            padre = _evento_n(eventos, int(m.group(1))) if m else None
            out.append(("  " + _linea(padre)) if padre else ("  " + b))
    return "\n".join(out)


# ------------------------------------------------------------- escritura

def _decidir(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    texto, porque = _partes(args, 2)
    if not texto:
        return ("ERROR: uso decidir <decision> | <porque n,n>  -- el 'porque' "
                "son numeros de evento del LIBRO, no prosa.")
    ns = [t for t in re.split(r"[,\s]+", porque or "") if t]
    if not ns:
        return ("ERROR: decidir RECHAZADO sin base. Cita los n de los eventos "
                "MEDIDOS que la sostienen: 'decidir <texto> | 813,815'. "
                "Buscalos con libro_grep. Una decision sin base es una "
                "conclusion que ningun hecho puede tumbar despues.")
    eventos = ses["libro"].leer()
    base, faltan, flojos = [], [], []
    for s in ns:
        try:
            n = int(s)
        except ValueError:
            faltan.append(s)
            continue
        e = _evento_n(eventos, n)
        if e is None:
            faltan.append(s)
        elif e.get("origen") in ("medido", "usuario"):
            base.append(e)
        else:
            flojos.append((n, e.get("origen")))
    if faltan:
        return ("ERROR: decidir RECHAZADO: no existen en el LIBRO los eventos "
                "%s. Cita solo n que hayas visto con libro_grep/libro_ver."
                % ", ".join(faltan))
    if not base:
        return ("ERROR: decidir RECHAZADO: ninguna de las bases es MEDIDA "
                "(%s). Solo cuentan los eventos con origen 'medido' (un exit "
                "code real) u 'usuario'. Corre el comando que lo demuestre y "
                "cita ESE evento."
                % "; ".join("n=%d origen=%s" % f for f in flojos))
    ident = "D-%04d" % (len(eventos) + 1)
    try:
        n = ses["libro"].append({
            "t": "decision", "op": "add", "banda": "D", "id": ident,
            "quien": "ejecutor", "origen": "derivado", "estado": "hipotesis",
            "texto": str(texto)[:MAX_TEXTO],
            "refs": [int(b.get("n")) for b in base],
            # La provenance la escribe la MAQUINA con los n que se validaron
            # arriba, no lo que el modelo dijo que cito.
            "prov": {"tipo": "derivada", "fn": "tool.decidir",
                     "base": ["n:%d" % int(b.get("n")) for b in base]},
        }, ciclo=ses["ciclo"])
    except Exception as exc:
        return "ERROR: el LIBRO rechazo la decision: %s" % exc
    return ("decision %s anotada (n=%d, banda D, estado=hipotesis) sobre %d "
            "base(s) medida(s). Cae sola si alguna base se invalida."
            % (ident, n, len(base)))


def _verificador_nulo(cmd):
    limpio = str(cmd or "").strip().strip('"').strip("'").lower()
    if limpio in VERIFICADORES_NULOS:
        return True
    return limpio.startswith("echo ")


def _clave_verificador(cmd):
    """La clave canonica del comando (ESPEC 3.4): 'test:<args>' o 'cmd:<args>'.

    La misma que escribe el interceptor por cada llamada a tool, para que
    `_ha_fallado_alguna_vez` pueda cruzarlas. `ruta_destino=""` porque aqui el
    comando no escribe un fichero conocido.
    """
    try:
        from cognia.tx import claves
        clave, _valor = claves.canonica("", cmd, None, exit_code=0,
                                        ruta_destino="")
        return clave
    except Exception:
        return "cmd:" + str(cmd or "")[:120]


def _ha_fallado_alguna_vez(eventos, cmd):
    """True si ESTE comando ya dio un resultado NEGATIVO en este LIBRO.

    EL CONTROL NEGATIVO DE LA ESPEC 1.1: el VERIFICADOR "les corre el control
    negativo antes de que puedan conceder nada". Un verificador que nunca ha
    dado != 0 no ha demostrado que PUEDA fallar, y `VERIFICADORES_NULOS` solo
    caza doce formas literales: `python -c "print('ok')"`, `git --version` o
    `cd ..` no estan en la lista, devuelven 0 siempre, y ascendian cualquier
    frase a hecho VERIFICADO con conf 1,00 en una banda que sobrevive a todos
    los resets. Aqui no se adivina si el comando puede fallar: se mira si YA
    fallo, que es un hecho del LIBRO.
    """
    clave = _clave_verificador(cmd)
    for e in eventos or []:
        if str(e.get("clave") or "") != clave:
            continue
        valor = e.get("valor")
        if valor is False:
            return True                  # 'test:' guarda el booleano exit==0
        if isinstance(valor, int) and not isinstance(valor, bool) and valor != 0:
            return True
        exit_prov = (e.get("prov") or {}).get("exit_code")
        if isinstance(exit_prov, int) and not isinstance(exit_prov, bool) \
                and exit_prov != 0:
            return True
    return False


def _afirmar(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    texto, verificador, espera = _partes(args, 3)
    if not texto or not verificador:
        return ("ERROR: uso afirmar <hecho> | <comando verificador> | "
                "<exit==0 | sha==<sha14>>  -- un hecho sin verificador que "
                "CORRA no asciende: un critico que solo opina esta medido en "
                "el azar (0,517).")
    espera = (espera or "exit==0").strip()
    if _verificador_nulo(verificador):
        return ("ERROR: afirmar RECHAZADO: '%s' es un VERIFICADOR NULO (no "
                "puede fallar). Un verificador que siempre da 0 asciende "
                "cualquier cosa a hecho verificado con conf 1,00."
                % verificador)

    ctx = ctx if isinstance(ctx, dict) else {}
    from cognia.agent import tools as _t
    salida = _t._shell(verificador, ctx, cwd=ses.get("workspace") or "")
    exit_code = ctx.get("_exit")
    medido = isinstance(exit_code, int) and not isinstance(exit_code, bool)

    ok = False
    # 'sha==<sha> --fichero <ruta>'. LAS DOS PIEZAS NUEVAS SON OBLIGATORIAS Y
    # CADA UNA TAPA UN AGUJERO MEDIDO:
    #   - el --fichero: antes se comparaba la cadena que elige el modelo contra
    #     la stdout que elige el modelo. `afirmar el bug esta arreglado |
    #     python -c "print('c0ffee')" | sha==c0ffee` daba un hecho VERIFICADO
    #     con conf 1,00 en la banda F, que es PERSISTENTE: la mentira sobrevive
    #     a todos los resets y sirve de base MEDIDA para fabricar decisiones.
    #     Ahora el sha se calcula sobre un ARTEFACTO del disco, que el modelo
    #     no puede elegir a la vez que la expectativa.
    #   - el exit 0: antes bastaba con que hubiera un exit CUALQUIERA.
    m = re.match(r"^sha==([0-9a-fA-F]{6,64})(?:\s+--fichero\s+(.+))?$", espera)
    ruta_sha = ""
    if m:
        ruta_sha = (m.group(2) or "").strip().strip('"').strip("'")
        if not ruta_sha:
            return ("ERROR: 'sha==<sha>' a secas ya no vale: comparaba la "
                    "cadena que elegis vos contra la salida del comando que "
                    "elegis vos, y eso asciende cualquier frase a hecho "
                    "VERIFICADO en una banda que sobrevive a todos los resets. "
                    "Usa 'sha==<sha14> --fichero <ruta>': el sha se lee del "
                    "DISCO.")
    if m and ruta_sha:
        if not medido or exit_code != 0:
            return ("afirmar RECHAZADO: el verificador '%s' dio exit=%r. Para "
                    "un sha se exige exit 0: si el comando que produce el "
                    "artefacto fallo, el fichero que hay en disco no es el que "
                    "el comando dice haber hecho.\ncola: %s"
                    % (verificador, exit_code, str(salida or "")[-300:]))
        from cognia.tx import claves as _claves
        absoluta = _claves.normalizar_ruta(ruta_sha, ses.get("workspace") or "")
        real = _claves.sha_de_fichero(absoluta)
        if real is None:
            return ("afirmar RECHAZADO: no pude leer '%s' para hashearlo. No "
                    "significa que el hecho sea falso: significa que no hay "
                    "artefacto que medir." % absoluta)
        pedido = m.group(1).lower()
        # Prefijo y no igualdad estricta: el LIBRO usa sha256[:14] y el dueno
        # puede pegar los 64 del sha completo o los 14 de una fila.
        ok = real.startswith(pedido) or pedido.startswith(real)
        if not ok:
            salida = "%s\nsha en disco de %s: %s (esperado %s)" % (
                salida or "", absoluta, real, pedido)
    elif espera in ("exit==0", "exit == 0", ""):
        ok = (exit_code == 0)
    elif re.match(r"^exit==-?\d+$", espera.replace(" ", "")):
        ok = medido and exit_code == int(espera.replace(" ", "")[6:])
    else:
        return ("ERROR: no entiendo la espera '%s'. Formas validas: 'exit==0', "
                "'exit==<n>', 'sha==<sha14> --fichero <ruta>'." % espera)

    if not ok:
        # NO entra en banda F, pero SI queda constancia: "el verificador dijo
        # que no" es informacion, y tirarla es el vacio silencioso.
        try:
            ses["libro"].append({
                "t": "verificacion", "op": "add", "banda": "E",
                "quien": "ejecutor", "origen": "medido" if medido else "derivado",
                "estado": "hipotesis",
                # Clave CANONICA: este fallo es la prueba de que el verificador
                # PUEDE fallar, y `_ha_fallado_alguna_vez` lo busca por clave.
                "clave": _clave_verificador(verificador),
                "valor": exit_code if medido else None,
                "texto": ("verificador NEGO la afirmacion: %s" % texto)[:MAX_TEXTO],
                "prov": {"tipo": "ejecutada" if medido else "derivada",
                         "cmd": verificador[:120], "exit_code": exit_code,
                         "cola": str(salida or "")[-160:],
                         "base": ["exit_code:%r" % exit_code]},
            }, ciclo=ses["ciclo"])
        except Exception as exc:
            return "ERROR: el LIBRO rechazo la verificacion fallida: %s" % exc
        if not medido:
            # exit None NO es exit != 0: el comando no llego a correr
            # (bloqueado por el sentinel, timeout, denegado). Confundir los dos
            # es P0-1 al reves -- el modelo concluiria que su hecho es falso
            # cuando lo que pasa es que nadie lo midio.
            return ("afirmar RECHAZADO: el verificador '%s' NO LLEGO A "
                    "EJECUTARSE (exit=None: bloqueado, denegado o timeout). "
                    "Eso NO significa que el hecho sea falso: significa que no "
                    "se midio nada, y sin medida no hay ascenso.\ncola: %s"
                    % (verificador, str(salida or "")[-300:]))
        return ("afirmar RECHAZADO: el verificador '%s' dio exit=%r y se "
                "esperaba '%s'. El hecho NO entra en la banda F; queda la "
                "verificacion fallida en banda E.\ncola: %s"
                % (verificador, exit_code, espera, str(salida or "")[-300:]))

    eventos = ses["libro"].leer()
    # CONTROL NEGATIVO (ESPEC 1.1, componente VERIFICADOR). Un `sha== --fichero`
    # ya se sostiene solo -- el sha sale del disco, no de la stdout que el
    # modelo eligio -- asi que solo se le exige al `exit==`.
    if not ruta_sha and not _ha_fallado_alguna_vez(eventos, verificador):
        try:
            ses["libro"].append({
                "t": "verificacion", "op": "add", "banda": "E",
                "quien": "ejecutor", "origen": "medido", "estado": "hipotesis",
                "clave": _clave_verificador(verificador), "valor": exit_code,
                "texto": ("HIPOTESIS (verificador sin poder discriminante "
                          "demostrado): %s" % texto)[:MAX_TEXTO],
                "prov": {"tipo": "ejecutada", "cmd": verificador[:120],
                         "exit_code": exit_code, "espera": espera,
                         "cola": str(salida or "")[-160:]},
            }, ciclo=ses["ciclo"])
        except Exception as exc:
            return "ERROR: el LIBRO rechazo la hipotesis: %s" % exc
        return ("afirmar NO ASCIENDE a la banda F: '%s' dio exit 0, pero en "
                "este LIBRO ese comando no ha dado NUNCA un exit distinto de "
                "0. Un verificador que jamas ha fallado no ha demostrado que "
                "PUEDA fallar, y sin eso su exit 0 no distingue tu hecho de "
                "cualquier otra frase.\nQueda anotado como HIPOTESIS en la "
                "banda E. Para ascenderlo: corre el verificador contra el caso "
                "que TIENE que fallar (asi queda su fallo en el LIBRO), o "
                "afirma sobre un artefacto con 'sha==<sha14> --fichero "
                "<ruta>'." % verificador)

    ident = "F-%04d" % (len(eventos) + 1)
    try:
        n = ses["libro"].append({
            "t": "afirmacion", "op": "add", "banda": "F", "id": ident,
            "quien": "ejecutor", "origen": "medido", "estado": "verificado",
            "clave": _clave_verificador(verificador), "valor": exit_code,
            "texto": str(texto)[:MAX_TEXTO],
            "prov": {"tipo": "ejecutada", "cmd": verificador[:120],
                     "exit_code": exit_code, "espera": espera,
                     "cola": str(salida or "")[-160:]},
        }, ciclo=ses["ciclo"])
    except Exception as exc:
        return "ERROR: el LIBRO rechazo la afirmacion: %s" % exc
    return ("hecho %s VERIFICADO (n=%d, banda F): '%s' dio exit=%r y cumple "
            "'%s'." % (ident, n, verificador, exit_code, espera))


def _pendiente(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    texto = str(args or "").strip()
    if not texto:
        return "ERROR: uso pendiente <que falta>"
    # El id se deriva de los IDS YA USADOS, no de contar eventos (mismo
    # comentario en `cli._libro_restringir`): contar tambien funciona hoy, pero
    # apoyandose en que el LIBRO nunca encoge y en que `resolver` no estrena id.
    # Un id repetido no falla ruidosamente: en el fold `vivos[id] = evento`.
    ident = "E-P%03d" % (_siguiente(ses["libro"].leer(), r"^E-P(\d+)$"))
    try:
        n = ses["libro"].append({
            "t": "pendiente", "op": "add", "banda": "E", "id": ident,
            "quien": "ejecutor", "origen": "modelo", "estado": "hipotesis",
            "texto": texto[:MAX_TEXTO],
            # banda E no es persistente: aqui `dicha` SI vale, y es lo honesto.
            "prov": {"tipo": "dicha", "fn": "tool.pendiente"},
        }, ciclo=ses["ciclo"])
    except Exception as exc:
        return "ERROR: el LIBRO rechazo el pendiente: %s" % exc
    return "pendiente %s anotado (n=%d, banda E). Cierralo con: resolver %s" % (
        ident, n, ident)


def _resolver(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    clave = str(args or "").strip()
    if not clave:
        return "ERROR: uso resolver <id-del-pendiente>"
    eventos = ses["libro"].leer()
    vivos = [e for e in eventos if e.get("t") == "pendiente"]
    victima = None
    for e in vivos:
        if str(e.get("id")) == clave or clave.lower() in str(e.get("texto") or "").lower():
            victima = e
    if victima is None:
        return ("ERROR: no encuentro ningun pendiente que case con '%s'. "
                "Los vivos: %s" % (clave, ", ".join(str(e.get("id")) for e in vivos) or "ninguno"))
    try:
        # op='invalidate' y no 'resolve': `bandas.fold` (M1) interpreta
        # invalidate/supersede y NO interpreta resolve, asi que un `resolve`
        # dejaria el pendiente VIVO en la proyeccion y nadie se enteraria --
        # el vacio silencioso, otra vez. Cuando el fold aprenda `resolve`,
        # esto cambia aqui y en un solo sitio.
        n = ses["libro"].append({
            "t": "pendiente", "op": "invalidate", "banda": "E",
            "id": victima.get("id"), "quien": "ejecutor", "origen": "derivado",
            "texto": ("RESUELTO: " + str(victima.get("texto") or ""))[:MAX_TEXTO],
            "prov": {"tipo": "derivada", "fn": "tool.resolver",
                     "base": ["n:%s" % victima.get("n")]},
        }, ciclo=ses["ciclo"])
    except Exception as exc:
        return "ERROR: el LIBRO rechazo el resolver: %s" % exc
    return "pendiente %s RESUELTO (n=%d): sale de la proyeccion viva." % (
        victima.get("id"), n)


def _leccion(args, ctx=None):
    ses, err = _sesion()
    if err:
        return err
    texto = str(args or "").strip()
    if not texto:
        return "ERROR: uso leccion <que hacer, en imperativo POSITIVO>"
    m = _RE_NEGATIVA.search(" " + _sin_tildes(texto) + " ")
    if m:
        return ("ERROR: leccion RECHAZADA por forma NEGATIVA ('%s'). La forma "
                "negativa condiciona hacia justo lo que prohibe y ademas no "
                "dice que hacer en su lugar. Reescribela en imperativo "
                "positivo: en vez de 'no uses pickle', 'serializar con "
                "json.dumps'." % m.group(1))
    try:
        n = ses["libro"].append({
            "t": "leccion", "op": "add", "banda": "N",
            "quien": "ejecutor", "origen": "derivado", "estado": "hipotesis",
            "texto": texto[:MAX_TEXTO],
            "prov": {"tipo": "derivada", "fn": "tool.leccion",
                     "base": ["ciclo:%s" % ses["ciclo"]]},
        }, ciclo=ses["ciclo"])
    except Exception as exc:
        return "ERROR: el LIBRO rechazo la leccion: %s" % exc
    return "leccion anotada (n=%d, banda N, imperativa positiva)." % n


# ------------------------------------------------------------- registro

def register(tool):
    """Registra las 7 tools del LIBRO en el registry de `agent/tools.py`.

    Se llama SOLO con COGNIA_TX=1 (mismo patron que las tools VLM): con el
    flag apagado el registry no cambia ni un byte, que es la condicion que
    puso el dueno para todo este subsistema.
    """
    tool("libro_grep",
         "libro_grep <patron> | <banda>         -- buscar en el LIBRO (memoria de la tarea)",
         desc=("Busca un regex en TODOS los eventos del LIBRO de la tarea "
               "larga (no solo en lo que cabe en la proyeccion). Es la via "
               "para recuperar lo que el tope de una banda dejo fuera."),
         params=[{"nombre": "patron", "tipo": "string", "requerido": True,
                  "descripcion": "regex a buscar (case-insensitive)"},
                 {"nombre": "banda", "tipo": "string", "requerido": False,
                  "descripcion": "limitar a una banda: P,T,N,D,F,A,E,Q,X"}])(_libro_grep)
    tool("libro_ver",
         "libro_ver <n> | <contexto>            -- ver un evento del LIBRO y sus vecinos",
         desc=("Muestra el evento n del LIBRO entero (texto, provenance, "
               "estado), sus vecinos y la cadena de eventos en que se basa."),
         params=[{"nombre": "n", "tipo": "integer", "requerido": True,
                  "descripcion": "numero de evento"},
                 {"nombre": "contexto", "tipo": "integer", "requerido": False,
                  "descripcion": "cuantos vecinos mostrar a cada lado"}])(_libro_ver)
    tool("decidir",
         "decidir <decision> | <porque n,n>     -- anotar una decision con su base MEDIDA",
         desc=("Anota una decision en la banda D citando los numeros de los "
               "eventos MEDIDOS que la sostienen. SE RECHAZA sin base medida: "
               "una decision sin base no la puede tumbar ningun hecho "
               "posterior. Busca los n con libro_grep."),
         params=[{"nombre": "decision", "tipo": "string", "requerido": True,
                  "descripcion": "que se decide, en una frase"},
                 {"nombre": "porque", "tipo": "string", "requerido": True,
                  "descripcion": "numeros de evento separados por coma"}])(_decidir)
    tool("afirmar",
         "afirmar <hecho> | <verificador> | <espera>  -- anotar un hecho que un comando DEMUESTRA",
         desc=("Anota un hecho en la banda F ejecutando el verificador y "
               "exigiendo el resultado esperado (exit==0, exit==<n> o "
               "sha==<sha14> --fichero <ruta>). Si el verificador no cumple, "
               "el hecho NO entra: queda la verificacion fallida. Un "
               "verificador que no puede fallar se rechaza, y uno que nunca "
               "ha fallado en este LIBRO solo produce una HIPOTESIS."),
         params=[{"nombre": "hecho", "tipo": "string", "requerido": True,
                  "descripcion": "el hecho, en una frase"},
                 {"nombre": "verificador", "tipo": "string", "requerido": True,
                  "descripcion": "comando que lo demuestra"},
                 {"nombre": "espera", "tipo": "string", "requerido": False,
                  "descripcion": "exit==0 (por defecto), exit==<n> o "
                                 "sha==<sha14> --fichero <ruta>"}])(_afirmar)
    tool("pendiente",
         "pendiente <que falta>                 -- anotar algo que queda por hacer",
         desc=("Anota en la banda E algo que falta. Sobrevive al reset del "
               "contexto; la charla no."),
         params=[{"nombre": "texto", "tipo": "string", "requerido": True,
                  "descripcion": "que falta"}])(_pendiente)
    tool("resolver",
         "resolver <id-del-pendiente>           -- cerrar un pendiente",
         desc=("Cierra un pendiente por su id (E-Pnnn) o por un trozo de su "
               "texto. No se borra nada: se invalida y se deja marcado."),
         params=[{"nombre": "id", "tipo": "string", "requerido": True,
                  "descripcion": "id del pendiente o parte de su texto"}])(_resolver)
    tool("leccion",
         "leccion <que hacer>                   -- anotar una leccion IMPERATIVA POSITIVA",
         desc=("Anota en la banda N que HACER la proxima vez. La forma "
               "negativa ('no uses X', 'nunca Y') se RECHAZA: condiciona "
               "hacia lo que prohibe y no dice que hacer en su lugar."),
         params=[{"nombre": "texto", "tipo": "string", "requerido": True,
                  "descripcion": "la leccion, en imperativo positivo"}])(_leccion)
