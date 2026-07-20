"""
reparacion.py — Disyuntor de reparacion: corta la espiral de parches.

Nucleo compartido por los dos consumidores: la disciplina de sesiones de
trabajo (cognia/disciplina/__main__.py) y el bucle de auto-correccion de
Cognia (cognia/agent/tool_synthesis.py).

LA IDEA CENTRAL, en una frase: si escribiste codigo dos veces y el sintoma no
cambio ni un caracter, no estas resolviendo, estas adivinando.

Sin dependencias externas: solo stdlib.
"""

import hashlib
import json
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

# ── Umbrales ───────────────────────────────────────────────────────────────
# Los tres primeros vienen de sistemas reales, verificados en su codigo fuente,
# no de intuicion. No cambiarlos sin medir.

# Aider: `max_reflections = 3` en aider/coders/base_coder.py, y esta
# hardcodeado — el proyecto mas maduro del sector ni siquiera lo expone.
MAX_INTENTOS = 3

# OpenHands StuckDetector, umbral `action_error`: misma accion -> error, 3
# veces. Es mas bajo que el de misma-observacion (4) a proposito: repetir algo
# que YA fallo es peor senal que repetir algo que solo no avanza.
MISMO_ERROR_CONSECUTIVO = 3

# OpenHands, ventana de eventos que mira el detector.
VENTANA = 20

# El corazon del disyuntor, y el unico umbral que NO viene de la literatura.
# Dos intentos que escribieron codigo y dejaron el sintoma identico. Es mas
# especifico que los detectores de accion repetida: el agente puede escribir
# diffs DISTINTOS que producen el MISMO fallo, y eso es exactamente "parche
# encima de parche". Ningun detector de OpenHands lo ve.
HUELLA_REPETIDA_CORTA = 2


# ── Normalizacion ──────────────────────────────────────────────────────────
# Obligatoria. Sin esto la huella nunca coincide consigo misma y el disyuntor
# queda muerto sin que nadie se entere: cada intento parece un sintoma nuevo.

_REGLAS = [
    (re.compile(r"0x[0-9a-fA-F]+"),                      "0xADDR"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ][\d:.,]+"),       "TS"),
    (re.compile(r"\bline \d+"),                          "line N"),
    (re.compile(r":\d+:"),                               ":N:"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"]+|/[^\s'\"]{4,}"),  "RUTA"),
    (re.compile(r"\bat 0x[0-9a-f]+>"),                   "at 0xADDR>"),
    (re.compile(r"\s+"),                                 " "),
]


def normalizar(texto: str) -> str:
    """
    Quita del texto de error todo lo que cambia entre corridas sin que el
    problema cambie: direcciones de memoria, timestamps, numeros de linea y
    rutas absolutas.
    """
    salida = texto or ""
    for patron, reemplazo in _REGLAS:
        salida = patron.sub(reemplazo, salida)
    return salida.strip().lower()


@dataclass(frozen=True)
class HuellaSintoma:
    """Identidad estable de un fallo, para poder decir 'es el mismo de antes'."""
    tipo:     str = ""    # 'AssertionError', 'SyntaxError', 'verificacion'...
    mensaje:  str = ""    # mensaje ya normalizado
    marcos:   tuple = ()  # top-3 (archivo, funcion), SIN numero de linea

    def clave(self) -> str:
        crudo = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:12]

    def __str__(self) -> str:
        return f"{self.tipo or 'fallo'}[{self.clave()}] {self.mensaje[:70]}"


_RE_TIPO   = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning))\b")
_RE_MARCO  = re.compile(r'File "([^"]+)", line \d+, in (\S+)')


def _nombre_de_marco(ruta: str) -> str:
    """
    Nombre de archivo estable para la huella.

    Un archivo bajo el directorio temporal del sistema NUNCA forma parte de la
    identidad de un sintoma: su nombre es aleatorio y cambia en cada corrida.

    Medido: el sandbox de Cognia ejecuta el codigo generado en
    cognia_prog_uqu_v78_.py una vez y cognia_prog_nqhqvbmk.py la siguiente.
    Con el nombre crudo, dos fallos IDENTICOS daban huellas distintas y el
    disyuntor no disparaba nunca — muerto en silencio, que es el peor modo de
    fallar para un mecanismo de seguridad.
    """
    p = Path(ruta)
    try:
        temp = Path(tempfile.gettempdir()).resolve()
        if temp in p.resolve().parents:
            return "<temp>"
    except (OSError, ValueError):
        pass
    return p.name


