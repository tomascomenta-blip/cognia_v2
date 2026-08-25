"""
Tests de cognia/harness/permisos_reglas.py — reglas de permiso persistentes.

Fijan lo que el modulo promete y lo que hoy NO existe en console/permissions.py:
casado por patron con semantica de barras, precedencia explicita
(denegar > preguntar > permitir, y a igual efecto gana el mas especifico),
persistencia atomica en .cognia/permisos.json tolerante a JSON corrupto, y la
guardia que impide que "permitir siempre" generalice un comando destructivo.
"""

import json
import os

import pytest

from cognia.harness import permisos_reglas as PR


# ── casar / normalizacion ─────────────────────────────────────────────────────

def test_casar_prefijo_y_herramienta_distinta():
    assert PR.casar("ejecutar(git status*)", "ejecutar", "git status")
    assert PR.casar("ejecutar(git status*)", "ejecutar", "git status --short")
    assert not PR.casar("ejecutar(git status*)", "ejecutar", "git push")
    # la herramienta forma parte del patron: mismo texto, otra tool -> no casa
    assert not PR.casar("ejecutar(git status*)", "escribir_archivo", "git status")


def test_casar_herramienta_a_secas_casa_cualquier_arg():
    assert PR.casar("borrar_archivo", "borrar_archivo", "loquesea/x.txt")
    assert PR.casar("borrar_archivo", "borrar_archivo", "")


def test_glob_estrella_no_cruza_barras_pero_doble_si():
    assert PR.casar("escribir_archivo(src/**)", "escribir_archivo", "src/a.py")
    assert PR.casar("escribir_archivo(src/**)", "escribir_archivo", "src/uno/dos/a.py")
    assert PR.casar("escribir_archivo(src/*)", "escribir_archivo", "src/a.py")
    assert not PR.casar("escribir_archivo(src/*)", "escribir_archivo", "src/uno/a.py")
    # '**/' vale por cero o mas directorios
    assert PR.casar("leer_archivo(**/*.py)", "leer_archivo", "a.py")
    assert PR.casar("leer_archivo(**/*.py)", "leer_archivo", "cognia/harness/a.py")
    assert not PR.casar("leer_archivo(**/*.py)", "leer_archivo", "cognia/harness/a.txt")


def test_normalizacion_barras_y_espacios():
    assert PR.normalizar("src\\app\\a.py") == "src/app/a.py"
    assert PR.normalizar("  git   status\n --short ") == "git status --short"
    # una ruta de Windows casa con el mismo glob que la POSIX
    assert PR.casar("escribir_archivo(src/**)", "escribir_archivo", "src\\app\\a.py")
    assert PR.casar("ejecutar(git status*)", "ejecutar", "git    status")


def test_casar_es_sensible_a_mayusculas_en_todos_los_so():
    # fnmatch.fnmatch normalizaria la caja en Windows; aqui no.
    assert not PR.casar("ejecutar(git*)", "ejecutar", "GIT status")


def test_patron_mal_formado_no_casa_nada():
    assert not PR.casar("", "ejecutar", "git status")
    assert not PR.casar("(git*)", "ejecutar", "git status")


# ── precedencia ───────────────────────────────────────────────────────────────

def test_sin_reglas_pregunta():
    assert PR.decidir("ejecutar", "git status", []) == ("preguntar", None)


def test_denegar_gana_a_permitir_aunque_sea_menos_especifico():
    reglas = [
        {"efecto": "permitir", "patron": "ejecutar(git push --force*)"},
        {"efecto": "denegar", "patron": "ejecutar(git*)"},
    ]
    efecto, regla = PR.decidir("ejecutar", "git push --force origin main", reglas)
    assert efecto == "denegar"
    assert regla["patron"] == "ejecutar(git*)"


def test_a_igual_efecto_gana_el_mas_especifico():
    reglas = [
        {"efecto": "permitir", "patron": "ejecutar"},
        {"efecto": "permitir", "patron": "ejecutar(git*)"},
        {"efecto": "permitir", "patron": "ejecutar(git status*)"},
    ]
    efecto, regla = PR.decidir("ejecutar", "git status", reglas)
    assert efecto == "permitir"
    assert regla["patron"] == "ejecutar(git status*)"
    assert PR.especificidad("ejecutar") == -1 < PR.especificidad("ejecutar(git*)")


