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


class TestCapDeSalidaEscalaConLaVentana:
    """El cap de tool-output (1800 chars) se midió con un 3B y ctx 16k y se
    quedó fijo mientras el cerebro pasaba a 1M. A esa ventana, recortar la
    salida de un comando a 1800 chars tira el stack trace del medio."""

    def test_a_la_ventana_donde_se_midio_no_cambia_nada(self):
        from cognia.agent.tools import aci_cap_para
        assert aci_cap_para(16384) == 1800          # el valor histórico

    def test_una_ventana_chica_no_baja_del_historico(self):
        from cognia.agent.tools import aci_cap_para
        assert aci_cap_para(4096) == 1800
        assert aci_cap_para(0) == 1800              # sin backend conocido

    def test_con_un_millon_de_ventana_cabe_el_stack_entero(self):
        from cognia.agent.tools import aci_cap_para
        cap = aci_cap_para(1_048_576)
        assert cap == 24_000                        # el techo, no infinito

    def test_el_env_gana_siempre(self, monkeypatch):
        from cognia.agent.tools import aci_cap_para
        monkeypatch.setenv("COGNIA_ACI_CAP", "500")
        assert aci_cap_para(1_048_576) == 500

    def test_el_recorte_conserva_cabeza_y_cola_del_error(self):
        from cognia.agent.tools import aci_trim
        texto = "RESULTADO ok\n" + ("x" * 50_000) + "\nTraceback: boom"
        salida = aci_trim(texto, "run", cap=4000)
        assert salida.startswith("RESULTADO ok")
        assert salida.endswith("Traceback: boom")
        assert "chars omitidos" in salida
        assert len(salida) < 4600      # cap + el marcador


class TestPrefiltroDeterminista:
    """La guarda que importa: un prefiltro que ahorra mucho y baja el recall
    está reprobado, aunque la lista quede más limpia."""

    def test_la_misma_pagina_con_utm_es_la_misma_pagina(self):
        from cognia.search.prefiltro import canonicalizar
        a = canonicalizar("https://www.Ejemplo.org/guia/?utm_source=x&id=42#top")
        b = canonicalizar("http://ejemplo.org/guia?id=42")
        assert a == b

    def test_no_colapsa_paginas_DISTINTAS_por_limpiar_de_mas(self):
        # ?id=42 ES el documento en medio internet: si se limpiara, dos
        # páginas distintas se volverían una y se perdería contenido bueno.
        from cognia.search.prefiltro import canonicalizar
        assert (canonicalizar("https://e.org/ver?id=42")
                != canonicalizar("https://e.org/ver?id=43"))

    def test_tope_por_dominio(self):
        from cognia.search.prefiltro import prefiltrar
        cands = [{"url": f"https://mismositio.com/p{i}"} for i in range(10)]
        r = prefiltrar(cands, tope_dominio=3)
        assert len(r["aceptados"]) == 3
        assert all("tope" in d["motivo"] for d in r["descartados"])

    def test_conserva_el_orden_del_buscador(self):
        from cognia.search.prefiltro import prefiltrar
        cands = [{"url": f"https://s{i}.org/a"} for i in range(5)]
        r = prefiltrar(cands)
        assert [a["url"] for a in r["aceptados"]] == [c["url"] for c in cands]

    def test_lo_descartado_dice_por_que(self):
        from cognia.search.prefiltro import prefiltrar
        r = prefiltrar([{"url": "https://a.org/x.pdf"},
                        {"url": "https://r.jina.ai/https://a.org/x"},
                        {"url": "https://a.org/y"},
                        {"url": "https://a.org/y/"}])
        motivos = sorted(d["motivo"].split(" ")[0] for d in r["descartados"])
        assert motivos == ["agregador", "duplicada", "extensión"]
        assert len(r["aceptados"]) == 1

    def test_sin_nada_que_filtrar_no_descarta_nada(self):
        # El caso que protege el recall: candidatos limpios pasan enteros.
        from cognia.search.prefiltro import prefiltrar
        cands = [{"url": f"https://sitio{i}.org/articulo"} for i in range(20)]
        r = prefiltrar(cands)
        assert len(r["aceptados"]) == 20 and r["ahorro"] == 0.0


class TestElMotorDeWorkflowsTambienPuedeVerSusFallos:
    """`paralelo_env` en el motor de workflows: mismo envelope, y sin tocar
    `paralelo()`, que tiene llamadores con el contrato del None."""

    def test_devuelve_lote_con_la_causa_y_el_indice(self):
        from cognia.agent.workflows import paralelo_env

        def _ok():
            return "bien"

        def _mal():
            raise ValueError("la rama 1 exploto")

        lote = paralelo_env([_ok, _mal, _ok])
        assert [s.ok for s in lote.sobres] == [True, False, True]
        assert lote.fallidos[0].spec == 1          # QUÉ rama
        assert "exploto" in lote.fallidos[0].error  # POR QUÉ
        assert lote.resumen() == "2/3 ok, 1 fallidos (ValueError×1)"

    def test_el_paralelo_viejo_sigue_intacto(self):
        # Contrafactual: no se puede arreglar un fallo silencioso creando
        # otro. Quien dependa del None lo sigue recibiendo.
        from cognia.agent.workflows import paralelo
        salida = paralelo([lambda: 1,
                           lambda: (_ for _ in ()).throw(ValueError("x"))])
        assert salida == [1, None]


