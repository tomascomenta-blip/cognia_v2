# -*- coding: utf-8 -*-
"""Tests del miniagente reformulador (cognia/harness/mejorar_prompt.py).

Sin red y sin backend: `mejorar()` recibe siempre `generar_fn` inyectado, y el
unico caso que no lo inyecta monkeypatchea `_detectar_url` para simular que no
hay llama-server. Si algun test llega a la red, es un bug del modulo.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from cognia.harness import mejorar_prompt as mp  # noqa: E402


# ------------------------------------------------------------- es_candidato

def test_candidato_vacio_y_espacios():
    assert mp.es_candidato("") is False
    assert mp.es_candidato("        ") is False
    assert mp.es_candidato(None) is False


def test_candidato_slash_no_es_candidato():
    # Un comando lo interpreta el CLI, no el modelo: reformularlo lo rompe.
    assert mp.es_candidato("/hacer un servidor http en python") is False
    assert mp.es_candidato("   /ayuda contexto largo aqui") is False


def test_candidato_bang_no_es_candidato():
    assert mp.es_candidato("!ls -la C:/Users/usuario/Desktop") is False


def test_candidato_texto_corto():
    assert mp.es_candidato("hola") is False
    assert mp.es_candidato("dame un plan") is True          # 13 chars
    # El umbral es configurable y se respeta.
    assert mp.es_candidato("dame un plan", minimo_chars=40) is False


def test_candidato_texto_demasiado_largo():
    pegado = "x" * (mp.MAX_CHARS + 1)
    assert mp.es_candidato(pegado) is False
    assert mp.es_candidato("y" * (mp.MAX_CHARS - 1)) is True


def test_candidato_normal():
    assert mp.es_candidato("arregla el login que rechaza usuarios validos") is True


def test_candidato_centinela_de_inyeccion():
    # Lineas de la cola del REPL: llevan NUL y no son texto tecleado.
    assert mp.es_candidato("\x00@f2@escribe un plan de pruebas") is False
    assert mp.es_candidato("\x00@fin@") is False


# ------------------------------------------------------------ sanear_salida

def test_sanear_quita_preambulo():
    original = "hazme un script que renombre fotos por fecha"
    bruto = ("Claro, aqui tienes el prompt mejorado:\n"
             "Escribe un script de Python que renombre las fotos de una "
             "carpeta usando su fecha de captura.")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"
    assert texto.startswith("Escribe un script de Python")
    assert "prompt mejorado" not in texto.lower()


def test_sanear_quita_vallas_de_codigo():
    original = "hazme un script que renombre fotos por fecha"
    bruto = ("```\nEscribe un script de Python que renombre las fotos de una "
             "carpeta segun su fecha de captura.\n```")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"
    assert "```" not in texto
    assert texto.startswith("Escribe un script")


def test_sanear_quita_comillas_envolventes():
    original = "hazme un script que renombre fotos por fecha"
    bruto = ('"Escribe un script de Python que renombre las fotos de una '
             'carpeta segun su fecha de captura."')
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"
    assert texto[0] != '"' and texto[-1] != '"'


def test_sanear_quita_etiquetas_filtradas():
    original = "hazme un script que renombre fotos por fecha"
    bruto = ("<think>El usuario quiere renombrar. Voy a reformular.</think>\n"
             "<prompt>Escribe un script de Python que renombre las fotos de "
             "una carpeta segun su fecha de captura.</prompt>")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"
    assert "<think>" not in texto and "<prompt>" not in texto
    # El razonamiento no se cuela en el prompt final.
    assert "Voy a reformular" not in texto


def test_sanear_rechaza_vacio():
    texto, motivo = mp.sanear_salida("   \n  ", "arregla el login del panel")
    assert motivo == "salida vacia"
    assert texto == ""


def test_sanear_rechaza_identico():
    original = "arregla el login que rechaza usuarios validos"
    texto, motivo = mp.sanear_salida("  Arregla el login que rechaza "
                                     "usuarios validos  ", original)
    assert motivo == "identico al original"


def test_sanear_rechaza_demasiado_corto():
    # Perder contenido del usuario es peor que no mejorar nada.
    original = ("arregla el login del panel de administracion que rechaza "
                "usuarios validos cuando la clave lleva acentos")
    texto, motivo = mp.sanear_salida("Arregla el login.", original)
    assert motivo == "demasiado corto (perdio contenido)"


def test_sanear_rechaza_demasiado_largo():
    # Crecer sin freno = el modelo entrego un documento en vez de una linea.
    original = "arregla el login del panel"
    inflado = ("Arregla el login del panel usando OAuth2 con Keycloak, migra "
               "la base a PostgreSQL 16, anade 2FA por TOTP, escribe tests de "
               "integracion con pytest y documenta el flujo en un README con "
               "diagramas de secuencia y un changelog semantico versionado. ") * 5
    assert len(inflado) > mp.tope_salida(original)
    texto, motivo = mp.sanear_salida(inflado, original)
    assert motivo.startswith("mas largo del tope previsto")


def test_el_rechazo_por_LARGO_no_acusa_de_inventar():
    """REGRESION (ronda 2). El tope por largo es un rechazo de PRESUPUESTO y
    tiene que decirlo. Compartia cadena con la acusacion de contenido
    ("demasiado largo (probable invencion)"), asi que al usuario se le decia
    que el modelo "probablemente invento" sobre salidas que no inventaban
    nada, y ni el usuario ni el log podian separar los dos casos. El motivo
    trae ademas las dos cifras, que es lo que hace falta para recalibrar."""
    original = "arregla el login del panel"
    largo = ("Arregla el login. " * 200).strip()
    texto, motivo = mp.sanear_salida(largo, original)
    assert "invencion" not in motivo
    assert str(len(largo)) in motivo and str(mp.tope_salida(original)) in motivo


def test_sanear_rechaza_respuesta_en_vez_de_reformulacion():
    original = "hazme una funcion que ordene una lista de numeros"
    bruto = ("Claro, voy a crear esa funcion. He escrito el codigo que "
             "necesitas para ordenar la lista de numeros enteros.")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "el modelo respondio en vez de reformular"


def test_sanear_rechaza_codigo_como_respuesta():
    original = "hazme una funcion que ordene una lista de numeros"
    bruto = "def ordenar(numeros):\n    return sorted(numeros)\n"
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "el modelo respondio en vez de reformular"


def test_sanear_acepta_reformulacion_legitima_en_imperativo():
    # Guardia anti-falso-positivo de la heuristica de "respuesta": un prompt
    # normal en imperativo NO puede caer en ninguna marca.
    original = "hazme una funcion que ordene una lista de numeros"
    bruto = ("Escribe una funcion en Python que reciba una lista de numeros "
             "y devuelva una nueva lista ordenada de forma ascendente.")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"
    assert texto == bruto


def test_sanear_tolera_tildes_en_el_preambulo():
    # El matcheo normaliza tildes conservando indices: si se desalineara, el
    # corte se comeria letras del prompt.
    original = "hazme un script que renombre fotos por fecha"
    bruto = ("Aqu\u00ed tienes el prompt reformulado:\n"
             "Escribe un script de Python que renombre las fotos por fecha.")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"
    assert texto.startswith("Escribe un script de Python")


def test_sanear_no_textual():
    texto, motivo = mp.sanear_salida(None, "arregla el login del panel")
    assert motivo == "salida no textual"


# --------------------------------------------- lo que NO puede cambiar nunca

def test_sanear_rechaza_que_la_linea_CAMBIE_DE_CLASE():
    # es_candidato descarta a la ENTRADA las lineas que empiezan por '/' o '!'
    # porque las despacha el CLI, no el modelo. Si la reformulacion empieza
    # asi, el turno se pierde en "Comando desconocido" -- o peor, EJECUTA un
    # comando que el usuario no escribio.
    original = "revisa el log de nginx y dime por que devuelve 502"
    bruto = ("/var/log/nginx/error.log: analiza las ultimas 200 lineas e "
             "identifica la causa del 502")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "cambio la clase de linea (empieza por / o !)"
    # Y si el original YA era un comando (via '/mejorar <texto>'), no aplica.
    texto, motivo = mp.sanear_salida("/hacer arregla el login del panel",
                                     "/hacer arregla login")
    assert motivo == "ok"


def test_sanear_rechaza_si_pierde_una_mencion():
    # '@ruta' es un sigilo del REPL que se expande DESPUES de este modulo: si
    # el modelo lo convierte en prosa, el fichero deja de adjuntarse y el
    # cerebro contesta sobre algo que nunca vio, en silencio.
    original = "@cognia/cli.py resume que hace este fichero"
    bruto = "Resume el proposito y las responsabilidades del fichero cognia/cli.py"
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "perdio una @-mencion (@cognia/cli.py)"


def test_sanear_acepta_la_mejora_que_CONSERVA_la_mencion():
    original = "@cognia/cli.py resume que hace este fichero"
    bruto = ("Resume en tres puntos que responsabilidades tiene el fichero "
             "@cognia/cli.py.")
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"


def test_sanear_no_confunde_un_correo_con_una_mencion():
    # Guardia anti-falso-positivo: '@' pegado a una palabra (juan@x.com) NO
    # abre mencion en el REPL, asi que perderlo no es motivo de rechazo.
    original = "escribe un correo a juan@ejemplo.com pidiendo el informe"
    bruto = "Redacta un correo para el destinatario indicado pidiendo el informe"
    texto, motivo = mp.sanear_salida(bruto, original)
    assert motivo == "ok"


# ------------------------------------------------------------------ mejorar

ORIGINAL = "arregla el login que rechaza usuarios validos"
MEJORADO = ("Corrige el formulario de login para que deje de rechazar "
            "usuarios con credenciales validas.")


def test_mejorar_exito(monkeypatch):
    # Sin borrar la env var el test mide el brazo del shell, no el default.
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    visto = {}

    def _fake(prompt, system):
        visto["prompt"] = prompt
        visto["system"] = system
        return MEJORADO

    res = mp.mejorar(ORIGINAL, generar_fn=_fake)
    assert res.ok is True
    assert res.texto == MEJORADO
    assert res.original == ORIGINAL
    assert res.motivo == "ok"
    assert res.ms >= 0
    # El texto crudo viaja delimitado y con las reglas del system.
    assert ORIGINAL in visto["prompt"]
    # Cual es el system depende de la version por defecto; lo que NO depende de
    # la version es que prohiba inventar, asi que se comprueba eso y no el
    # texto literal de v1.
    # NO se compara contra system_prompt(): mejorar() y system_prompt() resuelven
    # por el MISMO _resolver_version, asi que esa asercion era AUTO-REFERENCIAL
    # (pasaba igual con el default en v1 o con _resolver_version roto). Se ancla
    # al diccionario y a la constante, que es lo que parte un bug de resolucion.
    assert visto["system"] is mp.VERSIONES_SYSTEM[mp.VERSION_DEFECTO]
    assert "PROHIBIDO" in visto["system"]


def test_mejorar_pasa_el_contexto_marcado_como_no_requisito():
    visto = {}

    def _fake(prompt, system):
        visto["prompt"] = prompt
        return MEJORADO

    res = mp.mejorar(ORIGINAL, contexto="repo: cognia_v2", generar_fn=_fake)
    assert res.ok is True
    assert "repo: cognia_v2" in visto["prompt"]
    assert "NO lo conviertas en requisitos" in visto["prompt"]


def test_mejorar_excepcion_no_escapa():
    def _explota(prompt, system):
        raise ValueError("backend en llamas")

    res = mp.mejorar(ORIGINAL, generar_fn=_explota)
    assert res.ok is False
    assert res.texto == ORIGINAL == res.original
    assert "ValueError" in res.motivo
    assert "backend en llamas" in res.motivo


def test_mejorar_timeout_simulado():
    def _cuelga(prompt, system):
        # socket.timeout es OSError; asi lo lanza urllib al vencer el plazo.
        raise TimeoutError("timed out")

    res = mp.mejorar(ORIGINAL, timeout_s=0.01, generar_fn=_cuelga)
    assert res.ok is False
    assert res.texto == ORIGINAL
    assert res.motivo.startswith("timeout o red")


def test_mejorar_salida_vacia():
    res = mp.mejorar(ORIGINAL, generar_fn=lambda p, s: "   ")
    assert res.ok is False
    assert res.motivo == "salida vacia"
    assert res.texto == ORIGINAL


def test_mejorar_salida_none():
    res = mp.mejorar(ORIGINAL, generar_fn=lambda p, s: None)
    assert res.ok is False
    assert res.motivo == "el backend no devolvio texto"
    assert res.texto == ORIGINAL


def test_mejorar_sin_backend(monkeypatch):
    # Sin generar_fn y sin llama-server vivo: degrada al original, no revienta
    # ni toca la red (se anula el detector).
    monkeypatch.setattr(mp, "_detectar_url", lambda url=None: None)
    res = mp.mejorar(ORIGINAL)
    assert res.ok is False
    # El motivo ahora lleva el detalle (cual de los casos fue); el prefijo es
    # lo que el CLI mira para gritar la degradacion.
    assert res.motivo.startswith("sin backend local")
    assert res.texto == ORIGINAL
    assert res.modelo == ""


def test_motivo_backend_distingue_los_casos(monkeypatch):
    """"no lo cablearon" y "se rompio" no pueden verse igual. Con Ollama vivo
    el motivo generico ("sin backend local") mandaba al usuario a levantar un
    llama-server que no le hacia falta."""
    import cognia.llm_local as ll
    monkeypatch.setattr(mp, "_detectar_url", lambda url=None: None)

    monkeypatch.setattr(ll, "detectar_backend", lambda: None)
    assert mp._motivo_backend() == "sin backend local (no hay ninguno vivo)"

    monkeypatch.setattr(ll, "detectar_backend",
                        lambda: {"tipo": "ollama", "url": "http://x:11434"})
    motivo = mp._motivo_backend()
    assert "ollama" in motivo and "no soportado" in motivo
    # y ese motivo llega intacto al resultado, que es lo que ve el usuario
    assert mp.mejorar(ORIGINAL).motivo == motivo

    def _revienta():
        raise ImportError("no module named llm_local")

    monkeypatch.setattr(ll, "detectar_backend", _revienta)
    assert mp._motivo_backend().startswith("sin backend local: ImportError")


def test_un_fallo_interno_sube_por_aviso_en_vez_de_callarse(monkeypatch):
    """El modulo es puro (no imprime), asi que un fallo interno solo puede
    REPORTARSE. Antes era un `except: pass` y desaparecia: el sintoma llegaba
    como "salida vacia" sin una pista de la causa."""
    from cognia.agent import model_profiles

    def _revienta():
        raise RuntimeError("perfil ilegible")

    monkeypatch.setattr(model_profiles, "perfil_del_agente", _revienta)
    registro = {}
    assert mp._kwargs_plantilla(registro) == {}
    assert "perfil del modelo" in registro["aviso"]
    assert "RuntimeError" in registro["aviso"]
    # y el campo viaja en el resultado para que el CLI lo grite
    assert mp.Mejora(ok=True, texto="x", original="x", motivo="ok", ms=1,
                     modelo="", aviso="boom").aviso == "boom"


def test_mejorar_texto_vacio_no_llama_al_modelo():
    llamadas = []

    def _fake(prompt, system):
        llamadas.append(prompt)
        return MEJORADO

    res = mp.mejorar("   ", generar_fn=_fake)
    assert res.ok is False
    assert res.motivo == "texto vacio"
    assert llamadas == []


def test_mejorar_rechaza_salida_sospechosa_y_devuelve_original():
    # Integracion de mejorar() con el saneador: un rechazo deja el turno
    # intacto (texto == original), nunca a medias.
    res = mp.mejorar(ORIGINAL, generar_fn=lambda p, s: "Claro, ya lo arregle.")
    assert res.ok is False
    assert res.texto == ORIGINAL
    assert res.motivo in ("el modelo respondio en vez de reformular",
                          "demasiado corto (perdio contenido)")


def test_mejora_es_dataclass_con_el_contrato():
    campos = mp.Mejora.__dataclass_fields__
    # 'aviso' se sumo al arreglar el `except: pass` del registro en el audit:
    # el modulo es puro (no imprime), asi que un fallo INTERNO tiene que poder
    # subir hasta quien cablea para que lo grite. Va al final y con default.
    assert list(campos) == ["ok", "texto", "original", "motivo", "ms",
                            "modelo", "aviso"]
    assert mp.Mejora.__dataclass_fields__["aviso"].default == ""
    assert mp.ESTADOS == ("off", "preguntar", "auto")


def test_modulo_es_puro_no_importa_cli():
    fuente = (ROOT / "cognia" / "harness" / "mejorar_prompt.py").read_text(
        encoding="utf-8")
    # Se miran los IMPORTS reales, no la prosa (el docstring nombra cognia.cli
    # para explicar justamente que no lo usa).
    codigo = [l.strip() for l in fuente.splitlines()
              if l.strip().startswith(("import ", "from "))]
    assert not any("cognia.cli" in l for l in codigo), codigo
    assert "print(" not in fuente
    # Estilo del repo: ASCII puro.
    assert all(ord(c) < 128 for c in fuente)



# ------------------------------- el guardia COSMETICO (bug medido ronda 1)

def test_sanear_rechaza_la_mejora_SOLO_COSMETICA():
    """El guardia de "identico" normalizaba minusculas y tildes pero NO la
    puntuacion, asi que anadir una mayuscula y un punto contaba como mejora.
    Medido contra el modelo real: 3 de las 5 tareas del diagnostico salian
    "ok" con un cambio de contenido CERO, y cada una le cobraba al usuario dos
    selectores (confirmar y leer el diff) por nada."""
    casos = [
        ("Arregla el bug del login.", "arregla el bug del login"),
        ("Genera una lista de compras semanal.",
         "genera una lista de compras semanal"),
        ("Organiza el escritorio!", "organiza el escritorio"),
    ]
    for salida, original in casos:
        texto, motivo = mp.sanear_salida(salida, original)
        assert motivo == "identico al original", (salida, original, motivo)
    # Honestidad sobre el alcance: de las 5 tareas medidas, este guardia solo
    # caza las que cambian SOLO puntuacion. "organizame el escritorio" ->
    # "Organiza el escritorio." cambia palabras (y encima pierde el posesivo),
    # asi que pasa por aqui: lo que arregla ESE caso es el system v2, no el
    # saneador. Se deja escrito para que nadie lo confunda con un fallo.
    texto, motivo = mp.sanear_salida("Organiza el escritorio.",
                                     "organizame el escritorio")
    assert motivo == "ok"


def test_sanear_rechaza_cambios_de_espacios_comillas_y_signos():
    original = "arregla el bug del login"
    for salida in ['"Arregla   el bug del login!"',
                   "Arregla, el bug del login...",
                   "  \u00a1Arregla el bug del login!  ",
                   "(Arregla el bug del login)"]:
        texto, motivo = mp.sanear_salida(salida, original)
        assert motivo == "identico al original", (salida, motivo)


def test_el_esqueleto_NO_borra_lo_que_cambia_el_significado():
    """Guardia anti-sobre-normalizacion: si el esqueleto se comiera '@', '/'
    o '!', dos lineas con significados distintos para el REPL se verian
    iguales y el motivo del rechazo saldria equivocado."""
    # '@' abre una @-mencion: quitarlo cambia si el fichero se adjunta.
    assert mp._esqueleto("@cli.py resume esto") != mp._esqueleto("cli.py resume esto")
    # '/' y '!' marcan la CLASE de la linea (comando vs chat).
    assert mp._esqueleto("/ayuda del panel") != mp._esqueleto("ayuda del panel")
    assert mp._esqueleto("!ls del panel") != mp._esqueleto("ls del panel")
    # y un cambio de contenido real sigue siendo un cambio
    assert mp._esqueleto("Corrige el login.") != mp._esqueleto("arregla el login")


# --------------------------------------------- el tope ADAPTATIVO de largo

def test_tope_salida_es_adaptativo():
    # Textos cortos: manda el piso absoluto (el ratio los ahogaba).
    corto = "arregla el bug del login"          # 24 chars -> 8x = 192
    assert mp.tope_salida(corto) == mp.PISO_MAX_SALIDA == 800
    # Textos largos: manda el ratio.
    largo = "x" * 200
    assert mp.tope_salida(largo) == 1600
    # El punto de cruce esta donde el ratio alcanza al piso.
    assert mp.tope_salida("x" * 100) == 800
    assert mp.tope_salida("x" * 101) == 808


# Maximo MEDIDO de la distribucion de salidas reales de v2 (n=24, las 24
# llamadas del A/B en scratchpad/ab_mejorador/crudo.json; min 291, p50 382,
# p95 458). La fila es 'organizame el escritorio', replica 2.
MAX_MEDIDO_V2 = 541


def test_el_piso_cubre_la_distribucion_MEDIDA():
    """REGRESION (ronda 2). El piso valia 600 y su comentario decia "el techo
    medido (423) mas ~40% de margen", pero ese 423 salia de n=5 muestras del
    diagnostico de la ronda 1. La corrida A/B de la MISMA ronda lo desmintio
    con n=24: el maximo real es 541 chars, o sea 90,2% del tope y un margen del
    10,9%, no del 40%. Este test fija la regla de calibracion contra el numero
    medido, para que el piso no vuelva a quedarse corto en silencio."""
    assert mp.PISO_MAX_SALIDA >= int(MAX_MEDIDO_V2 * 1.4)   # 600 no llegaba
    # y una salida realmente larga de ese regimen se acepta
    original = "organizame el escritorio"
    salida = (
        "Organiza mi escritorio de forma que todo este ordenado y accesible. "
        "Antes de mover nada, preguntame que tipo de superficie tengo (mesa, "
        "escritorio de pared, bandeja de escritorio o incluso un tablero "
        "improvisado), que objetos hay encima ahora mismo, con que frecuencia "
        "los uso y si prefiero agruparlos por tipo o por frecuencia de uso. "
        "Con esas respuestas devuelve un plan por pasos para dejarlo ordenado, "
        "diciendo donde va cada cosa, y una senal concreta para saber si el "
        "escritorio quedo realmente organizado y accesible.")
    assert 500 < len(salida) <= mp.tope_salida(original)
    texto, motivo = mp.sanear_salida(salida, original)
    assert motivo == "ok"


def test_sanear_ACEPTA_la_expansion_legitima_de_un_pedido_CORTO():
    """Salida REAL de v2 contra el modelo local (417 chars sobre 24 de
    entrada). Con el ratio fijo de 8x el tope era 192 y esto se rechazaba como
    "probable invencion": el caso principal del dueno quedaba sin producto."""
    original = "arregla el bug del login"
    salida = ("Arregla el bug del login. Antes de tocar nada, preguntame que "
              "sistema operativo usa mi maquina, que navegador o cliente estoy "
              "empleando y si el error aparece siempre o solo en ciertas "
              "condiciones. Con esa informacion devuelve un plan de pasos "
              "concretos para diagnosticar y solucionar el fallo, indicando en "
              "cada paso que comando o accion ejecutar y que resultado esperar "
              "para confirmar que el login funciona de nuevo.")
    assert 8 * len(original) < len(salida) <= mp.tope_salida(original)
    texto, motivo = mp.sanear_salida(salida, original)
    assert motivo == "ok"


def test_el_tope_SIGUE_frenando_la_fuga_en_un_pedido_corto():
    # El limite superior no desaparecio: un documento entero se sigue tirando.
    original = "arregla el bug del login"
    fuga = ("Migra la autenticacion a OAuth2 con Keycloak 24, anade 2FA por "
            "TOTP, cambia la base a PostgreSQL 16 y documenta el flujo. ") * 8
    texto, motivo = mp.sanear_salida(fuga, original)
    assert motivo.startswith("mas largo del tope previsto")
    assert len(fuga) > mp.tope_salida(original)


# ------------------------------------------- selector de version del system

def test_system_prompt_default_es_v2(monkeypatch):
    # El default es v2 desde el A/B ciego del 2026-08-19: v2 gana 11 de 12
    # filas (v1 gana 1, 0 empates, neto +10) y ninguno de los dos brazos
    # inventa un dato en 24/24 salidas. Si esto cambia solo, el brazo servido
    # deja de ser el brazo medido.
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    assert mp.system_prompt() is mp._SYSTEM_V2
    assert mp.VERSION_DEFECTO == "v2"


def test_v1_sigue_alcanzable_para_volver_atras(monkeypatch):
    """El A/B eligio v2, pero v2 tiene un modo de fallo medido (en la fila
    'escritorio' cambio el entregable). La marcha atras no puede exigir editar
    codigo: tiene que estar a un env var de distancia."""
    monkeypatch.setenv(mp.ENV_VERSION, "v1")
    assert mp.system_prompt() is mp._SYSTEM_V1
    monkeypatch.setenv(mp.ENV_VERSION, "  V1  ")
    assert mp.system_prompt() is mp._SYSTEM_V1


def test_system_prompt_por_env_var_y_por_argumento(monkeypatch):
    monkeypatch.setenv(mp.ENV_VERSION, "v1")
    assert mp.system_prompt() is mp._SYSTEM_V1
    # El argumento explicito gana a la env var.
    assert mp.system_prompt("v2") is mp._SYSTEM_V2
    monkeypatch.setenv(mp.ENV_VERSION, "  V2  ")
    assert mp.system_prompt() is mp._SYSTEM_V2


def test_una_version_desconocida_no_se_traga_en_silencio(monkeypatch):
    """Un 'COGNIA_MEJORA_PROMPT=v9' mal escrito caeria al default sin que nadie
    lo note y el A/B mediria dos veces el mismo brazo. (El nombre de prueba NO
    puede ser una version real: 'v3' existe desde la ronda 2.)"""
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    assert "v9" not in mp.VERSIONES_SYSTEM
    nombre, aviso = mp._resolver_version("v9")
    assert nombre == "v2"
    assert "desconocida" in aviso and "v9" in aviso
    # y el aviso viaja hasta el resultado para que el CLI lo grite
    res = mp.mejorar(ORIGINAL, version="v9", generar_fn=lambda p, s: MEJORADO)
    assert res.ok is True
    assert "desconocida" in res.aviso


def test_mejorar_manda_el_system_de_la_version_pedida():
    visto = {}

    def _fake(prompt, system):
        visto["system"] = system
        return MEJORADO

    mp.mejorar(ORIGINAL, version="v2", generar_fn=_fake)
    assert visto["system"] is mp._SYSTEM_V2
    mp.mejorar(ORIGINAL, version="v1", generar_fn=_fake)
    assert visto["system"] is mp._SYSTEM_V1


def test_v2_ensena_la_frontera_legitimo_prohibido():
    """v2 solo sirve si le deja clarisima al 9B la linea entre explicitar y
    inventar. Un 9B sigue mejor un EJEMPLO que una regla, asi que los dos
    ejemplos son parte del contrato, no decoracion."""
    v2 = mp._SYSTEM_V2
    assert "PROHIBIDO" in v2 and "OBLIGATORIO" in v2
    # lo prohibido: afirmar datos que el usuario no dio
    for palabra in ("fechas", "presupuestos", "cantidades", "nombres",
                    "tecnologias", "rutas"):
        assert palabra in v2, palabra
    # lo legitimo y deseado
    assert "PREGUNTA" in v2 and "[placeholder]" in v2
    assert "FORMATO" in v2 and "criterio de exito" in v2
    # el sujeto del usuario no se pierde
    assert "preguntame" in v2 and "tercera persona" in v2
    # los dos ejemplos, uno de cada lado de la linea
    assert "EJEMPLO 1 - expansion legitima" in v2
    assert "EJEMPLO 2 - invencion prohibida" in v2
    # v1 sigue existiendo intacto como marcha atras (COGNIA_MEJORA_PROMPT=v1)
    assert "PROHIBIDO inventar" in mp._SYSTEM_V1
    # ENMIENDA 2026-08-29 (PEDIDO 5.1): se registra v4 -- el system que NO mete
    # preguntas en el prompt, para cuando la encuesta ya pregunto aparte. La
    # igualdad exhaustiva se mantiene a proposito: es el guardian de que nadie
    # cuele una version nueva sin declararla, y las cuatro siguen derivando de
    # los mismos literales. Que v2 no cambio lo fija test_v2_sigue_intacto.
    assert mp.VERSIONES_SYSTEM == {"v1": mp._SYSTEM_V1, "v2": mp._SYSTEM_V2,
                                   "v3": mp._SYSTEM_V3, "v4": mp._SYSTEM_V4}


def test_v3_anade_las_dos_formas_que_le_faltaban_a_v2():
    """REGRESION (ronda 2). Contado sobre las 24 salidas de v2 del A/B, v2 no
    aprendio una regla: copio la PLANTILLA del EJEMPLO 1 (24/24 con "Antes de",
    16/24 empezando por "Arma " con las tres conectivas del ejemplo), y su unico
    fallo de entregable medido sale de ahi. v3 mete dos formas mas. Se construye
    por insercion sobre v2, asi que si el ancla se pierde v3 quedaria IGUAL a v2
    y nadie se enteraria: esto es lo que lo caza."""
    v3 = mp._SYSTEM_V3
    assert v3 != mp._SYSTEM_V2 and len(v3) > len(mp._SYSTEM_V2)
    # v2 entero sigue dentro: v3 es v2 + ejemplos, no un prompt distinto.
    assert "EJEMPLO 1 - expansion legitima" in v3
    assert "EJEMPLO 2 - invencion prohibida" in v3
    # la forma que le faltaba: actuar sobre algo que ya existe
    assert "EJEMPLO 3 - actuar sobre algo que YA existe" in v3
    assert "Organiza mi escritorio." in v3
    # y la de "ya es especifico, se toca poco"
    assert "EJEMPLO 4 - ya es especifico" in v3
    # el cierre queda al FINAL, despues de los ejemplos nuevos
    assert v3.rstrip().endswith("sin comentarios.")
    assert v3.index("EJEMPLO 4") < v3.index(mp._ANCLA_CIERRE)


def test_v3_NO_es_el_default_porque_no_esta_medido():
    """El brazo servido tiene que ser el brazo MEDIDO. v3 no gano ningun A/B:
    entra como punto de extension seleccionable, no como default silencioso."""
    assert mp.VERSION_DEFECTO == "v2"
    assert mp.system_prompt("v3") is mp._SYSTEM_V3


# ------------------------------------------- el presupuesto de tokens (H6)

def _generar_con_finish(registro, contenido, razon):
    """Simula el generar_fn REAL: escribe finish_reason en `registro` igual que
    _construir_generar, que es el unico que lo ve."""
    def _fn(prompt, system):
        registro["finish_reason"] = razon
        return contenido
    return _fn


def test_una_salida_CORTADA_por_max_tokens_no_se_acepta(monkeypatch):
    """REGRESION (ronda 2). _construir_generar leia solo `content` y tiraba el
    resto: una generacion cortada en el token N_PREDICT cae DENTRO de la banda
    de largo, pasa todos los guardias de sanear_salida y en estado 'auto' se
    envia al cerebro a media frase sin que el usuario la apruebe."""
    original = "arregla el bug del login"
    # Fragmento plausible y CORTADO: dentro de la banda, sin marcas de nada.
    trunco = ("Arregla el bug del login. Antes de tocar nada, preguntame que "
              "navegador uso, que mensaje de error exacto veo y en que")
    assert mp.sanear_salida(trunco, original)[1] == "ok"   # el saneador no lo ve

    # Se monta el camino real: mejorar() lee el finish_reason del registro que
    # llena el generar_fn construido por _construir_generar.
    monkeypatch.setattr(mp, "_construir_generar",
                        lambda url, t, registro: _generar_con_finish(
                            registro, trunco, "length"))
    monkeypatch.setattr(mp, "_detectar_url", lambda url=None: "http://x")
    res = mp.mejorar(original)
    assert res.ok is False
    assert "presupuesto de tokens" in res.motivo
    assert res.texto == original            # el fragmento NO viaja


def test_content_vacio_por_presupuesto_no_se_reporta_como_salida_vacia(
        monkeypatch):
    """El agujero tapaba el diagnostico del caso ya conocido: cuando el CoT se
    come el presupuesto (medido 3 de 4 sin enable_thinking=False) el motivo era
    'salida vacia', que se lee como fallo del BACKEND en vez de falta de
    tokens."""
    monkeypatch.setattr(mp, "_construir_generar",
                        lambda url, t, registro: _generar_con_finish(
                            registro, "", "length"))
    monkeypatch.setattr(mp, "_detectar_url", lambda url=None: "http://x")
    res = mp.mejorar("arregla el bug del login")
    assert res.ok is False
    assert res.motivo != "salida vacia"
    assert "presupuesto de tokens" in res.motivo


def test_finish_reason_normal_no_cambia_el_camino_feliz(monkeypatch):
    monkeypatch.setattr(mp, "_construir_generar",
                        lambda url, t, registro: _generar_con_finish(
                            registro, MEJORADO, "stop"))
    monkeypatch.setattr(mp, "_detectar_url", lambda url=None: "http://x")
    res = mp.mejorar(ORIGINAL)
    assert res.ok is True and res.texto == MEJORADO


def test_construir_generar_LEE_finish_reason():
    """El campo tiene que salir de la respuesta HTTP real, no de un default:
    si _construir_generar deja de escribirlo, los dos tests de arriba siguen
    verdes (se lo inyectan ellos) y el agujero vuelve sin que nadie lo vea."""
    import io as _io
    import urllib.request as _u

    cuerpo = json.dumps({
        "model": "/ruta/al/modelo.gguf",
        "choices": [{"finish_reason": "length",
                     "message": {"content": "un fragmento cortado"}}],
    }).encode("utf-8")

    class _Resp:
        def read(self):
            return cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    original_urlopen = _u.urlopen
    _u.urlopen = lambda req, timeout=None: _Resp()
    try:
        registro = {}
        fn = mp._construir_generar("http://x", 1.0, registro)
        salida = fn("prompt", "system")
    finally:
        _u.urlopen = original_urlopen
    assert salida == "un fragmento cortado"
    assert registro["finish_reason"] == "length"
    assert registro["modelo"] == "modelo.gguf"


# =========================================================================
# v4: el system que NO mete preguntas (PEDIDO 5.1)
# =========================================================================

def test_v2_sigue_intacto():
    """ANTICUERPO del brazo medido. _SYSTEM_V2 es el brazo del A/B publicado
    (v1 devolvia el texto intacto en 22/24; v2 aceptado 24/24, test de signos
    p=1,95e-3). v3 y v4 se construyen por .replace() SOBRE el, asi que la
    tentacion permanente es "arreglar" v2 in place -- y eso deja los numeros
    publicados sin respaldo, en silencio y sin que ningun test de contenido lo
    note (los asserts por palabra sobreviven a casi cualquier reescritura).
    El hash no sobrevive a ninguna.

    Si este test falla: NO actualices el hash. O revertis el cambio a v2, o lo
    llevas a una version NUEVA de VERSIONES_SYSTEM, que es exactamente para lo
    que existe el punto de extension."""
    import hashlib
    huella = hashlib.sha256(mp._SYSTEM_V2.encode("utf-8")).hexdigest()
    assert huella == ("c1be01a887c36da636eeae16b4797dbd"
                      "5ebfa119b99f715042a96878c3f0157c"), (
        "_SYSTEM_V2 cambio: el brazo medido en A/B ya no es el que se midio")
    assert len(mp._SYSTEM_V2) == 3205


def test_v4_no_pide_preguntas():
    """LA razon de ser de v4: el bug del dueno es "el mejorador mete las
    preguntas en el prompt ya entregado". v2 lo hace porque se lo ORDENAN
    (OBLIGATORIO 3) y se lo ENSENAN (EJEMPLO 1). En v4 no queda ni la orden ni
    la plantilla."""
    v4 = mp.VERSIONES_SYSTEM["v4"]
    assert "preguntame" not in v4
    assert "Antes de proponer nada" not in v4
    assert "Con esas respuestas" not in v4
    assert "convierte cada hueco en una PREGUNTA" not in v4
    # y lo dice de frente en PROHIBIDO
    assert "Terminar el prompt con una lista de preguntas" in v4


def test_v4_conserva_lo_que_hacia_util_a_v2():
    """Riesgo 16 del plan: quitar TODAS las preguntas puede reactivar el modo
    de fallo de v1 -- devolver el texto casi intacto, que sanear_salida rechaza
    por "identico al original" y el dueno lee como "el mejorador no mejora".
    Lo que lo impide es que el hueco siga existiendo, como [placeholder]."""
    v4 = mp.VERSIONES_SYSTEM["v4"]
    assert "[placeholder]" in v4
    assert "criterio de exito" in v4 and "FORMATO" in v4
    assert "De 2 a 5 frases" in v4
    # las prohibiciones de invencion siguen enteras: son el contrato duro
    for palabra in ("fechas", "presupuestos", "cantidades", "tecnologias",
                    "rutas"):
        assert palabra in v4, palabra
    assert "EJEMPLO 1 - expansion legitima" in v4
    assert "EJEMPLO 2 - invencion prohibida" in v4
    # el ejemplo 1 sigue EXPANDIENDO, solo que con corchetes en vez de preguntas
    assert "[dias por semana disponibles]" in v4


def test_v4_deriva_de_v2_por_las_cuatro_anclas():
    """v4 se construye con .replace() sobre literales de v2. Si un ancla se
    perdiera (por un retoque de v2, o por una copia mal hecha), el .replace()
    no haria nada y v4 quedaria IGUAL a v2 -- o sea el bug entero de vuelta, en
    silencio. Esto es lo que lo caza. Mismo patron que
    test_v3_anade_las_dos_formas_que_le_faltaban_a_v2."""
    for ancla in (mp._ANCLA_V4_OBLIGATORIO_3, mp._ANCLA_V4_EJEMPLO_1,
                  mp._ANCLA_V4_PROHIBIDO, mp._ANCLA_V4_TERCERA_PERSONA):
        assert ancla in mp._SYSTEM_V2, "ancla perdida: {!r}".format(ancla[:60])
    # las tres que SUSTITUYEN desaparecen de v4...
    for ancla in (mp._ANCLA_V4_OBLIGATORIO_3, mp._ANCLA_V4_EJEMPLO_1,
                  mp._ANCLA_V4_TERCERA_PERSONA):
        assert ancla not in mp._SYSTEM_V4
    # ...y la de PROHIBIDO es una INSERCION: la linea ancla sigue viva, con la
    # prohibicion nueva justo delante.
    assert mp._SYSTEM_V4.index("Terminar el prompt con una lista de "
                               "preguntas") < mp._SYSTEM_V4.index(
        mp._ANCLA_V4_PROHIBIDO)
    assert mp._SYSTEM_V4 != mp._SYSTEM_V2
    # v4 y v3 son dos derivaciones INDEPENDIENTES de v2, no una cadena
    assert mp._SYSTEM_V4 != mp._SYSTEM_V3
    assert "EJEMPLO 3" not in mp._SYSTEM_V4


def test_v4_NO_es_el_default():
    """El default global sigue siendo el brazo MEDIDO. v4 solo es mejor que v2
    cuando alguien MAS pregunta (la encuesta); sin encuesta, un prompt sin
    preguntas y sin nadie que las haga pierde datos."""
    assert mp.VERSION_DEFECTO == "v2"
    assert mp.system_prompt() is mp._SYSTEM_V2
    assert mp.system_prompt("v4") is mp._SYSTEM_V4


# ------------------------------------------------------------- version_para

def test_version_para_sin_encuestas_es_v2():
    assert mp.version_para("off") == "v2"
    assert mp.version_para("") == "v2"
    assert mp.version_para(None) == "v2"


def test_version_para_con_encuestas_activas_es_v4():
    assert mp.version_para("auto") == "v4"


def test_version_para_encuesta_previa_gana_al_estado():
    """Aunque las encuestas esten 'off' como politica, si ESTE texto ya viene
    enriquecido por una encuesta contestada, meterle preguntas dentro es
    pedirle al dueno dos veces lo mismo."""
    assert mp.version_para("off", encuesta_previa=True) == "v4"


def test_version_para_el_estilo_del_dueno_siempre_gana():
    """La clave de config 'mejorar_prompt_estilo' / COGNIA_MEJORA_PROMPT es una
    eleccion EXPLICITA: si el dueno pidio v2, no se le sirve v4 por detras."""
    assert mp.version_para("auto", estilo="v2") == "v2"
    assert mp.version_para("auto", encuesta_previa=True, estilo="v1") == "v1"
    assert mp.version_para("off", estilo="V3 ") == "v3"


def test_version_para_estilo_desconocido_no_pisa_la_eleccion():
    """Un COGNIA_MEJORA_PROMPT mal escrito no puede devolver el bug por la
    puerta de atras: aqui se ignora (y lo grita _resolver_version por su
    lado, que es quien tiene el aviso)."""
    assert mp.version_para("auto", estilo="v9") == "v4"
    assert mp.version_para("off", estilo="basura") == "v2"


def test_version_para_devuelve_siempre_una_version_registrada():
    for estado in ("off", "auto", "", None, "AUTO"):
        for previa in (True, False):
            elegida = mp.version_para(estado, encuesta_previa=previa)
            assert elegida in mp.VERSIONES_SYSTEM


# ------------------------------------------------- preguntas_al_usuario (5.5)

def test_preguntas_al_usuario_cuenta_interrogaciones_y_pedidos():
    salida = ("Crea una pagina web para mi. Antes de escribir nada, "
              "preguntame para que va a servir. Que tecnologia uso? "
              "Que secciones tiene?")
    assert mp.preguntas_al_usuario(salida) == 3


def test_preguntas_al_usuario_una_sola_marca_no_alcanza_el_umbral():
    """EJEMPLO 3 de v3 y el caso 'organizame' medido en el A/B: una
    reformulacion LEGITIMA que pide datos sin soltar la accion. Cuenta 1, y el
    umbral de rechazo es 2 justamente para no tirarla."""
    salida = ("Organiza mi escritorio. Antes de mover nada, preguntame si "
              "hablo del escritorio fisico o del de la computadora y con que "
              "criterio quiero agruparlo.")
    assert mp.preguntas_al_usuario(salida) == 1
    assert mp.preguntas_al_usuario(salida) < mp.MIN_PREGUNTAS_PARA_RECHAZAR


def test_preguntas_al_usuario_ignora_lo_que_no_es_una_pregunta():
    # 'pregunta' como sustantivo, y un '?' dentro de una URL con query.
    assert mp.preguntas_al_usuario("Responde la pregunta de investigacion "
                                   "usando http://x/y?a=1&b=2 como fuente") == 0
    assert mp.preguntas_al_usuario("") == 0
    assert mp.preguntas_al_usuario(None) == 0


def test_preguntas_al_usuario_cuenta_dos_verbos_distintos():
    assert mp.preguntas_al_usuario("Decime el plazo y aclarame el alcance") == 2


# ------------------------------------ sanear_salida(encuesta_previa=...) (5.5)

_CON_PREGUNTAS = ("Crea una pagina web para mi negocio. Antes de escribir "
                  "nada, preguntame para que va a servir. Que tecnologia "
                  "prefiero? Devuelve el codigo listo para abrir.")


def test_sanear_por_defecto_acepta_las_preguntas_embebidas():
    """El default NO cambia: sin encuesta, pedir datos dentro del prompt es el
    comportamiento correcto y medido de v2. Este test es el anticuerpo de que
    el arreglo no se cuela en el camino de siempre."""
    texto, motivo = mp.sanear_salida(_CON_PREGUNTAS, "hazme una web")
    assert motivo == "ok"
    texto2, motivo2 = mp.sanear_salida(_CON_PREGUNTAS, "hazme una web",
                                       encuesta_previa=False)
    assert (texto2, motivo2) == (texto, motivo)


def test_sanear_con_encuesta_previa_rechaza_las_preguntas():
    """La red determinista: si la encuesta YA pregunto en el selector y el
    modelo devuelve preguntas igual, el dueno tendria que contestar lo mismo
    dos veces. Es EL bug reportado, y esta es la unica defensa que aguanta si
    el modelo ignora el system v4."""
    _texto, motivo = mp.sanear_salida(_CON_PREGUNTAS, "hazme una web",
                                      encuesta_previa=True)
    assert motivo.startswith("mejora descartada")
    assert "la encuesta ya pregunto" in motivo
    # el motivo trae la CIFRA: sin ella no se puede recalibrar el umbral
    assert mp.preguntas_al_usuario(_CON_PREGUNTAS) == 2
    assert "2 preguntas" in motivo


def test_sanear_con_encuesta_previa_acepta_una_sola_pregunta():
    """Umbral 2, no 1 (riesgo 17 del plan): una mejora con un solo 'preguntame'
    sigue pasando, con encuesta previa o sin ella."""
    salida = ("Organiza mi escritorio agrupando lo que hay encima. Antes de "
              "mover nada, preguntame con que criterio quiero agruparlo, y "
              "dejame despues una lista de lo que moviste.")
    _texto, motivo = mp.sanear_salida(salida, "ordename el escritorio de casa",
                                      encuesta_previa=True)
    assert motivo == "ok"


def test_mejorar_pasa_encuesta_previa_al_saneador():
    """El parametro llega de punta a punta: si se quedara en la firma sin
    cablearse, todo lo de arriba seria decoracion."""
    enriquecido = ("hazme una pagina web\n\nDetalles que el usuario aclaro:\n"
                   "- Para que va a servir: vender pan")

    def _fake(_prompt, _system):
        return _CON_PREGUNTAS

    con = mp.mejorar(enriquecido, generar_fn=_fake, encuesta_previa=True)
    assert con.ok is False
    assert "la encuesta ya pregunto" in con.motivo
    # y lo que se envia es el texto ENRIQUECIDO, no el crudo: las respuestas
    # de la encuesta no se pierden porque la reformulacion se descarte.
    assert con.texto == enriquecido

    sin = mp.mejorar(enriquecido, generar_fn=_fake)
    assert sin.ok is True and sin.texto == _CON_PREGUNTAS


def test_mejorar_sirve_la_version_que_elige_version_para():
    """El cableado previsto de punta a punta: version_para() decide y
    mejorar() la sirve, sin que el CLI tenga que nombrar 'v4' a mano."""
    visto = {}

    def _fake(_prompt, system):
        visto["system"] = system
        return ("Arma la pagina de mi panaderia con [secciones] y [paleta de "
                "colores], y avisame cuando este publicada.")

    mp.mejorar("hazme una pagina web", generar_fn=_fake,
               version=mp.version_para("auto", encuesta_previa=True))
    assert visto["system"] is mp._SYSTEM_V4

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