def test_preguntar_ancho_vence_a_permitir_estrecho():
    # trade-off declarado: un freno no puede desactivarse con un patron mas largo
    reglas = [
        {"efecto": "permitir", "patron": "ejecutar(git status*)"},
        {"efecto": "preguntar", "patron": "ejecutar"},
    ]
    assert PR.decidir("ejecutar", "git status", reglas)[0] == "preguntar"


def test_decidir_acepta_tuplas_e_ignora_basura():
    reglas = [("permitir", "ejecutar(git*)"), {"efecto": "invento", "patron": "x"},
              "no soy una regla", {"patron": "sin efecto"}]
    assert PR.decidir("ejecutar", "git log", reglas)[0] == "permitir"


# ── persistencia ──────────────────────────────────────────────────────────────

def test_guardar_y_cargar_ida_y_vuelta(tmp_path):
    reglas = [{"efecto": "permitir", "patron": "ejecutar(git*)"},
              {"efecto": "denegar", "patron": "borrar_archivo"}]
    ruta = PR.guardar(tmp_path, reglas)
    assert ruta == tmp_path / ".cognia" / "permisos.json"
    assert ruta.exists()
    assert PR.cargar(tmp_path) == reglas
    # escritura atomica: no queda el temporal tirado
    assert list(ruta.parent.glob("*.tmp")) == []


def test_guardar_deduplica_y_conserva_orden(tmp_path):
    PR.guardar(tmp_path, [("permitir", "ejecutar(git*)"),
                          ("permitir", "ejecutar(git*)"),
                          ("denegar", "ejecutar(rm*)")])
    assert [r["patron"] for r in PR.cargar(tmp_path)] == ["ejecutar(git*)", "ejecutar(rm*)"]


def test_cargar_sin_fichero_devuelve_vacio_y_no_crea(tmp_path):
    assert PR.cargar(tmp_path) == []
    assert not PR.ruta_reglas(tmp_path).exists()
    assert PR.cargar(tmp_path, crear=True) == []
    assert PR.ruta_reglas(tmp_path).exists()


def test_cargar_json_corrupto_no_revienta_y_avisa(tmp_path):
    ruta = PR.ruta_reglas(tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("{esto no es json", encoding="utf-8")

    from cognia.ux import events as ev
    vistos = []

    def _sonda(e):
        if isinstance(e, ev.Degradado):
            vistos.append(e)

    ev.suscribir(_sonda)
    try:
        assert PR.cargar(tmp_path) == []
    finally:
        ev.desuscribir(_sonda)
    assert any("permisos_reglas" in getattr(e, "donde", "") for e in vistos)
    # y sin reglas se vuelve al lado seguro
    assert PR.decidir("ejecutar", "git status", PR.cargar(tmp_path)) == ("preguntar", None)


def test_cargar_ignora_reglas_invalidas_del_fichero(tmp_path):
    ruta = PR.ruta_reglas(tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"version": 1, "reglas": [
        {"efecto": "permitir", "patron": "ejecutar(git*)"},
        {"efecto": "borrar_todo", "patron": "ejecutar(*)"},
    ]}), encoding="utf-8")
    assert PR.cargar(tmp_path) == [{"efecto": "permitir", "patron": "ejecutar(git*)"}]


# ── recordar / generalizacion ─────────────────────────────────────────────────

def test_recordar_comando_generaliza_por_primer_token(tmp_path):
    patron = PR.recordar(tmp_path, "permitir", "ejecutar", "git status --short")
    assert patron == "ejecutar(git*)"
    reglas = PR.cargar(tmp_path)
    assert PR.decidir("ejecutar", "git status", reglas) == ("permitir", reglas[0])
    assert PR.decidir("ejecutar", "npm test", reglas)[0] == "preguntar"


def test_recordar_fichero_generaliza_al_directorio(tmp_path):
    patron = PR.recordar(tmp_path, "permitir", "escribir_archivo",
                         "src\\app\\a.py | contenido nuevo")
    assert patron == "escribir_archivo(src/app/**)"
    reglas = PR.cargar(tmp_path)
    assert PR.decidir("escribir_archivo", "src/app/b.py | x", reglas)[0] == "permitir"
    assert PR.decidir("escribir_archivo", "otro/b.py | x", reglas)[0] == "preguntar"


