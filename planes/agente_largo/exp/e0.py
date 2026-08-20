# -*- coding: utf-8 -*-
"""E0 -- EL BRAZO NULO (ESPEC agente largo, seccion 15.5).

PREGUNTA: .la maquinaria de TX aporta algo, o basta con re-emitir el contrato?

METRICA PRIMARIA, DECLARADA ANTES DE CORRER:
    recall_restricciones@N = fraccion de las restricciones de la banda P que
    aparecen LITERALMENTE (por su codigo exacto) en LA RESPUESTA DEL MODELO
    tras N ciclos. Se mide sobre lo que escribe el modelo, jamas sobre la
    proyeccion (ESPEC 6.5 / P0-4: preguntarle a una funcion pura si escribio lo
    que acaba de escribir da 1,000 en el ciclo 1 y en el 500, informacion cero).

SECUNDARIAS: tokens y segundos de MAQUINARIA, ciclos hasta la perdida del
objetivo, demandas satisfechas (las "tareas completadas"), tokens de prompt.

LOS CINCO BRAZOS (intercalados, rotando el orden en cada corrida):
  SIN-MEMORIA B0, EL AZAR: sesion limpia cada ciclo con el objetivo en una
              linea. No compite: fija el SUELO de la metrica. Si este brazo
              sacara mas de 0, el examen se aprobaria adivinando.
  ANCHO-200k  ventana entera, sin recorte (la tarea CABE). Aisla la dilucion:
              lo que se pierda aqui se pierde con todo delante.
  ANCHO-2k5   el status quo de Cognia: `loop._recortar_mensajes` IMPORTADO (no
              copiado) mas el truncado por la izquierda que hace llama.cpp
              cuando aun asi no cabe.
  RESUMEN     el antipatron: cuando no cabe, el LLM resume el historial ENTERO
              -- contrato incluido -- y el resumen se vuelve a resumir.
  CONTRATO    B4, EL BRAZO A BATIR: reset cada CADA ciclos re-emitiendo P
              verbatim y nada mas. Cero LIBRO, cero gates, cero Q, cero coste.
  TX          B5: el subsistema completo (LIBRO + proyeccion + 2PC + gates + Q).

PAREADO: las cinco corridas de una misma `corrida` comparten SEMILLA, asi que
ven la MISMA tarea, las MISMAS restricciones y las MISMAS observaciones. Solo
los netos intra-corrida son evidencia: la varianza entre corridas de este
proyecto llego a +-34 puntos.

LO QUE ESTE E0 **NO** ES (dicho antes de los numeros):
  - NO es el E0 de la ESPEC 15.5. Aquel son 12 tareas x 4 h x 2 brazos = 96 h
    de pared. Este corre 18 ciclos y 54 min MEDIDOS. Es una MAQUETA A ESCALA.
  - El brazo ANCHO-2k5 usa n_ctx=1.800 en vez de los 200.192 reales para
    alcanzar el regimen de desbordamiento en 18 ciclos en vez de ~160. El
    MECANISMO es el de produccion (el recorte importado, y el truncado por
    la izquierda del server cuando aun asi no cabe); la ESCALA no lo es, y
    por eso ANCHO-200k corre al lado como control de que CABE.
  - La tarea es sintetica y la escribo yo: *el techo es del disenador de
    examenes*. Por eso hay demandas que un brazo sin la restriccion no puede
    contestar, y por eso ANCHO-200k esta: si TODOS sacan 1,000, el examen es
    facil y el experimento sale plano por construccion, no porque no haya
    efecto.

CORRER:
  venv312\\Scripts\\python.exe planes/agente_largo/exp/e0.py
"""

import json
import os
import random
import re
import shutil
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

os.environ["COGNIA_TX"] = "1"

from cognia.agent import loop as agente_loop                # noqa: E402
from cognia.agent.chat_client import completar              # noqa: E402
from cognia.tx import driver                                # noqa: E402
from cognia.tx import libro as almacen                      # noqa: E402

# --------------------------------------------------------------- constantes

N_CICLOS = 18
N_CORRIDAS = 4              # n>=3 por brazo (doctrina 15.1); 4 para que el
                            # signo tenga 4 observaciones pareadas
