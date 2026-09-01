# -*- coding: utf-8 -*-
"""contrato_tarea.py -- el ENCARGO, vivo, mientras dura la tarea.

QUE RESUELVE
    El bucle no tenia ninguna representacion del objetivo. "La tarea termino"
    era literalmente "el modelo no pidio herramientas en este turno"
    (loop.py, rama de fin natural): un turno de prosa cerraba con exito una
    tarea de cuarenta pasos y diez sistemas pedidos, de los cuales podia haber
    hecho dos. El agente confundia RESPONDER con TERMINAR porque nadie le
    guardaba la lista de lo pedido.

    Este modulo guarda esa lista. Saca del enunciado los requisitos que el
    usuario enumero, sigue cual de ellos tiene rastro en lo que se produjo, y
    da el texto que se le devuelve al modelo cuando intenta cerrar con
    requisitos sin tocar.

QUE **NO** ES
    No es un verificador. La cobertura que calcula es un proxy lexico y se
    declara como tal: dice "de este requisito no hay ni rastro en lo que
    escribiste", que es una afirmacion barata y casi siempre cierta, y NO dice
    "esto funciona". Por eso solo gobierna una decision: si se puede CERRAR.
    Nunca marca una tarea como exitosa; para eso estan la parada verificada
    (que exige haber ejecutado algo) y las pruebas de verdad.

    La asimetria es deliberada. Un falso "esta cubierto" solo devuelve el
    comportamiento de hoy (cerrar); un falso "falta" cuesta un turno mas. El
    error barato es el que se elige.

POR QUE ES GENERAL Y NO UN PARCHE
    No conoce ningun dominio: no sabe que es un juego, ni una API, ni una
    pagina. Solo sabe leer una lista numerada o con vinnetas -- que es como
    los humanos escriben un encargo largo en cualquier campo -- y buscar sus
    palabras en lo producido. Una tarea de una linea saca un requisito y el
    comportamiento es el de siempre.
"""
from __future__ import annotations

import os
import re
import unicodedata

# Un encargo con mas de esto no cabe en un nudge util; ademas, mas alla de
# ~24 puntos la lista deja de guiar y empieza a ser ruido en el prompt.
TOPE_REQUISITOS = 24
MIN_CHARS_REQUISITO = 22
UMBRAL_COBERTURA = 0.55

_VACIAS = {
    "para", "como", "con", "sin", "que", "los", "las", "del", "una", "uno",
    "por", "sus", "este", "esta", "estos", "estas", "debe", "deben", "tiene",
    "tienen", "hay", "muy", "mas", "menos", "cada", "todo", "toda", "todos",
    "todas", "cuando", "donde", "sobre", "entre", "desde", "hasta", "pero",
    "porque", "aunque", "segun", "ademas", "tambien", "solo", "propio",
    "propia", "propios", "propias", "the", "and", "for", "with", "your",
    "debera", "deberas", "puede", "pueden", "sea", "ser", "esta", "estar",
    "hacer", "haz", "usa", "usar", "poner", "pon", "dar", "del", "por",
}

_NUMERADA = re.compile(r"^\s{0,6}(\d{1,2})\s*[.)\-:]\s+(.{%d,})$" % MIN_CHARS_REQUISITO)
_VINNETA = re.compile(r"^\s{0,6}[-*•–]\s+(.{%d,})$" % MIN_CHARS_REQUISITO)
_CABECERA = re.compile(
    r"^\s{0,6}(contrato|nota|aviso|importante|no entregues|entregalo|"
    r"requisitos?|sistemas?)\b", re.I)


def _sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _palabras(texto):
    """Palabras de contenido, sin tildes, en minusculas."""
    bruto = re.findall(r"[a-zA-ZÀ-ſ_][\wÀ-ſ]{2,}",
                       _sin_tildes(texto or "").lower())
    return [p for p in bruto if len(p) > 3 and p not in _VACIAS]


def derivar(texto, tope=TOPE_REQUISITOS):
    """Los requisitos que el enunciado enumera. Lista de strings, en orden.

    Prioriza la estructura que puso el usuario (numeracion o vinnetas) porque
    es la unica senal fiable de "aqui hay N cosas distintas". Solo si no hay
    estructura ninguna cae a partir por frases, y ahi es conservador: un
    encargo corto no debe inventarse requisitos.
    """
    texto = texto or ""
    lineas = texto.splitlines()
    reqs, vistos = [], set()

    def _mete(s):
        s = re.sub(r"\s+", " ", (s or "").strip()).strip(" .;:-")
        if len(s) < MIN_CHARS_REQUISITO:
            return
        clave = " ".join(sorted(set(_palabras(s))))[:120]
        if not clave or clave in vistos:
            return
        vistos.add(clave)
        reqs.append(s[:300])

    for ln in lineas:
        if _CABECERA.match(ln):
            continue
        m = _NUMERADA.match(ln)
        if m:
            _mete(m.group(2))
            continue
        m = _VINNETA.match(ln)
        if m:
            _mete(m.group(1))

    if len(reqs) < 2:
        # Sin lista: frases con obligacion. Tope bajo a proposito -- de un
        # encargo de dos frases no salen ocho requisitos.
        reqs, vistos = [], set()
        for frase in re.split(r"(?<=[.;\n])\s+", texto):
            f = frase.strip()
            if len(f) < 30:
                continue
            if re.search(r"\b(debe|tiene que|incluye|implementa|crea|construye|"
                         r"anade|añade|genera|escribe|entrega|expon|permite|"
                         r"soporta|guarda)\b", _sin_tildes(f).lower()):
                _mete(f)
            if len(reqs) >= 12:
                break
    return reqs[:tope]