def test_recordar_fichero_en_la_raiz_no_abre_el_subarbol(tmp_path):
    assert PR.recordar(tmp_path, "permitir", "escribir_archivo", "notas.md | x") \
        == "escribir_archivo(*)"
    reglas = PR.cargar(tmp_path)
    assert PR.decidir("escribir_archivo", "otras.md | x", reglas)[0] == "permitir"
    assert PR.decidir("escribir_archivo", "src/a.py | x", reglas)[0] == "preguntar"


def test_recordar_reemplaza_la_regla_del_mismo_patron(tmp_path):
    PR.recordar(tmp_path, "permitir", "ejecutar", "git status")
    PR.recordar(tmp_path, "denegar", "ejecutar", "git log")   # mismo patron git*
    reglas = PR.cargar(tmp_path)
    assert reglas == [{"efecto": "denegar", "patron": "ejecutar(git*)"}]


def test_recordar_efecto_invalido():
    with pytest.raises(ValueError):
        PR.recordar(".", "quiza", "ejecutar", "git status")


# ── guardia de destructivos ───────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "rm -rf build", "del /q x.txt", "format C:", "shutdown /s /t 0",
    "mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/sda", "taskkill /F /IM x.exe",
    "reg delete HKCU\\Software\\X /f", "Remove-Item -Recurse build",
    "npm run build && rm -rf dist", "C:\\Windows\\System32\\shutdown.exe -r",
])
def test_es_destructivo(cmd):
    assert PR.es_destructivo("ejecutar", cmd), cmd


@pytest.mark.parametrize("cmd", [
    "git status", "npm test", "reg query HKCU\\Software\\X",
    "python -m pytest tests/ -q", "/usr/bin/ls -la",
])
def test_no_es_destructivo(cmd):
    assert not PR.es_destructivo("ejecutar", cmd), cmd


def test_permitir_siempre_no_generaliza_un_destructivo(tmp_path):
    patron = PR.recordar(tmp_path, "permitir", "ejecutar", "rm -rf build")
    assert patron == "ejecutar(rm -rf build)"          # literal, sin comodin
    reglas = PR.cargar(tmp_path)
    assert reglas == [{"efecto": "preguntar", "patron": "ejecutar(rm -rf build)"}]
    # el si de hoy no firma el borrado de manana: sigue preguntando
    assert PR.decidir("ejecutar", "rm -rf build", reglas)[0] == "preguntar"
    assert PR.decidir("ejecutar", "rm -rf /", reglas)[0] == "preguntar"


def test_permitir_siempre_no_generaliza_un_comando_envuelto(tmp_path):
    patron = PR.recordar(tmp_path, "permitir", "ejecutar", "sudo apt install cosa")
    assert patron == "ejecutar(sudo apt install cosa)"
    assert PR.cargar(tmp_path)[0]["efecto"] == "preguntar"
    # y el envoltorio no esconde al destructivo
    assert PR.es_destructivo("ejecutar", "sudo rm -rf /")
    assert PR.es_destructivo("ejecutar", "cmd /c del x.txt")


def test_herramienta_destructiva_nunca_se_generaliza(tmp_path):
    patron = PR.recordar(tmp_path, "permitir", "borrar_archivo", "src/app/a.py")
    assert patron == "borrar_archivo(src/app/a.py)"
    assert PR.cargar(tmp_path)[0]["efecto"] == "preguntar"


def test_denegar_destructivo_si_se_puede_guardar(tmp_path):
    # la degradacion a "preguntar" es solo para "permitir": denegar se respeta
    PR.recordar(tmp_path, "denegar", "ejecutar", "rm -rf build")
    reglas = PR.cargar(tmp_path)
    assert reglas == [{"efecto": "denegar", "patron": "ejecutar(rm -rf build)"}]
    assert PR.decidir("ejecutar", "rm -rf build", reglas)[0] == "denegar"


# ── REGRESION: el glob casa contra la RUTA, no contra el contenido pegado ─────
# El casado usaba la cadena entera "ruta | contenido": bastaba una '/' dentro del
# contenido para que un permiso YA concedido dejase de casar (el REPL volvia a
# preguntar: exactamente la fatiga que este modulo dice evitar).