CADA = 5                    # ciclos por reset en CONTRATO y en TX
W_CTX = 1800                # n_ctx del brazo estrecho (maqueta a escala).
                            # Elegido para que el brazo ANCHO llegue de
                            # verdad al regimen de DESBORDAMIENTO dentro de
                            # 18 ciclos, y en la MISMA proporcion que la real:
                            # el desbordamiento empieza sobre el ciclo 11 de
                            # 18 (61%), igual que 200k con ~2k tok/ciclo
                            # desborda sobre el ciclo 100 de 160 (62%).
                            # Con 6.000 no llegaba nunca: el recorte de
                            # Cognia deja los mensajes tool en 200 chars y la
                            # ventana nunca supera el n_ctx, con lo cual el
                            # experimento no habria podido distinguir 'no hay
                            # efecto' de 'no lo pude ver'.
CTX_ANCHO = 200192          # el n_ctx REAL del server (medido en /v1/models)
MAX_TOKENS_TURNO = 700
MAX_TOKENS_SONDA = 2500    # las sondas piden hasta 6 lineas verbatim
MAX_TOKENS_Q = 2500        # el turno de Q pide 3 citas literales MAS los
                           # identificadores de la banda T. Con 420 el
                           # razonador se comia el presupuesto y Q salia
                           # 0/3 por finish_reason=length: eso mide el tope
                           # de tokens, no la memoria. `finish_reason` se
                           # cuenta en cada corrida para poder verlo.
SONDAS_OBJETIVO = (6, 11, 15, 18)

SYSTEM = ("Eres un agente que trabaja una tarea larga. Cumples las "
          "restricciones al pie de la letra y citas sus codigos cuando te los "
          "piden. Respondes corto.")


def _tok(texto):
    """Estimador de tokens del repo: 4 chars por token. El mismo para todos
    los brazos, que es lo que hace comparables los numeros entre ellos."""
    return (len(str(texto or "")) + 3) // 4


# ---------------------------------------------------------- la tarea sintetica

def tarea(semilla):
    """La MISMA tarea para los cinco brazos de una corrida (pareado)."""
    rnd = random.Random(semilla)

    def hx(n):
        return "".join(rnd.choice("0123456789abcdef") for _ in range(n))

    obj = "OBJ-" + hx(6).upper()
    mes = rnd.randrange(1, 13)
    legado = "legado_%s.py" % hx(4)
    tope = rnd.randrange(120, 999)
    firma = "FIRMA-" + hx(6).upper()
    fmt = rnd.choice(["AAAA/MM/DD", "DD-MM-AAAA", "AAAA.MM.DD"])
    resp = rnd.choice(["Marisa Olguin", "Hector Paz", "Nadia Ferreyra"])
    carpeta = "informes/2026-%02d/" % mes

    restricciones = [
        {"id": "R-01", "cod": "k" + hx(5), "payload": carpeta,
         "texto": "todo fichero de salida va a la carpeta %s y a ninguna otra" % carpeta,
         "pregunta": "En que carpeta exacta tiene que quedar el fichero de "
                     "salida? Responde SOLO la ruta."},
        {"id": "R-02", "cod": "k" + hx(5), "payload": legado,
         "texto": "queda prohibido tocar el fichero %s bajo cualquier excusa" % legado,
         "pregunta": "Cual es el UNICO fichero que tienes prohibido tocar? "
                     "Responde SOLO el nombre del fichero."},
        {"id": "R-03", "cod": "k" + hx(5), "payload": str(tope),
         "texto": "el tope de filas por tabla es %d, ni una mas" % tope,
         "pregunta": "Cual es el tope de filas por tabla? Responde SOLO el numero."},
        {"id": "R-04", "cod": "k" + hx(5), "payload": firma,
         "texto": "no se publica nada sin la firma %s" % firma,
         "pregunta": "Cual es el codigo de firma sin el cual no se publica? "
                     "Responde SOLO el codigo."},
        {"id": "R-05", "cod": "k" + hx(5), "payload": fmt,
         "texto": "el formato de fecha obligatorio es %s" % fmt,
         "pregunta": None},
        {"id": "R-06", "cod": "k" + hx(5), "payload": resp,
         "texto": "la responsable de aprobar cada entrega es %s" % resp,
         "pregunta": None},
    ]
    for r in restricciones:
        r["linea"] = "%s [%s]: %s" % (r["id"], r["cod"], r["texto"])

    objetivo = ("consolidar el informe trimestral %s a partir de los tres "
                "extractos y dejarlo firmado" % obj)

    # Las demandas: preguntas cuya respuesta la DICTA una restriccion. Un brazo
    # que perdio la restriccion no las puede contestar por sentido comun --
    # esa es la mitigacion del "techo del disenador de examenes".
    demandas = [(4, restricciones[0]), (8, restricciones[2]),
                (13, restricciones[3]), (17, restricciones[1])]

    return {"semilla": semilla, "obj_cod": obj, "objetivo": objetivo,
            "restricciones": restricciones, "demandas": dict(demandas),
            "rnd_obs": random.Random(semilla * 7919 + 13)}


