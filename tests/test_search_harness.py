# -*- coding: utf-8 -*-
"""El harness de búsqueda nuevo (cognia/search), 2026-08-14.

La métrica primaria de la pieza de fan-out está aquí y es binaria: con el
camino viejo (`workflows.paralelo`) un fallo se vuelve `None` y NO queda nada
que reconstruir — 0%. Con el envelope tiene que ser 100%, leído del archivo
persistido y no del objeto en memoria.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.search import contexto as CTX
from cognia.search import evidencia as EV
from cognia.search import fanout as FO


def _buscador_flaky(fallan: set):
    """Buscador falso que revienta en las consultas indicadas."""
    def _buscar(consulta, max_candidatos=8):
        if consulta in fallan:
            raise ConnectionError(f"rate limited: {consulta}")
        return [{"titulo": f"r{i}", "url": f"https://x/{consulta}/{i}",
                 "resumen": ""} for i in range(max_candidatos)]
    return _buscar


class TestElFalloNoSePierde:

    def test_el_viejo_paralelo_borra_la_causa(self):
        """El contrafactual, medido y no supuesto: así se ve hoy el agujero."""
        from cognia.agent.workflows import paralelo
        buscar = _buscador_flaky({"b"})
        salida = paralelo([lambda q=q: buscar(q) for q in ("a", "b", "c")])
        # 'b' falló y quedó None: indistinguible de "no hubo resultados".
        assert salida[1] is None
        assert not any(isinstance(x, dict) and x.get("error")
                       for x in salida if x is not None)

    def test_el_envelope_conserva_spec_y_causa(self):
        lote = FO.buscar_many(["a", "b", "c"],
                              buscador=_buscador_flaky({"b"}))
        assert len(lote.sobres) == 3
        assert [s.ok for s in lote.sobres] == [True, False, True]
        malo = lote.fallidos[0]
        assert malo.spec == "b"                    # QUÉ falló
        assert "rate limited" in malo.error        # POR QUÉ
        assert malo.tipo_error == "ConnectionError"

    def test_el_orden_es_el_de_entrada(self):
        # Con concurrencia, el orden de terminación no es el de entrada; si
        # se devolviera ese, cruzar resultado con consulta sería adivinar.
        lote = FO.buscar_many([f"q{i}" for i in range(12)], cap=5,
                              buscador=_buscador_flaky({"q3", "q7"}))
        assert [s.spec for s in lote.sobres] == [f"q{i}" for i in range(12)]

    def test_fraccion_reconstruible_desde_el_ARCHIVO(self, tmp_path):
        """La métrica primaria: 0% antes, 100% ahora."""
        lote = FO.buscar_many([f"q{i}" for i in range(20)], cap=5,
                              buscador=_buscador_flaky({"q2", "q5", "q11",
                                                        "q17"}))
        ruta = lote.volcar(tmp_path / "resultados.jsonl")
        m = FO.reconstruibles(ruta)
        assert m["total"] == 20 and m["fallidos"] == 4
        assert m["fraccion"] == 1.0

    def test_el_resumen_no_puede_mentir_el_conteo(self):
        lote = FO.buscar_many(["a", "b", "c", "d"],
                              buscador=_buscador_flaky({"b", "d"}))
        assert lote.resumen() == "2/4 ok, 2 fallidos (ConnectionError×2)"
        assert len(lote.valores) == 2      # valores() son SOLO los buenos

    def test_redespachar_solo_toca_los_fallidos(self):
        estado = {"falla": {"b"}}

        def _buscar(consulta, max_candidatos=8):
            if consulta in estado["falla"]:
                raise TimeoutError("lento")
            return [{"url": f"https://x/{consulta}"}]

        lote = FO.en_paralelo(["a", "b", "c"], lambda q: _buscar(q))
        assert len(lote.fallidos) == 1
        estado["falla"] = set()            # la red se recupera
        recuperado = FO.redespachar(lote, lambda q: _buscar(q))
        assert [s.ok for s in recuperado.sobres] == [True, True, True]
        assert recuperado.sobres[1].tipo_error == "recuperado_en_reintento"


class TestPresupuestoEnSegundos:

    def test_el_modo_se_elige_por_pared_no_por_tokens(self):
        # 20 s no alcanzan para ANCHO por mucho que la ventana sea de 1M.
        assert CTX.modo_para(20, tok_s=900).nombre == "estrecho"
        assert CTX.modo_para(60, tok_s=900).nombre == "medio"
        assert CTX.modo_para(600, tok_s=900).nombre == "ancho"

    def test_el_coste_esta_declarado_antes_de_pagarlo(self):
        seg = CTX.segundos_de(CTX.ANCHO, tok_s=900)
        assert 150 < seg < 210      # ~178 s con los tok/s medidos

    def test_el_recorte_deja_cicatriz(self):
        largo = "x" * 200_000
        salida = CTX.repartir([{"url": "u", "texto": largo}], CTX.ESTRECHO)
        assert "chars elididos" in salida[0]["texto"]
        assert len(salida[0]["texto"]) < len(largo)

    def test_lo_que_cabe_entero_no_se_toca(self):
        corto = "y" * 500
        salida = CTX.repartir([{"url": "u", "texto": corto}], CTX.ANCHO)
        assert salida[0]["texto"] == corto

    def test_ancho_no_lee_mas_paginas_de_las_que_declara(self):
        paginas = [{"url": f"u{i}", "texto": "z" * 1000} for i in range(80)]
        assert len(CTX.repartir(paginas, CTX.ANCHO)) == CTX.ANCHO.paginas
        assert len(CTX.repartir(paginas, CTX.ESTRECHO)) == 3


class TestCitaLiteral:

    FUENTE = ("La API cobra 0,0025 dólares por invocación de web_search.\n"
              "El SDK exige Python 3.12 o superior para instalarse.")

    def test_una_cita_real_pasa(self):
        v = EV.verificar_cita("cobra 0,0025 dólares por invocación",
                              self.FUENTE)
        assert v["ok"]

    def test_una_cita_inventada_reprueba(self):
        v = EV.verificar_cita("cobra 0,0050 dólares por invocación",
                              self.FUENTE)
        assert not v["ok"] and "no está en la fuente" in v["razon"]

    def test_las_comillas_tipograficas_no_reprueban_una_cita_buena(self):
        # El modelo re-teclea “ ” ’ como ASCII: sin NFKC esto sería un falso
        # positivo de fabricación, o sea acusar al modelo de mentir por un
        # carácter invisible.
        v = EV.verificar_cita('exige Python 3.12 o superior',
                              self.FUENTE.replace("3.12", "3.12"))
        assert v["ok"]

    def test_la_elision_marcada_se_acepta_trozo_a_trozo(self):
        v = EV.verificar_cita("La API cobra 0,0025 dólares [...] "
                              "El SDK exige Python 3.12", self.FUENTE)
        assert v["ok"] and v["trozos"] == 2

    def test_pegar_dos_fuentes_distintas_no_pasa(self):
        v = EV.verificar_cita("La API cobra 0,0025 dólares [...] "
                              "y corre en Windows 95", self.FUENTE)
        assert not v["ok"]

    def test_una_cita_minuscula_no_cuenta_como_verificada(self):
        # "La API" está literal, pero no identifica nada: un verde vacío es
        # peor que un rojo.
        v = EV.verificar_cita("La API", self.FUENTE)
        assert not v["ok"] and "no identifica nada" in v["razon"]

    def test_la_tasa_separa_fabricado_de_no_descargado(self):
        regs = [
            {"evidencia": "cobra 0,0025 dólares por invocación",
             "source_url": "u1"},
            {"evidencia": "cobra 9,9999 dólares por invocación",
             "source_url": "u1"},
            {"evidencia": "lo que sea, la página no bajó", "source_url": "u2"},
        ]
        r = EV.verificar_registros(regs, {"u1": self.FUENTE})
        assert len(r["verificados"]) == 1
        assert len(r["fabricados"]) == 1
        assert len(r["sin_fuente"]) == 1
        # 1 de 2 JUZGABLES, no 1 de 3: la página caída no es culpa del modelo.
        assert r["tasa_fabricacion"] == 0.5