def huella_de_texto(texto: str, tipo: str = "") -> HuellaSintoma:
    """
    Construye la huella a partir de un traceback o de un mensaje de error.

    Extrae el tipo de excepcion y los tres marcos superiores del traceback si
    los hay; si no, se queda con el mensaje normalizado, que sigue sirviendo.
    """
    texto = texto or ""

    marcos = tuple(
        (_nombre_de_marco(archivo), funcion)
        for archivo, funcion in _RE_MARCO.findall(texto)[:3]
    )

    if not tipo:
        # El tipo suele estar en la ultima linea del traceback.
        for linea in reversed([l.strip() for l in texto.splitlines() if l.strip()]):
            m = _RE_TIPO.match(linea)
            if m:
                tipo = m.group(1)
                break

    return HuellaSintoma(tipo=tipo, mensaje=normalizar(texto)[:400], marcos=marcos)


# ── Registro de intentos ───────────────────────────────────────────────────

@dataclass
class Intento:
    """
    Un intento de reparacion.

    `hubo_cambio` es la diferencia entre explorar y parchear. Leer, buscar y
    probar hipotesis sin editar NO cuenta para el disyuntor: lo que se mide
    son escrituras esteriles, no exploracion. Sin esta distincion el
    disyuntor castiga la depuracion sana, que es el falso positivo que hace
    que la gente lo desactive.
    """
    n:           int
    clave:       str
    ok:          bool
    hubo_cambio: bool = True
    nota:        str  = ""
    t:           float = field(default_factory=time.time)