def cobertura(requisito, evidencia_palabras):
    """Fraccion de palabras de contenido del requisito presentes en la evidencia."""
    ps = set(_palabras(requisito))
    if not ps:
        return 1.0
    return len(ps & evidencia_palabras) / float(len(ps))


class Contrato:
    """La lista de lo pedido y su rastro en lo producido."""

    def __init__(self, texto_tarea, umbral=UMBRAL_COBERTURA, tope=TOPE_REQUISITOS):
        self.texto = texto_tarea or ""
        self.umbral = float(umbral)
        self.requisitos = [
            {"id": i + 1, "texto": t, "cobertura": 0.0, "cubierto": False}
            for i, t in enumerate(derivar(self.texto, tope))
        ]
        self.nudges = 0
        self.ultima_evidencia_chars = 0

    def __len__(self):
        return len(self.requisitos)

    @property
    def activo(self):
        """Con menos de 3 requisitos el contrato no aporta nada: el
        comportamiento de siempre ya es correcto para una tarea corta."""
        return len(self.requisitos) >= 3

    def actualizar(self, evidencia_texto):
        pal = set(_palabras(evidencia_texto))
        self.ultima_evidencia_chars = len(evidencia_texto or "")
        for r in self.requisitos:
            c = cobertura(r["texto"], pal)
            r["cobertura"] = round(c, 3)
            # monotono: lo que estuvo cubierto no se descubre solo porque un
            # recorte de evidencia deje de verlo.
            r["cubierto"] = bool(r["cubierto"] or c >= self.umbral)
        return self

    def pendientes(self):
        return [r for r in self.requisitos if not r["cubierto"]]

    def cubiertos(self):
        return [r for r in self.requisitos if r["cubierto"]]

    def tope_nudges(self):
        """Cuantas veces se puede retener un cierre. Escala con lo que falta:
        retener una vez una tarea de 12 requisitos no sirve de nada."""
        return max(2, min(6, len(self.pendientes())))

    def puede_insistir(self):
        return self.activo and self.pendientes() and self.nudges < self.tope_nudges()

    def bloque_para_modelo(self, tope=8):
        """El texto que se le devuelve al modelo en vez de dejarle cerrar."""
        faltan = self.pendientes()
        self.nudges += 1
        lista = "\n".join("  %d. %s" % (r["id"], r["texto"][:220])
                          for r in faltan[:tope])
        extra = ("\n  ... y %d mas" % (len(faltan) - tope)) if len(faltan) > tope else ""
        hechos = len(self.cubiertos())
        return (
            "ALTO: todavia no has terminado. De los %d requisitos del encargo hay "
            "rastro de %d en lo que has producido, y de estos NO:\n%s%s\n\n"
            "No respondas todavia con un resumen. Para cada punto de esa lista, o bien "
            "lo implementas ahora (con las herramientas, escribiendo el codigo que falta), "
            "o bien dices en una linea por que es imposible o ya esta hecho y donde. "
            "Trabaja: no vale describir lo que harias."
            % (len(self.requisitos), hechos, lista, extra)
        )

    def informe(self):
        return {
            "requisitos": len(self.requisitos),
            "cubiertos": len(self.cubiertos()),
            "pendientes": [r["texto"][:120] for r in self.pendientes()][:12],
            "nudges": self.nudges,
            "cobertura_media": round(
                sum(r["cobertura"] for r in self.requisitos) / len(self.requisitos), 3)
            if self.requisitos else 0.0,
        }


# -- evidencia: lo que hay en disco y lo que devolvieron las tools ------------

_EXT_EVIDENCIA = {".py", ".js", ".mjs", ".ts", ".jsx", ".html", ".htm", ".css",
                  ".json", ".md", ".txt", ".lua", ".java", ".cs", ".c", ".cpp",
                  ".h", ".go", ".rs", ".rb", ".php", ".sh", ".sql", ".yml",
                  ".yaml", ".toml", ".glsl", ".vert", ".frag"}
_FUERA = {"__pycache__", ".git", "node_modules", ".pytest_cache", "venv",
          ".venv", "dist", "build", ".cognia"}


def evidencia_de_disco(raiz, desde_ts=None, tope_total=400000, tope_fichero=60000):
    """Concatena lo escrito bajo `raiz` (opcionalmente solo lo tocado despues
    de `desde_ts`). Es la evidencia INDEPENDIENTE del registro de mutaciones:
    da igual que tool lo escribiera, o si lo escribio un sub-agente."""
    trozos = []
    total = 0
    try:
        for base, dirs, ficheros in os.walk(str(raiz)):
            dirs[:] = [d for d in dirs if d not in _FUERA]
            for f in ficheros:
                ruta = os.path.join(base, f)
                ext = os.path.splitext(f)[1].lower()
                if ext not in _EXT_EVIDENCIA:
                    continue
                try:
                    st = os.stat(ruta)
                    if desde_ts and st.st_mtime < desde_ts - 1:
                        continue
                    if st.st_size > 4 * tope_fichero:
                        continue
                    with open(ruta, "r", encoding="utf-8", errors="replace") as fh:
                        datos = fh.read(tope_fichero)
                except Exception:
                    continue
                trozos.append(os.path.relpath(ruta, str(raiz)))
                trozos.append(datos)
                total += len(datos)
                if total >= tope_total:
                    return "\n".join(trozos)
    except Exception:
        pass
    return "\n".join(trozos)