def test_permiso_de_fichero_sobrevive_a_un_contenido_con_barras(tmp_path):
    PR.recordar(tmp_path, "permitir", "escribir_archivo", "notas.md | x")
    reglas = PR.cargar(tmp_path)
    assert PR.decidir("escribir_archivo", "notas.md | ver http://a/b", reglas)[0] == "permitir"
    assert PR.decidir("escribir_archivo", "otras.md | a/b/c", reglas)[0] == "permitir"
    assert PR.decidir("escribir_archivo", "src/a.py | x", reglas)[0] == "preguntar"


def test_casar_de_fichero_mira_la_ruta_no_el_contenido():
    assert PR.casar("leer_archivo(**/*.py)", "leer_archivo", "src/a.py | print('/')")
    # y el contenido no puede colar un fichero que esta fuera del glob
    assert not PR.casar("escribir_archivo(src/**)", "escribir_archivo", "otro/a.py | src/x")
    # en herramienta de comando NO se recorta: la tuberia es parte del comando
    assert PR.casar("ejecutar(cat*)", "ejecutar", "cat a | grep b")


# ── REGRESION: patron escrito a mano con barras de Windows ───────────────────

def test_patron_con_barras_de_windows_casa_igual():
    # el usuario edita .cognia/permisos.json en Windows y pega una ruta con '\':
    # antes no casaba NUNCA (y en silencio), porque solo se normalizaban los args
    assert PR.casar(r"escribir_archivo(src\app\**)", "escribir_archivo", "src/app/a.py")
    assert PR.casar(r"escribir_archivo(src\app\**)", "escribir_archivo", r"src\app\a.py")
    assert PR.especificidad(r"escribir_archivo(src\app\**)") \
        == PR.especificidad("escribir_archivo(src/app/**)")


# ── REGRESION: recordar no puede destruir el fichero del usuario ─────────────

def test_recordar_no_borra_un_permisos_json_que_no_supo_leer(tmp_path):
    ruta = PR.ruta_reglas(tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    original = ('{"version": 1, "reglas": ['
                '{"efecto": "denegar", "patron": "ejecutar(git push*)"},]}')   # coma de mas
    ruta.write_text(original, encoding="utf-8")
    PR.recordar(tmp_path, "permitir", "ejecutar", "git status")
    copias = [p for p in ruta.parent.iterdir() if p.name.startswith("permisos.json.corrupto")]
    assert copias, "el permisos.json del usuario (con su regla denegar) se perdio"
    assert copias[0].read_text(encoding="utf-8") == original


def test_recordar_no_descarta_en_silencio_una_regla_que_no_entiende(tmp_path):
    ruta = PR.ruta_reglas(tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"version": 1, "reglas": [
        {"efecto": "deny", "patron": "ejecutar(git push*)"}]})   # efecto en ingles
    ruta.write_text(original, encoding="utf-8")
    PR.recordar(tmp_path, "permitir", "ejecutar", "git status")
    copias = [p for p in ruta.parent.iterdir() if p.name.startswith("permisos.json.corrupto")]
    assert copias and copias[0].read_text(encoding="utf-8") == original


# ── REGRESION: agujeros de la guardia de destructivos ────────────────────────

@pytest.mark.parametrize("cmd", [
    'bash -c "rm -rf /"',            # comillas: el token era '"rm'
    "env FOO=bar rm -rf /",          # asignacion delante del comando real
    'cmd /c "del x.txt"',
    "git status\nrm -rf build",      # salto de linea: normalizar lo volvia un espacio
    "npm ci\r\nformat C:",
])
def test_es_destructivo_pese_a_comillas_asignaciones_y_saltos(cmd):
    assert PR.es_destructivo("ejecutar", cmd), cmd


def test_el_contenido_de_un_fichero_no_se_lee_como_linea_de_shell(tmp_path):
    args = "src/app/a.py | print('hola'); del cache  # limpia"
    assert not PR.es_destructivo("escribir_archivo", args)
    # y el patron guardado es la RUTA, no el fichero entero pegado dentro
    assert PR.recordar(tmp_path, "permitir", "escribir_archivo", args) \
        == "escribir_archivo(src/app/**)"
    assert PR.cargar(tmp_path)[0]["efecto"] == "permitir"
    # una herramienta de shell NO registrada se sigue analizando entera (fail-safe)
    assert PR.es_destructivo("run_shell", "rm -rf /")