_PLANTILLAS = (
    "============================= test session starts ==============================\n"
    "platform win32 -- Python 3.12.4, pytest-8.2.0\n"
    "rootdir: C:\\proy\\%(mod)s\ncollected %(n)d items\n\n"
    "tests/test_%(mod)s.py %(puntos)s [100%%]\n\n"
    "=========================== %(n)d passed in %(seg).2fs ===========================",

    "Directorio de C:\\proy\\%(mod)s\\datos\n\n"
    "%(fecha)s  10:%(mm)02d    <DIR>          .\n"
    "%(fecha)s  10:%(mm)02d           %(b1)7d extracto_%(mod)s_a.csv\n"
    "%(fecha)s  10:%(mm)02d           %(b2)7d extracto_%(mod)s_b.csv\n"
    "%(fecha)s  10:%(mm)02d           %(b3)7d extracto_%(mod)s_c.csv\n"
    "               3 archivos    %(tot)9d bytes",

    "grep -rn 'total' %(mod)s/\n"
    "%(mod)s/agrega.py:%(l1)d:    total = sum(fila.importe for fila in filas)\n"
    "%(mod)s/agrega.py:%(l2)d:    if total > tope:\n"
    "%(mod)s/informe.py:%(l3)d:    cab = ['concepto', 'importe', 'total']\n"
    "%(mod)s/informe.py:%(l4)d:    escribir(cab, total=total)\n"
    "4 coincidencias en 2 ficheros",

    "[%(fecha)s 10:%(mm)02d:%(ss)02d] INFO  cargador: leidas %(n)d filas de extracto_%(mod)s_a.csv\n"
    "[%(fecha)s 10:%(mm)02d:%(ss)02d] WARN  cargador: %(w)d filas sin importe, se saltan\n"
    "[%(fecha)s 10:%(mm)02d:%(ss)02d] INFO  agrega: %(g)d grupos, importe medio %(imp).2f\n"
    "[%(fecha)s 10:%(mm)02d:%(ss)02d] INFO  informe: plantilla resuelta, %(n)d filas listas\n"
    "[%(fecha)s 10:%(mm)02d:%(ss)02d] DEBUG informe: cache de formato %(hit)d aciertos / %(mis)d fallos",
)


