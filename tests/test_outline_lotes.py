"""
tests/test_outline_lotes.py
===========================
Regresiones del outline por LOTES y de la cabeza que teje
(node/llama_backend.py: _items_enumerados, _parse_outline, _outline_validado,
_plan_outline, _cabeza_tejida, generate_delegated).

Los tres fallos MEDIDOS que cubren, todos MUDOS antes del fix (2026-08-17):
  1. La lista entera en UNA linea: el parseo por lineas la tomaba como un solo
     item y lo entregaba RECORTADO a 120 chars como titulo de la seccion 1. Un
     worker recibio ese titulo y escribio el documento entero.
  2. El outline corto: n=144 devolvia 55 items en 1 de 2 corridas -> ~77k
     tokens en vez de 200k, sin una linea de aviso.
  3. La cabeza reventaba pasadas ~151 secciones (HTTP 400, generate()->None,
     head = ... or "" se lo tragaba) -> documento sin introduccion, en silencio.

No usan modelo: impls falsos con guiones. La verificacion contra el :8080 vivo
esta en scripts/sondear_outline_lotes.py y scripts/sondear_cabeza_grande.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from node.llama_backend import LlamaBackend


# --------------------------------------------------------------------------
# Impls falsos
# --------------------------------------------------------------------------

class _ImplGuion:
    """Impl con guion: cada generate() saca el siguiente texto de la lista.

    n_ctx alimenta /props (el presupuesto de la cabeza se mide contra el server
    real, no contra la env). tokens_por_char emula /tokenize.
    """

    def __init__(self, textos, n_ctx: int = 16384, tokens_por_char: float = 1 / 4.21):
        self._textos = list(textos)
        self._n_ctx = n_ctx
        self._tpc = tokens_por_char
        self.prompts: list = []
        self.last_tokens_predicted: Optional[int] = None
        self.last_stop_reason: Optional[str] = None

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        self.prompts.append((prompt, max_tokens))
        if not self._textos:
            return None
        texto = self._textos.pop(0)
        if texto is None:
            self.last_tokens_predicted = None
            self.last_stop_reason = "error"
            return None
        self.last_tokens_predicted = max(1, len(texto) // 4)
        self.last_stop_reason = "eos"
        return texto

    def props(self):
        return {"default_generation_settings": {"n_ctx": self._n_ctx},
                "model_path": "falso.gguf"}

    def tokenize_len(self, texto: str) -> int:
        return int(len(texto or "") * self._tpc)


class _ImplServerCorto(_ImplGuion):
    """Server que devuelve None (HTTP 400) cuando el prompt pasa de tope tokens.

    Es el comportamiento REAL medido: por encima de ~151 secciones el prompt de
    la cabeza no entraba en 16.384 y el server contestaba 400.
    """

    def __init__(self, textos, n_ctx=16384, tope_tokens=12288, **kw):
        super().__init__(textos, n_ctx=n_ctx, **kw)
        self.tope = tope_tokens
        self.rechazos = 0

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        if self.tokenize_len(prompt) > self.tope:
            self.rechazos += 1
            self.prompts.append((prompt, max_tokens))
            self.last_tokens_predicted = None
            self.last_stop_reason = "error"
            return None
        return super().generate(prompt, max_tokens, temperature, **kw)


def _outline(n: int, prefijo: str = "Seccion") -> str:
    return "\n".join(f"{i + 1}. {prefijo} {i + 1}" for i in range(n))


# --------------------------------------------------------------------------
# 1. La lista entera en UNA linea
# --------------------------------------------------------------------------

# La cadena EXACTA del informe del 2026-08-17: el 14B devolvio la lista inline y
# ADEMAS la repitio bien debajo. Con >=2 lineas numeradas el reparto inline no
# se disparaba y el item 1 salia recortado a 120 chars.
_UNA_LINEA = ("1. Diseño Arquitectónico 2. Implementación de Software "
              "3. Configuración de la GPU 4. Entrenamiento de Modelos "
              "5. Operación y Mantenimiento")
_MIXTO = (_UNA_LINEA + "\n\n1. Diseño Arquitectónico\n"
          "2. Implementación de Software\n3. Configuración de la GPU\n"
          "4. Entrenamiento de Modelos\n5. Operación y Mantenimiento\n")

# Lo que el worker recibio como titulo (120 chars, cortado a mitad de palabra).
_TITULO_ENVENENADO = ("Diseño Arquitectónico 2. Implementación de Software "
                      "3. Configuración de la GPU 4. Entrenamiento de Modelos "
                      "5. Operación ")


class TestListaEnUnaLinea:
    def test_el_titulo_envenenado_ya_no_sale_del_parseo(self):
        """El caso exacto medido: ningun item lleva la lista entera dentro."""
        items = LlamaBackend._parse_outline(_MIXTO, 6)
        assert _TITULO_ENVENENADO not in items
        assert all(" 2. " not in it for it in items), items
        assert items == ["Diseño Arquitectónico", "Implementación de Software",
                         "Configuración de la GPU", "Entrenamiento de Modelos",
                         "Operación y Mantenimiento"]

    def test_el_titulo_envenenado_tenia_exactamente_120_chars(self):
        """Ancla del bug: el recorte a 120 chars es lo que lo hacia pasar por titulo."""
        assert len(_TITULO_ENVENENADO) == 120

    def test_lista_inline_sin_repeticion_tambien_se_parte(self):
        items = LlamaBackend._parse_outline(_UNA_LINEA, 6)
        assert len(items) == 5
        assert items[0] == "Diseño Arquitectónico"

    def test_numeros_sueltos_en_un_titulo_no_parten_el_item(self):
        """La cadena solo acepta el numero SIGUIENTE: 'RFC 5. algo' no es item."""
        texto = "1. Relojes de Lamport y RFC 3339\n2. Vector clocks\n3. Snapshot"
        assert LlamaBackend._parse_outline(texto, 3) == [
            "Relojes de Lamport y RFC 3339", "Vector clocks", "Snapshot"]

    def test_el_worker_no_recibe_un_titulo_con_la_lista_entera(self):
        """End to end: con el outline envenenado, generate_delegated NO corre
        workers con ese titulo. O reintenta y sale limpio, o devuelve None."""
        impl = _ImplGuion([_MIXTO, _MIXTO, _MIXTO])
        be = LlamaBackend(impl)
        avisos = []
        res = be.generate_delegated("tema X", target_tokens=600, n_tasks=6,
                                    on_aviso=lambda t, m: avisos.append((t, m)))
        assert res is None
        assert avisos and avisos[0][0] == "outline"
        assert "pedi 6, parsee 5" in avisos[0][1]
        # Y sobre todo: ningun prompt de worker llevo el titulo envenenado.
        assert all(_TITULO_ENVENENADO not in p for (p, _mt) in impl.prompts)


# --------------------------------------------------------------------------
# 2. El outline corto: se CUENTA antes de gastar la GPU
# --------------------------------------------------------------------------

class TestOutlineValidado:
    def test_reintenta_hasta_que_cuadra_el_numero(self):
        impl = _ImplGuion([_outline(9), _outline(24)])
        be = LlamaBackend(impl)
        items, err = be._outline_validado("tema", 24, 0.4)
        assert err is None and len(items) == 24

    def test_devuelve_los_dos_numeros_cuando_no_cuadra(self):
        """El fallo mudo se vuelve una frase con las dos cifras."""
        impl = _ImplGuion([_outline(55), _outline(55), _outline(55)])
        be = LlamaBackend(impl)
        items, err = be._outline_validado("tema", 144, 0.4)
        assert err == "esquema incompleto: pedi 144, parsee 55"
        assert len(items) == 55

    def test_backend_mudo_se_reporta_como_tal(self):
        impl = _ImplGuion([None, None, None])
        be = LlamaBackend(impl)
        items, err = be._outline_validado("tema", 24, 0.4)
        assert items == []
        assert "sin respuesta del backend" in err and "3 de 3" in err

    def test_delegated_no_gasta_la_gpu_con_un_plan_corto(self):
        """55 de 144 = ~77k tokens de los 200k pedidos: se corta ANTES.

        144 con lote 24 pide un indice de 6 capitulos; el modelo devuelve 3."""
        impl = _ImplGuion([_outline(3)] * 3)     # el indice de capitulos sale mal
        be = LlamaBackend(impl)
        avisos = []
        res = be.generate_delegated("tema", target_tokens=200000, n_tasks=144,
                                    on_aviso=lambda t, m: avisos.append((t, m)))
        assert res is None
        assert avisos and avisos[0][0] == "outline"
        assert avisos[0][1] == ("indice de capitulos: esquema incompleto: "
                                "pedi 6, parsee 3")
        # 3 intentos del indice y NI UN worker.
        assert len(impl.prompts) == 3


# El outline REAL que el gate dio por bueno el 2026-08-18: 24 items, 24 strings
# distintos, conteo 24/24... y del 12 al 23 el modelo en bucle. El documento salio
# con 11 secciones sobre "Modelos de Consistencia de Sesgo Parcial Parcial ...".
_OUTLINE_EN_BUCLE = [
    "Introducción a la Ingeniería de Sistemas Distribuidos",
    "Definición y Características de Sistemas Distribuidos",
    "Tipos de Sistemas Distribuidos",
    "Modelos de Arquitectura de Sistemas Distribuidos",
    "Comunicación en Sistemas Distribuidos",
    "Protocolos de Comunicación",
    "Modelos de Sincronización",
    "Consistencia en Sistemas Distribuidos",
    "Tipos de Consistencia",
    "Modelos de Consistencia Causal",
    "Modelos de Consistencia de Causalidad Total",
    "Modelos de Consistencia de Sesgo",
    "Modelos de Consistencia de Sesgo Total",
    "Modelos de Consistencia de Sesgo Parcial",
    "Modelos de Consistencia de Sesgo Parcial Total",
    "Modelos de Consistencia de Sesgo Parcial Parcial",
    "Modelos de Consistencia de Sesgo Parcial Parcial Total",
    "Modelos de Consistencia de Sesgo Parcial Parcial Parcial",
    "Modelos de Consistencia de Sesgo Parcial Parcial Parcial Total",
    "Modelos de Consistencia de Sesgo Parcial Parcial Parcial Parcial",
    "Modelos de Consistencia de Sesgo Parcial Parcial Parcial Parcial Total",
    "Modelos de Consistencia de Sesgo Parcial Parcial Parcial Parcial Parcial",
    "Modelos de Consistencia de Sesgo Parcial Parcial Parcial Parcial Parcial Total",
    "Aplicaciones Prácticas de Modelos de Consistencia",
]

# Uno de los 9 outlines SANOS medidos el mismo dia contra el mismo server: el
# detector no puede reprobar esto.
_OUTLINE_SANO = [
    "Introducción a la Ingeniería de Sistemas Distribuidos",
    "Definición y Características de Sistemas Distribuidos",
    "Modelos de Consistencia",
    "Relojes Lógicos y Sincronización",
    "Consenso Distribuido: Paxos",
    "Consenso Distribuido: Raft",
    "Replicación de Datos",
    "Particionado y Sharding",
    "Tolerancia a Fallos",
    "Colas de Mensajes",
    "Almacenamiento Distribuido",
    "Observabilidad y Trazas",
]


class TestOutlineDegenerado:
    """El CONTEO da 24/24 y aun asi el esquema es un bucle (medido 2026-08-18)."""

    def test_mide_la_familia_del_outline_real_en_bucle(self):
        familia, base = LlamaBackend._familia_repetida(_OUTLINE_EN_BUCLE)
        assert familia == 12          # la base + 11 variantes
        assert base == "Modelos de Consistencia de Sesgo"

    def test_un_outline_sano_tiene_familia_1(self):
        familia, _base = LlamaBackend._familia_repetida(_OUTLINE_SANO)
        assert familia == 1

    def test_se_reintenta_el_lote_y_se_acepta_el_sano(self):
        """El bucle cuesta un reintento de segundos, no 11 secciones de basura."""
        bucle = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(_OUTLINE_EN_BUCLE))
        sano = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(
            _OUTLINE_SANO + [f"Extra {i}" for i in range(12)]))
        impl = _ImplGuion([bucle, sano])
        be = LlamaBackend(impl)
        items, err = be._outline_validado("tema", 24, 0.4)
        assert err is None
        assert items[10] == "Almacenamiento Distribuido"
        assert len(impl.prompts) == 2

    def test_si_insiste_el_bucle_se_reporta_con_los_numeros(self):
        bucle = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(_OUTLINE_EN_BUCLE))
        impl = _ImplGuion([bucle] * 3)
        be = LlamaBackend(impl)
        items, err = be._outline_validado("tema", 24, 0.4)
        assert len(items) == 24                 # los items existen: no se pierden
        assert err.startswith("esquema degenerado: 12 de 24 titulos son variantes")
        assert "Modelos de Consistencia de Sesgo" in err

    def test_delegated_no_escribe_200k_con_un_esquema_en_bucle(self):
        bucle = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(_OUTLINE_EN_BUCLE))
        impl = _ImplGuion([bucle] * 3)
        be = LlamaBackend(impl)
        avisos = []
        res = be.generate_delegated("tema", target_tokens=30000, n_tasks=24,
                                    on_aviso=lambda t, m: avisos.append((t, m)))
        assert res is None
        assert avisos[0][0] == "outline"
        assert "degenerado" in avisos[0][1]
        assert len(impl.prompts) == 3           # 3 outlines y NI UN worker


class TestPlanOutlinePorLotes:
    def test_n_chico_va_en_un_nivel(self):
        impl = _ImplGuion([_outline(24)])
        be = LlamaBackend(impl)
        tasks, bloques, meta = be._plan_outline("tema", 24, 0.4)
        assert len(tasks) == 24 and meta["niveles"] == 1 and meta["error"] is None
        assert len(bloques) == 24

    def test_n_grande_va_en_dos_niveles_y_da_el_numero_exacto(self):
        # 144 con lote 24 = 6 capitulos de 24: 1 indice + 6 lotes = 7 llamadas.
        impl = _ImplGuion([_outline(6)] + [_outline(24)] * 6)
        be = LlamaBackend(impl)
        tasks, bloques, meta = be._plan_outline("tema", 144, 0.4)
        assert len(tasks) == 144, len(tasks)
        assert meta["niveles"] == 2 and meta["lote"] == 24
        assert len(meta["capitulos"]) == 6
        assert meta["error"] is None
        assert len(impl.prompts) == 7

    def test_ninguna_llamada_pide_mas_de_un_lote(self):
        """La razon de ser del troceo: cada llamada se queda en el rango medido
        fiable (<=24). Si alguna pidiera 144, el fallo volveria."""
        impl = _ImplGuion([_outline(6)] + [_outline(24)] * 6)
        be = LlamaBackend(impl)
        be._plan_outline("tema", 144, 0.4)
        for (p, _mt) in impl.prompts:
            assert "exactamente 144" not in p, p[:200]

    def test_reparto_no_pierde_ni_inventa_secciones(self):
        assert LlamaBackend._reparto(144, 6) == [24] * 6
        assert sum(LlamaBackend._reparto(100, 5)) == 100
        assert LlamaBackend._reparto(100, 5) == [20] * 5
        assert sum(LlamaBackend._reparto(37, 2)) == 37
        assert LlamaBackend._reparto(37, 2) == [19, 18]

    def test_el_worker_ve_su_seccion_con_el_numero_GLOBAL(self):
        """El bloque del capitulo 2 numera desde 25, no desde 1: el numero que se
        le pide escribir tiene que ser el mismo que ve en el esquema."""
        impl = _ImplGuion([_outline(6)] + [_outline(24)] * 6)
        be = LlamaBackend(impl)
        tasks, bloques, meta = be._plan_outline("tema", 144, 0.4)
        secciones = bloques[24].split("Secciones del capitulo")[1]
        assert secciones.strip().splitlines()[1].startswith("25. ")
        assert "\n1. " not in secciones      # nada renumerado desde 1
        assert secciones.strip().splitlines()[-1].startswith("48. ")

    def test_un_capitulo_que_falla_corta_con_su_numero(self):
        impl = _ImplGuion([_outline(6), _outline(24), _outline(24),
                           _outline(9), _outline(9), _outline(9)])
        be = LlamaBackend(impl)
        tasks, bloques, meta = be._plan_outline("tema", 144, 0.4)
        assert meta["error"].startswith("capitulo 3/6")
        assert "pedi 24, parsee 9" in meta["error"]


# --------------------------------------------------------------------------
# 3. La cabeza: encoge, trocea, y si falla lo DICE
# --------------------------------------------------------------------------

def _drafts(n: int, chars: int = 3000) -> list:
    return [(f"Seccion {i + 1}", "palabra " * (chars // 8)) for i in range(n)]


class TestCabezaTejida:
    def test_encoge_el_extracto_hasta_que_entra(self):
        """El caso que reventaba: 160 secciones x 400 chars no entran en 16k."""
        impl = _ImplServerCorto(["Introduccion tejida."], n_ctx=16384)
        be = LlamaBackend(impl)
        txt, meta = be._cabeza_tejida("tema", _drafts(160), 0.4)
        assert txt == "Introduccion tejida."
        assert meta["error"] is None
        assert meta["extracto_chars"] < 400, meta
        assert meta["prompt_tokens"] <= meta["presupuesto"]
        assert impl.rechazos == 0     # no se le manda al server nada que no entre

    def test_a_144_secciones_ya_no_va_al_limite(self):
        impl = _ImplServerCorto(["Intro."], n_ctx=16384)
        be = LlamaBackend(impl)
        txt, meta = be._cabeza_tejida("tema", _drafts(144), 0.4)
        assert txt and meta["error"] is None
        assert meta["prompt_tokens"] <= meta["presupuesto"]

    def test_trocea_cuando_ni_los_titulos_pelados_entran(self):
        """Titulos solos de 2.000 secciones > presupuesto -> cabeza en 2 niveles."""

        class _ImplDosNiveles(_ImplServerCorto):
            """Distingue la sintesis de bloque de la cabeza FINAL: la final es la
            unica cuyo prompt trae los 'Bloque N' ya sintetizados."""

            def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
                if self.tokenize_len(prompt) > self.tope:
                    self.rechazos += 1
                    return None
                self.prompts.append((prompt, max_tokens))
                self.last_tokens_predicted = 10
                self.last_stop_reason = "eos"
                return "Intro final." if "1. Bloque 1:" in prompt else "sintesis"

        impl = _ImplDosNiveles([], n_ctx=16384)
        be = LlamaBackend(impl)
        drafts = [(f"Titulo largo de la seccion numero {i + 1} sobre sistemas "
                   f"distribuidos y consenso", "x" * 100) for i in range(2000)]
        txt, meta = be._cabeza_tejida("tema", drafts, 0.4)
        assert meta["bloques"] > 1, meta
        assert meta["error"] is None
        assert txt == "Intro final."

    def test_si_la_cabeza_no_responde_lo_dice_con_los_numeros(self):
        """Nunca mas un documento sin introduccion en silencio."""
        impl = _ImplGuion([None], n_ctx=16384)
        be = LlamaBackend(impl)
        txt, meta = be._cabeza_tejida("tema", _drafts(10), 0.4)
        assert txt == ""
        assert "no respondio" in meta["error"]
        assert "documento sin introduccion" in meta["error"]

    def test_ctx_ridiculo_no_revienta_avisa(self):
        impl = _ImplGuion(["x"], n_ctx=128)
        be = LlamaBackend(impl)
        txt, meta = be._cabeza_tejida("tema", _drafts(10), 0.4)
        assert txt == "" and "no da ni para la cabeza" in meta["error"]

    def test_delegated_propaga_el_fallo_de_cabeza_y_conserva_el_cuerpo(self):
        """El cuerpo NO se tira: el aviso sale por head_error y por on_aviso."""
        impl = _ImplGuion([_outline(3), "cuerpo 1", "cuerpo 2", "cuerpo 3", None],
                          n_ctx=16384)
        be = LlamaBackend(impl)
        avisos = []
        res = be.generate_delegated("tema", target_tokens=900, n_tasks=3,
                                    on_aviso=lambda t, m: avisos.append((t, m)))
        assert res is not None
        assert res["sections"] == 3
        assert res["head"] == ""
        assert "documento sin introduccion" in res["head_error"]
        assert [t for (t, _m) in avisos] == ["cabeza"]
        assert "cuerpo 2" in res["text"]