# ── REGRESION: la escritura atomica que prometia el docstring ────────────────

def test_guardar_usa_un_temporal_distinto_en_cada_escritura(tmp_path, monkeypatch):
    # con un tmp de nombre FIJO, dos procesos a la vez escriben el mismo fichero
    # temporal y el JSON resultante puede quedar entrelazado (= corrupto)
    vistos = []
    real = os.replace
    monkeypatch.setattr(os, "replace",
                        lambda a, b: (vistos.append(str(a)), real(a, b))[1])
    PR.guardar(tmp_path, [("permitir", "ejecutar(a*)")])
    PR.guardar(tmp_path, [("permitir", "ejecutar(b*)")])
    assert len(set(vistos)) == 2, vistos


def test_guardar_fallido_no_deja_temporal_ni_toca_lo_anterior(tmp_path, monkeypatch):
    PR.guardar(tmp_path, [("denegar", "ejecutar(rm*)")])

    def rompe(a, b):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", rompe)
    with pytest.raises(OSError):
        PR.guardar(tmp_path, [("permitir", "ejecutar(git*)")])
    monkeypatch.undo()
    assert PR.cargar(tmp_path) == [{"efecto": "denegar", "patron": "ejecutar(rm*)"}]
    assert list(PR.ruta_reglas(tmp_path).parent.glob("*.tmp")) == []


def test_el_json_guardado_es_utf8_con_saltos_lf(tmp_path):
    PR.guardar(tmp_path, [("permitir", "escribir_archivo(src/ñandú/**)")])
    crudo = PR.ruta_reglas(tmp_path).read_bytes()
    assert b"\r\n" not in crudo            # estable entre SO y en git
    assert "ñandú".encode("utf-8") in crudo


# ── REGRESION: contrabando de comandos encadenados ───────────────────────────
# El patron casaba contra la linea ENTERA, asi que un permiso ancho arrastraba
# lo que viniera detras de '&&': con "permitir ejecutar(git*)" guardado,
# "git status && rm -rf build" se ejecutaba SIN preguntar, y un
# "denegar ejecutar(rm*)" escrito a mano no lo frenaba (medido).

@pytest.mark.parametrize("cmd", [
    "git status && rm -rf build",
    "git status; del x.txt",
    "git status\nrm -rf build",
    "git log | taskkill /F /IM x.exe",
])
def test_permiso_ancho_no_arrastra_un_destructivo_encadenado(cmd):
    reglas = [{"efecto": "permitir", "patron": "ejecutar(git*)"}]
    assert PR.decidir("ejecutar", cmd, reglas)[0] == "preguntar", cmd


def test_al_degradar_se_devuelve_la_regla_que_se_quedo_corta():
    # el REPL tiene que poder decir QUE permiso no alcanzaba
    reglas = [{"efecto": "permitir", "patron": "ejecutar(git*)"}]
    efecto, regla = PR.decidir("ejecutar", "git status && rm -rf build", reglas)
    assert efecto == "preguntar"
    assert regla["patron"] == "ejecutar(git*)"


def test_un_denegar_no_se_esquiva_poniendole_delante_algo_permitido():
    reglas = [{"efecto": "permitir", "patron": "ejecutar(git*)"},
              {"efecto": "denegar", "patron": "ejecutar(git push*)"}]
    efecto, regla = PR.decidir("ejecutar", "git status && git push origin main", reglas)
    assert efecto == "denegar"
    assert regla["patron"] == "ejecutar(git push*)"


def test_un_permitir_explicito_del_destructivo_si_cubre_su_segmento():
    # la guardia frena el contrabando, no la voluntad declarada del usuario
    reglas = [{"efecto": "permitir", "patron": "ejecutar(git*)"},
              {"efecto": "permitir", "patron": "ejecutar(rm*)"}]
    assert PR.decidir("ejecutar", "git status && rm -rf build", reglas)[0] == "permitir"
    assert PR.decidir("ejecutar", "rm -rf build", reglas)[0] == "permitir"