class TestElDeadlineEsDelLoteNoPorFuturo:

    def test_la_pared_no_se_multiplica_por_el_numero_de_specs(self):
        """`fut.result(timeout=X)` en un bucle reinicia el reloj en cada
        iteración: 6 specs colgados costaban 6×X, no X. Eso rompía el
        contrato de presupuesto en segundos de pared."""
        import time as _t
        t0 = _t.time()
        lote = FO.en_paralelo(list(range(6)), lambda i: _t.sleep(30), cap=2,
                              timeout_s=1.0)
        pared = _t.time() - t0
        assert pared < 3.0, f"tardó {pared:.1f}s: el deadline no es del lote"
        assert len(lote.fallidos) == 6
        assert all(s.tipo_error == "Timeout" for s in lote.fallidos)

    def test_lo_que_termina_a_tiempo_se_conserva(self):
        # El deadline no puede convertir en fallo lo que sí respondió.
        import time as _t
        lote = FO.en_paralelo([0.01, 0.01, 30], _t.sleep, cap=3, timeout_s=2.0)
        assert [s.ok for s in lote.sobres] == [True, True, False]


class TestElBrazoNuloEsElPipelineViejo:

    def test_estrecho_recorta_a_2000_no_a_4511(self):
        """Con el tope derivado de tok_por_pagina, 'estrecho' recortaba a
        4.511 chars mientras declaraba 2.000 — y la separación con la aguja
        del banco (sembrada a 6.000) quedaba en pie de casualidad."""
        pagina = {"url": "u", "texto": "x" * 20_000}
        salida = CTX.repartir([pagina], CTX.ESTRECHO)
        cuerpo = salida[0]["texto"].split("\n[...")[0]
        assert len(cuerpo) == 2_000

    def test_cada_modo_recorta_a_lo_que_declara(self):
        for modo in (CTX.ESTRECHO, CTX.MEDIO, CTX.ANCHO):
            salida = CTX.repartir([{"url": "u", "texto": "y" * 200_000}], modo)
            cuerpo = salida[0]["texto"].split("\n[...")[0]
            # una sola página larga puede quedarse con el reparto sobrante,
            # pero nunca con menos de lo declarado
            assert len(cuerpo) >= modo.chars_por_pagina


class TestLosArreglosDeLaRevisionAdversarial:
    """Cuatro hallazgos más que sobrevivieron al abogado del diablo."""

    def test_el_prefiltro_APLAZA_por_dominio_en_vez_de_tirar(self):
        """2 resultados pasaban a 0: si las 3 primeras de un dominio fallan
        al extraer, la 4ª es lo único que queda. Un prefiltro que ahorra
        bajando el recall está reprobado por su propia guarda."""
        from cognia.knowledge.navegador import buscar_en_web

        def _buscador(_c, _n):
            return [{"url": f"https://unico.org/p{i}", "titulo": "t",
                     "resumen": ""} for i in range(6)]

        def _extractor(url, timeout_s=25):
            if url.endswith(("p0", "p1", "p2")):
                raise RuntimeError("404")
            return {"titulo": "t", "texto": "contenido util del tema " * 40,
                    "url_final": url, "via": "test"}

        r = buscar_en_web("tema", max_resultados=2, buscador=_buscador,
                          extractor=_extractor)
        assert len(r["resultados"]) == 2

    def test_pero_el_ahorro_sigue_vivo(self):
        # Duplicados y PDFs NO se intentan: esos descartes sí son definitivos
        # porque no aportan recall.
        from cognia.search.prefiltro import prefiltrar
        r = prefiltrar([{"url": "https://www.a.org/x/?utm_source=1"},
                        {"url": "http://a.org/x"},
                        {"url": "https://a.org/y.pdf"},
                        {"url": "https://b.org/z"}])
        assert len(r["aceptados"]) == 2 and len(r["descartados"]) == 2
        assert r["reserva"] == []

    def test_la_familia_de_sampling_no_captura_al_14b(self):
        from cognia.agent import model_profiles as MP
        cfg, fam = MP._cfg_familia("OpenReasoning-Nemotron-14B.Q4_K_M.gguf")
        assert fam != "nemotron-3.5"
        cfg2, fam2 = MP._cfg_familia("nemotron-3.5-lightning-30b-a3b.gguf")
        assert fam2 == "nemotron-3.5" and cfg2["top_p"] == 0.95

    def test_aci_trim_con_el_cap_historico_es_byte_identico(self, tmp_path,
                                                            monkeypatch):
        """1200/450 EXACTOS con cap 1800: repartir sobre head+tail daba
        1309/491 y rompía el contrafactual en los decimales."""
        import cognia.agents.workers.dev_tools as dev
        from cognia.agent import tools
        monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
        texto = "A" * 10_000
        out = tools.aci_trim(texto, "x", cap=1800)
        cabeza, cola = out.split("\n[... ")[0], out.rsplit(" ...]\n", 1)[1]
        assert len(cabeza) == 1200 and len(cola) == 450

    def test_si_chromium_no_arranca_no_se_pierden_las_paginas_http(
            self, monkeypatch):
        """El launch fallando se llevaba por delante TODOS los sobres HTTP
        que ya habían salido bien."""
        from cognia.knowledge import navegador as NAV

        def _http_ok(url, timeout_s=15):
            return {"titulo": "t", "texto": "x" * 5000, "url_final": url,
                    "via": "http"}

        import playwright.sync_api as pw
        monkeypatch.setattr(pw, "sync_playwright",
                            lambda: (_ for _ in ()).throw(
                                RuntimeError("no hay Chromium")))
        # una corta fuerza la segunda fase; la larga ya está bien
        def _http_mixto(url, timeout_s=15):
            if url.endswith("corta"):
                return {"titulo": "t", "texto": "poco", "url_final": url,
                        "via": "http"}
            return _http_ok(url, timeout_s)

        lote = NAV.extraer_muchas(["https://a.org/larga", "https://a.org/corta"],
                                  extractor_http=_http_mixto)
        assert len(lote.ok) >= 1
        assert any((s.valor or {}).get("texto", "").startswith("x")
                   for s in lote.ok)