class Disyuntor:
    """
    Cuenta intentos de reparacion sobre un mismo sintoma y ordena parar.

    Uso:
        d = Disyuntor("arreglar ranking")
        d.registrar(huella_de_texto(salida_del_test), ok=False)
        if d.motivo_corte():
            print(d.orden_de_modo_raiz())
    """

    def __init__(self, tarea: str = "", ruta_log: Optional[Path] = None,
                 max_intentos: int = MAX_INTENTOS):
        self.tarea        = tarea
        self.max_intentos = max_intentos
        self.ruta_log     = Path(ruta_log) if ruta_log else None
        self.intentos: List[Intento] = []
        self.cortes = 0

    # ── registro ────────────────────────────────────────────────────────

    def registrar(self, huella: HuellaSintoma, ok: bool,
                  hubo_cambio: bool = True, nota: str = "") -> Intento:
        intento = Intento(
            n           = len(self.intentos) + 1,
            clave       = huella.clave(),
            ok          = ok,
            hubo_cambio = hubo_cambio,
            nota        = nota,
        )
        self.intentos.append(intento)
        self._persistir(intento)
        return intento

    def _persistir(self, intento: Intento) -> None:
        """
        Append-only. Nunca se sobrescribe ni se resume: este registro es lo
        unico que permite calibrar los umbrales despues con datos propios.
        """
        if not self.ruta_log:
            return
        self.ruta_log.parent.mkdir(parents=True, exist_ok=True)
        linea = json.dumps(
            {"tarea": self.tarea, **asdict(intento)}, ensure_ascii=False
        )
        with self.ruta_log.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")

    # ── decision ────────────────────────────────────────────────────────

    def _esteriles(self) -> List[Intento]:
        """
        Intentos fallidos que SI escribieron algo, DESDE EL ULTIMO VERDE.

        Un exito corta la racha. Sin esto el disyuntor se quedaba disparado
        para siempre: medido el 2026-07-20, tras dos fallos con la misma
        huella seguidos de un arreglo CORRECTO, motivo_corte() seguia
        devolviendo D6, y un fallo nuevo y distinto devolvia D1. O sea que
        una vez que saltaba ya no dejaba trabajar aunque el problema estuviera
        resuelto, y cualquier lazo de reparacion apoyado en el se bloqueaba
        entero.

        Es la misma regla que reset_por_intervencion, que ya documenta este
        modulo copiando a OpenHands: si hay progreso dentro de la ventana,
        solo cuentan los eventos posteriores. Un verde es progreso al menos
        tan fuerte como que hable el humano.
        """
        ventana = self.intentos[-VENTANA:]

        ultimo_verde = -1
        for idx, intento in enumerate(ventana):
            if intento.ok:
                ultimo_verde = idx

        return [i for i in ventana[ultimo_verde + 1:]
                if not i.ok and i.hubo_cambio]

    def motivo_corte(self) -> Optional[str]:
        """
        Devuelve el codigo del disparo, o None si se puede seguir.

        D6 va primero a proposito: es el diagnostico mas informativo. Decir
        "escribiste 2 veces y el sintoma no se movio" ayuda mas que decir
        "llegaste al limite de intentos".
        """
        esteriles = self._esteriles()

        # D6 — misma huella tras N intentos que escribieron codigo.
        if len(esteriles) >= HUELLA_REPETIDA_CORTA:
            ultimas = [i.clave for i in esteriles[-HUELLA_REPETIDA_CORTA:]]
            if len(set(ultimas)) == 1:
                return "D6"

        # D2 — misma accion -> mismo error, consecutivas (umbral de OpenHands).
        if len(esteriles) >= MISMO_ERROR_CONSECUTIVO:
            ultimas = [i.clave for i in esteriles[-MISMO_ERROR_CONSECUTIVO:]]
            if len(set(ultimas)) == 1:
                return "D2"

        # Ciclo: una huella que ya se habia visto y se creia superada.
        claves = [i.clave for i in esteriles]
        if len(claves) >= 3 and claves[-1] in claves[:-2]:
            return "D6b"

        # D1 — limite duro de intentos (umbral de Aider).
        if len(esteriles) >= self.max_intentos:
            return "D1"

        return None

    def reset_por_intervencion(self) -> None:
        """
        Resetea la ventana porque intervino un humano.

        Copiado de OpenHands: un mensaje del usuario dentro de la ventana hace
        que solo se miren los eventos posteriores. Hablar es progreso.

        NO resetean: una compactacion de contexto (si no, cada resumen borraria
        la evidencia del bucle), el paso del tiempo, ni que el agente diga que
        va a probar otra cosa.
        """
        self.intentos.clear()

    def anotar_corte(self) -> int:
        """Registra que el disyuntor disparo. Devuelve cuantas veces van."""
        self.cortes += 1
        return self.cortes

    def reiniciar_limpio(self) -> None:
        """
        Limpia la ventana porque SE TOMO la accion que el disyuntor exigia:
        tirar el trabajo acumulado y empezar de cero.

        Distinto de reset_por_intervencion(): aqui no hablo nadie, se ejecuto
        el modo raiz. El contador `cortes` NO se limpia a proposito, porque el
        segundo disparo sobre la misma tarea tiene que poder escalar.
        """
        self.intentos.clear()

    # ── salida para humanos ─────────────────────────────────────────────

    _EXPLICACION = {
        "D6":  "escribiste codigo {n} veces y el sintoma quedo IDENTICO",
        "D6b": "el sintoma volvio a uno que ya habias visto: estas dando vueltas",
        "D2":  "misma accion y mismo error {n} veces seguidas",
        "D1":  "limite de {n} intentos alcanzado sin resolver",
    }

    def diagnostico(self) -> str:
        motivo = self.motivo_corte()
        if not motivo:
            return "sin corte"
        plantilla = self._EXPLICACION.get(motivo, "corte")
        return f"{motivo}: " + plantilla.format(n=len(self._esteriles()))

    def orden_de_modo_raiz(self) -> str:
        """
        Lo que hay que hacer al disparar. Es una ORDEN, no un consejo.

        Deliberadamente NO dice 'piensa mejor' ni 'respira hondo': sin
        verificador externo eso empeora el resultado (Huang et al.). Dice que
        se dejen de escribir parches y se produzca una medicion.
        """
        escalar = self.anotar_corte() >= 2

        lineas = [
            "",
            "=" * 68,
            f"  DISYUNTOR DISPARADO — {self.diagnostico()}",
            f"  tarea: {self.tarea or '(sin nombre)'}",
            "=" * 68,
            "",
            "  PROHIBIDO seguir editando para arreglar esto.",
            "",
            "  MODO RAIZ, en este orden:",
            "   1. Revertir los parches acumulados. Volves al estado limpio.",
            "   2. Escribir la reproduccion minima: un comando que falle solo.",
            "   3. Enunciar la hipotesis de causa POR ESCRITO, antes de tocar codigo.",
            "   4. MEDIR el caso real en vez de ajustar la heuristica a ciegas.",
            "",
        ]

        if escalar:
            # Wink (arXiv:2602.17037, 42.807 trayectorias): recuperarse con UNA
            # intervencion sale 90,93%; con multiples, 79,07%. Para bucles,
            # 94,29% vs 73,78%. La segunda correccion sobre el mismo bucle vale
            # ~20 puntos menos. No insistir: escalar.
            lineas += [
                "  SEGUNDO DISPARO EN LA MISMA TAREA.",
                "  Reiniciar limpio otra vez rinde ~20 puntos menos que la primera vez.",
                "  Pedir ayuda o cambiar de enfoque, no reintentar.",
                "",
            ]

        lineas.append("=" * 68)
        return "\n".join(lineas)