def test_una_tuberia_inocente_sigue_permitida():
    # un segmento SIN regla no estrecha nada: si lo hiciera, volveria la fatiga
    # de confirmaciones que este modulo existe para quitar
    reglas = [{"efecto": "permitir", "patron": "ejecutar(cat*)"}]
    assert PR.decidir("ejecutar", "cat a | grep b", reglas)[0] == "permitir"


def test_un_solo_segmento_decide_exactamente_como_antes(tmp_path):
    # rutas con '&' o llamadas de fichero: nada de troceo, nada de preguntas de mas
    reglas = [{"efecto": "permitir", "patron": "escribir_archivo(docs/**)"}]
    assert PR.decidir("escribir_archivo", "docs/q&a.md | x", reglas)[0] == "permitir"
    assert PR.decidir("escribir_archivo", "docs/a.md | rm -rf /", reglas)[0] == "permitir"


# ── REGRESION: el fichero de reglas no siempre es UTF-8 puro ─────────────────

def test_cargar_no_revienta_con_un_permisos_json_en_latin1(tmp_path):
    # `cargar` promete no tumbar el turno, pero UnicodeDecodeError NO es OSError
    # y se escapaba de los dos `except`: un fichero en latin-1 (o utf-16) hacia
    # explotar cada llamada al modulo.
    ruta = PR.ruta_reglas(tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(json.dumps(
        {"version": 1, "reglas": [{"efecto": "denegar", "patron": "escribir_archivo(ñ/**)"}]},
        ensure_ascii=False).encode("latin-1"))
    assert PR.cargar(tmp_path) == []                       # sin excepcion
    assert PR.decidir("ejecutar", "git status", PR.cargar(tmp_path)) == ("preguntar", None)
    # y lo que no se pudo leer se aparta, no se pisa
    PR.recordar(tmp_path, "permitir", "ejecutar", "git status")
    copias = [p for p in ruta.parent.iterdir() if p.name.startswith("permisos.json.corrupto")]
    assert copias, "el permisos.json en latin-1 del usuario se perdio"


def test_cargar_acepta_el_bom_que_escribe_powershell(tmp_path):
    # `Out-File -Encoding utf8` de PowerShell 5.1 antepone BOM; con encoding
    # "utf-8" json.loads lo rechazaba y las reglas `denegar` desaparecian
    ruta = PR.ruta_reglas(tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"\xef\xbb\xbf" + json.dumps(
        {"version": 1, "reglas": [{"efecto": "denegar", "patron": "ejecutar(git push*)"}]}
    ).encode("utf-8"))
    reglas = PR.cargar(tmp_path)
    assert reglas == [{"efecto": "denegar", "patron": "ejecutar(git push*)"}]
    assert PR.decidir("ejecutar", "git push --force", reglas)[0] == "denegar"


# ── shell_exec es una herramienta de COMANDO (revision adversarial 2026-08-25) ──

def test_shell_exec_casa_la_tuberia_entera():
    # 'shell_exec' es el action_kind del gate cli._confirmar_accion (reglas por
    # bot: permitir shell_exec(git status*)). Sin estar en
    # HERRAMIENTAS_DE_COMANDO el comando se trataba como RUTA y solo se miraba
    # lo anterior a ' | ': 'git status | rm -rf x' pasaba sin preguntar.
    assert "shell_exec" in PR.HERRAMIENTAS_DE_COMANDO
    reglas = [{"efecto": "permitir", "patron": "shell_exec(git status*)"},
              {"efecto": "denegar", "patron": "shell_exec(git push*)"}]
    assert PR.decidir("shell_exec", "git status", reglas) == ("permitir", reglas[0])
    assert PR.decidir("shell_exec", "git status --short", reglas)[0] == "permitir"
    for colado in ("git status | rm -rf C:/tmp/x", "git status && rm -rf x",
                   "git status; del x", "git status\nrm -rf build"):
        assert PR.decidir("shell_exec", colado, reglas)[0] != "permitir", colado
    assert PR.decidir("shell_exec", "git push --force", reglas)[0] == "denegar"
    assert PR.decidir("shell_exec", "git status | git push", reglas)[0] == "denegar"