def observacion(t, k):
    """Ruido plausible de ~300-400 tokens: la salida de la herramienta del
    ciclo k. Es el DILUYENTE -- lo que empuja el contrato hacia atras."""
    rnd = t["rnd_obs"]
    mods = ("cargador", "agrega", "informe", "extractor", "cuadre")
    d = {"mod": rnd.choice(mods), "n": rnd.randrange(40, 400),
         "seg": rnd.random() * 9 + 1, "fecha": "1%d/0%d/2026" % (rnd.randrange(0, 9), rnd.randrange(1, 9)),
         "mm": rnd.randrange(0, 60), "ss": rnd.randrange(0, 60),
         "b1": rnd.randrange(10000, 999999), "b2": rnd.randrange(10000, 999999),
         "b3": rnd.randrange(10000, 999999),
         "l1": rnd.randrange(10, 400), "l2": rnd.randrange(10, 400),
         "l3": rnd.randrange(10, 400), "l4": rnd.randrange(10, 400),
         "w": rnd.randrange(0, 30), "g": rnd.randrange(3, 40),
         "imp": rnd.random() * 5000, "hit": rnd.randrange(10, 900),
         "mis": rnd.randrange(0, 90)}
    d["tot"] = d["b1"] + d["b2"] + d["b3"]
    d["puntos"] = "." * min(60, d["n"] // 6 + 8)
    trozos = [(_PLANTILLAS[(k + i) % len(_PLANTILLAS)] % d) for i in range(2)]
    return "\n\n".join(trozos)


def briefing(t):
    """El contrato VERBATIM. Es exactamente lo que re-emite CONTRATO y lo que
    la banda P de TX proyecta byte a byte."""
    lineas = ["OBJETIVO: %s" % t["objetivo"], "",
              "RESTRICCIONES DURAS (citalas por su codigo cuando te lo pidan):"]
    lineas += [" " + r["linea"] for r in t["restricciones"]]
    return "\n".join(lineas)


def consigna(t, k):
    dem = t["demandas"].get(k)
    obs = observacion(t, k)
    if dem is not None:
        cola = ("PREGUNTA DEL CICLO: %s" % dem["pregunta"])
    else:
        cola = ("Responde en UNA linea que empiece por ACCION: con el "
                "siguiente paso concreto.")
    return "CICLO %d. Salida de la herramienta:\n%s\n\n%s" % (k, obs, cola)


# ------------------------------------------------------------------ medidas

def _norm(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip().lower()


def recall_verbatim(respuesta, t):
    """LA PRIMARIA. Una restriccion cuenta como presente si su CODIGO exacto
    aparece en la respuesta. El codigo es aleatorio y no inferible: si esta,
    sobrevivio; no se pudo deducir."""
    r = _norm(respuesta)
    presentes = [x["id"] for x in t["restricciones"] if _norm(x["cod"]) in r]
    return len(presentes) / float(len(t["restricciones"])), presentes


def objetivo_vivo(respuesta, t):
    return _norm(t["obj_cod"]) in _norm(respuesta)


def demanda_ok(respuesta, dem):
    return _norm(dem["payload"]) in _norm(respuesta)


# --------------------------------------------------------------- el backend

class Contador:
    """Todo lo que se le pide al modelo pasa por aqui. Separa TRABAJO de
    MAQUINARIA porque el ratio de maquinaria es una secundaria declarada y
    mezclarlos es exactamente como se maquilla un coste.

    Y REINTENTA UNA VEZ cuando `finish_reason` dice `length`. POR QUE: en la
    primera corrida de E0 (2026-08-19) dos filas del brazo TX salieron 0,500 y
    0,000 de recall. No era memoria: era la sonda cortada por el tope de
    tokens -- una lista de 6 restricciones truncada en la cuarta, y otra vacia
    entera porque el razonador se comio el presupuesto. La doctrina del repo lo
    dice con todas las letras: `finish_reason` y `usage` se miran ANTES de
    atribuirle nada al modelo, y un flaky es un bug del INSTRUMENTO hasta que
    se demuestre lo contrario. El reintento se cuenta y su coste va al cubo que
    corresponde: no es gratis y no se esconde.
    """

    def __init__(self):
        self.trabajo = {"llamadas": 0, "prompt": 0, "salida": 0, "seg": 0.0}
        self.maquinaria = {"llamadas": 0, "prompt": 0, "salida": 0, "seg": 0.0}
        self.errores = []
        self.finish = {}
        self.reintentos_por_corte = 0
        self.cortes_no_recuperados = 0
        self.ultimo_cortado = False

    def _una(self, msgs, max_tokens, cubo):
        t0 = time.time()
        r = completar(msgs, max_tokens=max_tokens, temperature=0.0,
                      via="e0_" + cubo)
        dt = time.time() - t0
        c = getattr(self, cubo)
        c["llamadas"] += 1
        c["seg"] += dt
        u = r.usage or {}
        # `usage` vacio significa NO SE PUDO SABER, nunca 0 (chat_client lo
        # declara). Se cae al estimador y se sigue, en vez de sumar 0.
        pr = u.get("prompt_tokens")
        sa = u.get("completion_tokens")
        c["prompt"] += (int(pr) if isinstance(pr, (int, float))
                        else sum(_tok(m.get("content")) for m in msgs))
        c["salida"] += int(sa) if isinstance(sa, (int, float)) else _tok(r.texto)
        self.finish[r.finish_reason or "?"] = self.finish.get(r.finish_reason or "?", 0) + 1
        if r.error:
            # Un fallo del backend NO es "el modelo no supo": son decisiones
            # opuestas. Se registra y se devuelve marcado.
            self.errores.append({"cubo": cubo, "error": r.error[:200]})
            return "", False
        return (r.texto or ""), (r.finish_reason == "length")

    def llamar(self, msgs, max_tokens, cubo="trabajo"):
        texto, cortado = self._una(msgs, max_tokens, cubo)
        if cortado:
            self.reintentos_por_corte += 1
            texto2, cortado2 = self._una(msgs, max_tokens * 2, cubo)
            if (not cortado2) or len(texto2) > len(texto):
                texto, cortado = texto2, cortado2
        if cortado:
            self.cortes_no_recuperados += 1
            self.errores.append({"cubo": cubo,
                                 "error": "finish_reason=length aun con el "
                                          "doble de presupuesto (%d)" % (max_tokens * 2)})
        self.ultimo_cortado = cortado
        return texto


# ---------------------------------------------------------------- los brazos

class Brazo:
    """Interfaz comun. Todo brazo tiene historial propio y contabilidad propia."""

    def __init__(self, nombre, t, cont):
        self.nombre = nombre
        self.t = t
        self.cont = cont
        self.hist = [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": briefing(t)}]
        self.resets = 0
        self.anchos = 0
        self.maq_seg = 0.0          # segundos de maquinaria NO-LLM
        self.notas = []

    # payload para la API: el rol 'tool' es interno (lo necesita el recorte de
    # Cognia); al server se le manda como 'user' etiquetado. Lo que se mide es
    # la POLITICA de recorte, no el formato de cable.
    def payload(self):
        out = []
        for m in self.hist:
            rol = m["role"]
            if rol == "tool":
                out.append({"role": "user",
                            "content": "[salida de herramienta]\n" + (m.get("content") or "")})
            else:
                out.append({"role": rol, "content": m.get("content") or ""})
        return out

    def antes_del_ciclo(self, k):
        return None

    def despues_del_ciclo(self, k):
        return None

    def turno(self, k):
        self.hist.append({"role": "tool", "content": consigna(self.t, k)})
        texto = self.cont.llamar(self.payload(), MAX_TOKENS_TURNO, "trabajo")
        self.hist.append({"role": "assistant", "content": texto})
        return texto

    def sonda(self, pregunta):
        """Fuera de banda: la pregunta NO entra al historial. Si entrara,
        estaria refrescando el contrato justo antes de medirlo."""
        msgs = self.payload() + [{"role": "user", "content": pregunta}]
        return self.cont.llamar(msgs, MAX_TOKENS_SONDA, "trabajo")

    def tokens_ventana(self):
        return sum(_tok(m.get("content")) for m in self.hist)


class Ancho(Brazo):
    """B2 -- el status quo. `loop._recortar_mensajes` es el de produccion,
    IMPORTADO. Si aun asi no cabe, se trunca por la izquierda: eso es lo que
    hace llama.cpp con context shift, y es el modo de fallo que el docstring
    de `_recortar_mensajes` describe ('el server trunca por izquierda... y el
    agente pierde el objetivo sin que nadie lo diga')."""

    def __init__(self, nombre, t, cont, n_ctx):
        Brazo.__init__(self, nombre, t, cont)
        self.n_ctx = n_ctx
        self.truncados_izq = 0

    def antes_del_ciclo(self, k):
        t0 = time.perf_counter()
        for _ in range(30):
            tk = self.tokens_ventana()
            if tk < int(self.n_ctx * 0.8):
                break
            if not agente_loop._recortar_mensajes(self.hist, self.n_ctx, tk):
                break
        # context shift del server: caen los mensajes MAS VIEJOS (nunca el
        # system, que el server tampoco tira porque va primero en el prompt...
        # pero el briefing SI cae, y ese es justo el punto).
        while self.tokens_ventana() > self.n_ctx and len(self.hist) > 2:
            self.hist.pop(1)
            self.truncados_izq += 1
        self.maq_seg += time.perf_counter() - t0


class Resumen(Brazo):
    """B1 -- el antipatron que el dueno quiere evitar: cuando no cabe, el LLM
    resume el historial ENTERO (contrato incluido) y el resumen se vuelve a
    resumir en la siguiente compactacion. Cascada de resumenes."""

    def __init__(self, nombre, t, cont, n_ctx):
        Brazo.__init__(self, nombre, t, cont)
        self.n_ctx = n_ctx

    def antes_del_ciclo(self, k):
        if self.tokens_ventana() < int(self.n_ctx * 0.8):
            return
        cuerpo = "\n\n".join("[%s] %s" % (m["role"], m.get("content") or "")
                             for m in self.hist[1:])
        msgs = [{"role": "system", "content": "Resumes historiales de trabajo."},
                {"role": "user",
                 "content": ("Resume el historial siguiente para poder seguir "
                             "la tarea sin el original. Se breve.\n\n" + cuerpo)}]
        res = self.cont.llamar(msgs, 900, "maquinaria")
        self.resets += 1
        self.hist = [{"role": "system", "content": SYSTEM},
                     {"role": "user",
                      "content": "RESUMEN DEL TRABAJO PREVIO:\n" + (res or "(vacio)")}]


class SinMemoria(Brazo):
    """B0 -- EL AZAR, y la referencia de todo (ESPEC 15.3).

    Sesion limpia CADA ciclo con el objetivo en una linea y nada mas. No es un
    brazo que compita: es el SUELO de la metrica. Sin el, un 1,000 en todos los
    brazos no se puede leer -- puede ser que la memoria funcione o que el examen
    se apruebe adivinando, y son cosas distintas. La ESPEC 15.7 lo pide con
    todas las letras: "se verifica que B0 falla antes de contar nada".
    """

    def __init__(self, nombre, t, cont):
        Brazo.__init__(self, nombre, t, cont)
        self.linea = "OBJETIVO: %s" % t["objetivo"]
        self.hist = [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": self.linea}]

    def antes_del_ciclo(self, k):
        self.hist = [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": self.linea}]
        self.resets += 1


class Contrato(Brazo):
    """B4 -- EL BRAZO A BATIR. Reset cada CADA ciclos re-emitiendo P verbatim
    y NADA mas. Cero LIBRO, cero gates, cero Q, cero tokens de maquinaria."""

    def despues_del_ciclo(self, k):
        if k % CADA:
            return
        t0 = time.perf_counter()
        self.hist = [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": briefing(self.t)}]
        self.resets += 1
        self.maq_seg += time.perf_counter() - t0


class Tx(Brazo):
    """B5 -- el subsistema completo: LIBRO append-only, proyeccion pura, commit
    2PC con G1..G6, Q1..Q3 en sesion fresca y destruccion de la ventana."""

    def __init__(self, nombre, t, cont, tmp):
        Brazo.__init__(self, nombre, t, cont)
        self.ws = os.path.join(tmp, "tx_ws_%d" % t["semilla"])
        os.makedirs(self.ws, exist_ok=True)
        self.task_id = "e0-tx-%d-%d" % (t["semilla"], int(time.time() * 1000) % 10 ** 6)
        self.ses = driver.iniciar(
            t["objetivo"],
            criterios=['"%s" -c "pass"' % sys.executable],
            restricciones=[r["linea"] for r in t["restricciones"]],
            pasos=CADA, horas=4, workspace=self.ws, task_id=self.task_id,
            semilla=t["semilla"], k_trazadores=4)
        self.salidas = []
        self.gates_fallados = {}
        self.q = []
        proy = self._proyeccion()
        self.hist = [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": proy}]

    def _proyeccion(self):
        from cognia.tx import bandas
        return bandas.proyectar(self.ses["libro"].leer(),
                                topes=dict(self.ses["salud"].get("topes") or {}))

    def _responder(self):
        base = driver.responder_por_defecto(max_tokens=MAX_TOKENS_Q)

        def _r(texto):
            # La Q va al cubo MAQUINARIA: es coste del reset, no trabajo.
            msgs = [{"role": "system",
                     "content": "Responde SOLO con las citas literales pedidas."},
                    {"role": "user", "content": texto}]
            return self.cont.llamar(msgs, MAX_TOKENS_Q, "maquinaria")
        _r.base = base
        return _r

    def _destruir(self):
        def _d(proyeccion):
            self.hist = [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": proyeccion}]
            self.ses["ventana"] = _tok(proyeccion)
        return _d

    def turno(self, k):
        texto = Brazo.turno(self, k)
        # El LIBRO recibe lo del ciclo: el comando MEDIDO (lo que G6 exige) y
        # la prosa del modelo, que va a la banda X con prov 'dicha' -- ahi
        # muere en el reset, que es el corazon anti-alucinacion (ESPEC 3.2).
        try:
            self.ses["libro"].append({
                "t": "comando", "op": "add", "banda": "F",
                "id": "F-C%03d" % k, "quien": "ejecutor", "origen": "medido",
                "estado": "verificado", "clave": "cmd:paso_%03d" % k, "valor": 0,
                "texto": "el paso %d corrio y devolvio exit 0" % k,
                "prov": {"tipo": "ejecutada", "fn": "e0.turno",
                         "cmd": "paso_%03d" % k, "exit": 0, "base": ["subprocess"]},
            }, ciclo=self.ses["ciclo"])
            self.ses["libro"].append({
                "t": "decision", "op": "add", "banda": "X",
                "id": "X-A%03d" % k, "quien": "ejecutor", "origen": "modelo",
                "estado": "hipotesis", "texto": (texto or "(vacio)")[:400],
                "prov": {"tipo": "dicha", "fn": "e0.turno", "base": []},
            }, ciclo=self.ses["ciclo"])
        except Exception as exc:
            self.notas.append("no pude apendar el ciclo %d: %r" % (k, exc))
        driver.paso()
        return texto

    def despues_del_ciclo(self, k):
        if k % CADA:
            return
        t0 = time.perf_counter()
        seg_llm0 = self.cont.maquinaria["seg"]
        res = driver.commit_ya(responder=self._responder(),
                               destruir=self._destruir())
        # Se DESCUENTA lo que se fue en las llamadas de Q: esos segundos ya
        # estan en el cubo de maquinaria-LLM. Sumarlos dos veces inflaria el
        # coste de TX justo en la secundaria que decide si la maquinaria paga.
        self.maq_seg += (time.perf_counter() - t0
                         - (self.cont.maquinaria["seg"] - seg_llm0))
        self.salidas.append(res.get("salida"))
        # `destruido` y `salida` NO son lo mismo: si Q falla, la ventana YA se
        # destruyo y aun asi el commit sale como ANCHO. Contar los resets por
        # `salida` esconderia el caso peor (se destruyo y ademas no se pudo
        # verificar), que es justo el que hay que ver.
        if res.get("destruido"):
            self.resets += 1
        if res.get("salida") != "HECHO":
            self.anchos += 1
        for v in (res.get("gates") or []):
            if not v.get("ok"):
                g = v.get("gate")
                self.gates_fallados[g] = self.gates_fallados.get(g, 0) + 1
        self.q.append(res.get("q"))

    def cerrar(self):
        try:
            driver.cerrar()
        except Exception as exc:
            self.notas.append("no pude cerrar la sesion TX: %r" % exc)
        shutil.rmtree(almacen.dir_tarea(self.task_id), ignore_errors=True)


# ---------------------------------------------------------------- la corrida

# La etiqueta "ANCHO-2k5" quedo del primer tanteo: el n_ctx que corre es
# W_CTX (1.800). NO se renombra porque `e0_out.json` ya lleva ese nombre y
# cambiarlo partiria el pareado con las corridas guardadas; el valor que
# manda esta en `w_ctx` del propio JSON.
ORDEN = ("SIN-MEMORIA", "ANCHO-200k", "ANCHO-2k5", "RESUMEN",
         "CONTRATO", "TX")


def construir(nombre, t, cont, tmp):
    if nombre == "SIN-MEMORIA":
        return SinMemoria(nombre, t, cont)
    if nombre == "ANCHO-200k":
        return Ancho(nombre, t, cont, CTX_ANCHO)
    if nombre == "ANCHO-2k5":
        return Ancho(nombre, t, cont, W_CTX)
    if nombre == "RESUMEN":
        return Resumen(nombre, t, cont, W_CTX)
    if nombre == "CONTRATO":
        return Contrato(nombre, t, cont)
    if nombre == "TX":
        return Tx(nombre, t, cont, tmp)
    raise ValueError("brazo desconocido: %s" % nombre)


PREGUNTA_RECALL = (
    "PARA CERRAR: enumera TODAS las restricciones duras vigentes de esta "
    "tarea, una por linea, con su codigo entre corchetes exactamente como se "
    "te dieron (formato 'R-0x [kxxxxx]: texto'). No inventes ninguna: si no "
    "recuerdas alguna, no la escribas.")
PREGUNTA_OBJETIVO = ("Responde SOLO con el codigo del objetivo de esta tarea "
                     "(empieza por OBJ-). Nada mas.")


def una_corrida(nombre, t, cont, tmp):
    t0 = time.time()
    brazo = construir(nombre, t, cont, tmp)
    demandas = {"n": 0, "ok": 0, "detalle": []}
    obj = []
    ciclo_perdida = None
    ventana_max = 0
    for k in range(1, N_CICLOS + 1):
        brazo.antes_del_ciclo(k)
        ventana_max = max(ventana_max, brazo.tokens_ventana())
        texto = brazo.turno(k)
        dem = t["demandas"].get(k)
        if dem is not None:
            demandas["n"] += 1
            ok = demanda_ok(texto, dem)
            demandas["ok"] += 1 if ok else 0
            demandas["detalle"].append({"ciclo": k, "restriccion": dem["id"],
                                        "ok": ok, "espera": dem["payload"],
                                        "dijo": (texto or "")[:160]})
        brazo.despues_del_ciclo(k)
        if k in SONDAS_OBJETIVO:
            r = brazo.sonda(PREGUNTA_OBJETIVO)
            vivo = objetivo_vivo(r, t)
            obj.append({"ciclo": k, "vivo": vivo, "dijo": (r or "")[:80]})
            if not vivo and ciclo_perdida is None:
                ciclo_perdida = k

    final = brazo.sonda(PREGUNTA_RECALL)
    # Si la sonda de la PRIMARIA salio cortada incluso tras el reintento, la
    # fila no vale: un recall bajo por tope de tokens y uno bajo por memoria
    # perdida se ven identicos y piden decisiones opuestas. Se marca y no se
    # promedia con las demas.
    primaria_cortada = bool(cont.ultimo_cortado)
    rec, presentes = recall_verbatim(final, t)
    fila = {
        "brazo": nombre,
        "semilla": t["semilla"],
        "recall": rec,
        "primaria_cortada": primaria_cortada,
        "presentes": presentes,
        "demandas_ok": demandas["ok"],
        "demandas_n": demandas["n"],
        "objetivo_sondas": obj,
        "ciclo_perdida_objetivo": ciclo_perdida,
        "resets": brazo.resets,
        "anchos": brazo.anchos,
        "ventana_max_tok": ventana_max,
        "maq_seg_no_llm": round(brazo.maq_seg, 3),
        "segundos_corrida": round(time.time() - t0, 1),
        "respuesta_final": (final or "")[:1200],
        "notas": brazo.notas,
        "reintentos_por_corte": cont.reintentos_por_corte,
        "cortes_no_recuperados": cont.cortes_no_recuperados,
        "demandas_detalle": demandas["detalle"],
    }
    if isinstance(brazo, Ancho):
        fila["truncados_izq"] = brazo.truncados_izq
    if isinstance(brazo, Tx):
        fila["salidas_commit"] = brazo.salidas
        fila["gates_fallados"] = brazo.gates_fallados
        fila["q"] = brazo.q
        brazo.cerrar()
    return fila


def main(argv=None):
    """`--solo BRAZO` anade UN brazo a un `e0_out.json` que ya existe, con las
    MISMAS semillas, sin repetir los demas. Las semillas son deterministas, asi
    que el pareado se mantiene; lo que NO se mantiene es el intercalado en el
    tiempo, y por eso un brazo anadido asi se marca `anadido_aparte` y se dice
    en el informe en vez de colarlo como si hubiera corrido a la par."""
    argv = list(sys.argv[1:] if argv is None else argv)
    solo = None
    if "--solo" in argv:
        solo = argv[argv.index("--solo") + 1]
    tmp = os.path.join(os.environ.get("TEMP") or "/tmp", "e0_ws_%d" % os.getpid())
    os.makedirs(tmp, exist_ok=True)
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e0_out.json")
    filas = []
    if solo and os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fh:
            filas = [f for f in json.load(fh)["filas"] if f["brazo"] != solo]
    t_ini = time.time()
    try:
        for c in range(N_CORRIDAS):
            semilla = 4100 + c
            # INTERCALADO: el orden de los brazos ROTA en cada corrida, para
            # que una deriva del backend en el tiempo no caiga siempre sobre
            # el mismo brazo.
            orden = ORDEN[c % len(ORDEN):] + ORDEN[:c % len(ORDEN)]
            if solo:
                orden = [solo]
            for nombre in orden:
                cont = Contador()
                t = tarea(semilla)          # MISMA tarea para los 5 brazos
                print("[e0] corrida %d/%d  brazo %-11s ..."
                      % (c + 1, N_CORRIDAS, nombre), end="", flush=True)
                fila = una_corrida(nombre, t, cont, tmp)
                fila["corrida"] = c
                fila["anadido_aparte"] = bool(solo)
                fila["trabajo"] = cont.trabajo
                fila["maquinaria"] = cont.maquinaria
                fila["errores_backend"] = cont.errores
                fila["finish_reason"] = cont.finish
                filas.append(fila)
                print(" recall %.3f  dem %d/%d  maq %d tok / %.1f s  (%.0f s)"
                      % (fila["recall"], fila["demandas_ok"], fila["demandas_n"],
                         cont.maquinaria["prompt"] + cont.maquinaria["salida"],
                         cont.maquinaria["seg"] + fila["maq_seg_no_llm"],
                         fila["segundos_corrida"]), flush=True)
                with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump({"experimento": "E0", "n_ciclos": N_CICLOS,
                               "n_corridas": N_CORRIDAS, "cada": CADA,
                               "w_ctx": W_CTX, "filas": filas}, fh,
                              ensure_ascii=True, indent=1)
    finally:
        try:
            driver.cerrar()
        except Exception as exc:
            print("[e0] cierre: %r" % exc, file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
    print("[e0] %d filas en %.0f s -> %s" % (len(filas), time.time() - t_ini, ruta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
