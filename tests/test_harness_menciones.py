# -*- coding: utf-8 -*-
"""@-menciones de ficheros: la via para meter contexto exacto sin copiar y pegar.

Regresion del 2026-08-12: antes de `cognia/harness/menciones.py` un '@ruta' en
el turno del usuario no significaba nada (grep de '@' como mencion: cero), asi
que este fichero entero falla sin el modulo. Se cubren las tres decisiones que
se pueden romper en silencio: la regla email/decorador, el troceo por el medio
con su presupuesto, y el orden del autocompletado.
"""
import pathlib

from cognia.harness.menciones import completar_rutas, detectar, expandir


# ---------------------------------------------------------------- detectar

def test_detecta_mencion_simple_con_offsets():
    texto = "arregla el bug de @cognia/agent/loop.py porfa"
    ms = detectar(texto)
    assert len(ms) == 1
    assert ms[0]["ruta"] == "cognia/agent/loop.py"
    assert ms[0]["token"] == "@cognia/agent/loop.py"
    assert texto[ms[0]["inicio"]:ms[0]["fin"]] == ms[0]["token"]


def test_detecta_ruta_con_espacios_entre_comillas():
    ms = detectar('mira @"src/mi fichero.py" y decime')
    assert [m["ruta"] for m in ms] == ["src/mi fichero.py"]
    ms1 = detectar("mira @'src/otro fichero.py'")
    assert [m["ruta"] for m in ms1] == ["src/otro fichero.py"]


def test_ignora_emails():
    """El @ de un email viene pegado a una letra: no abre token."""
    assert detectar("escribile a anthuangod@gmail.com y avisame") == []
    assert detectar("user.name@sub.dominio.org") == []


def test_ignora_decoradores_a_principio_de_linea():
    codigo = "@dataclass\nclass X:\n    @app.route(\"/x\")\n    def f(self): ...\n"
    assert detectar(codigo) == []


def test_decorador_solo_si_arranca_la_linea_y_no_tiene_separador():
    # A mitad de frase SI es mencion, aunque parezca un decorador.
    assert [m["ruta"] for m in detectar("mira @app.route")] == ["app.route"]
    # A principio de linea, con separador, tambien.
    assert [m["ruta"] for m in detectar("@./setup.py")] == ["./setup.py"]
    # Y la forma con comillas nunca se toma por decorador.
    assert [m["ruta"] for m in detectar('@"dataclass"')] == ["dataclass"]


def test_arrancar_el_turno_con_un_fichero_es_mencion():
    """El caso mas comun del usuario: '@loop.py que hace esto'. No es decorador."""
    assert [m["ruta"] for m in detectar("@loop.py que hace esto")] == ["loop.py"]
    assert [m["ruta"] for m in detectar("@README.md")] == ["README.md"]


def test_el_disco_desempata_los_tokens_sin_punto(tmp_path):
    """'@src' a principio de linea: sin raiz es ambiguo, con raiz manda el disco."""
    (tmp_path / "src").mkdir()
    assert detectar("@src arreglalo") == []
    assert [m["ruta"] for m in detectar("@src arreglalo", tmp_path)] == ["src"]
    # Un decorador de verdad no aparece en disco: sigue descartado.
    assert detectar("@dataclass", tmp_path) == []


def test_no_se_come_la_puntuacion_final():
    ms = detectar("revisa @cognia/cli.py, y despues @README.md.")
    assert [m["ruta"] for m in ms] == ["cognia/cli.py", "README.md"]


def test_el_directorio_actual_y_el_padre_sobreviven_al_rstrip():
    """Regresion: '@..' se quedaba en '' al quitar la puntuacion final y se perdia."""
    assert [m["ruta"] for m in detectar("mira @.. y @.")] == ["..", "."]
    assert detectar("y luego @...") == []       # eso ya es puntuacion, no ruta


def test_texto_sin_menciones():
    assert detectar("") == []
    assert detectar("no hay nada de nada aca") == []


# ---------------------------------------------------------------- expandir

def test_expandir_anexa_el_bloque_y_deja_la_mencion(tmp_path):
    # newline="": en Windows write_text convierte \n en \r\n y el modulo
    # devuelve el fichero TAL CUAL (byte a byte), que es lo correcto.
    (tmp_path / "hola.py").write_text("print('hola')\n", encoding="utf-8",
                                      newline="")
    texto, adjuntos, avisos = expandir("mira @hola.py", tmp_path)

    assert "mira @hola.py" in texto
    assert "--- @hola.py ---\nprint('hola')" in texto
    assert avisos == []
    assert len(adjuntos) == 1
    assert adjuntos[0]["tipo"] == "fichero"
    assert adjuntos[0]["contenido"] == "print('hola')\n"


def test_expandir_no_repite_la_misma_ruta(tmp_path):
    (tmp_path / "a.txt").write_text("uno\n", encoding="utf-8")
    texto, adjuntos, _ = expandir("@a.txt y otra vez @a.txt", tmp_path)
    assert texto.count("--- @a.txt ---") == 1
    assert len(adjuntos) == 1


def test_fichero_inexistente_avisa_y_no_rompe(tmp_path):
    texto, adjuntos, avisos = expandir("mira @no_esta.py", tmp_path)
    assert texto == "mira @no_esta.py"          # sin bloques, texto intacto
    assert adjuntos == []
    assert avisos == ["no existe: @no_esta.py"]


def test_directorio_anexa_listado_no_contenido(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    (d / "uno.py").write_text("secreto_que_no_debe_salir = 1\n", encoding="utf-8")
    (d / "dos.py").write_text("x = 2\n", encoding="utf-8")
    (d / "__pycache__").mkdir()

    texto, adjuntos, avisos = expandir("@src", tmp_path)
    assert adjuntos[0]["tipo"] == "directorio"
    assert "[directorio] 2 entradas" in texto
    assert "uno.py" in texto and "dos.py" in texto
    assert "secreto_que_no_debe_salir" not in texto
    assert "__pycache__" not in texto
    assert avisos == []


def test_trunca_por_el_medio_y_dice_cuantas_lineas_omitio(tmp_path):
    lineas = [f"linea {i:04d}" for i in range(2000)]
    (tmp_path / "largo.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    texto, adjuntos, avisos = expandir("@largo.txt", tmp_path,
                                       max_bytes_por_fichero=1024)
    cuerpo = adjuntos[0]["contenido"]
    omitidas = adjuntos[0]["lineas_omitidas"]

    assert "linea 0000" in cuerpo                  # queda la cabeza
    assert "linea 1999" in cuerpo                  # queda la cola
    assert "linea 1000" not in cuerpo              # se fue el medio
    assert f"... [{omitidas} lineas omitidas] ..." in cuerpo
    assert 0 < omitidas < 2000
    assert len(cuerpo.encode("utf-8")) < 2048      # respeta el presupuesto
    assert any("truncado por el medio" in a for a in avisos)
    assert "--- @largo.txt ---" in texto


def test_crlf_no_duplica_contenido_ni_omite_lineas_negativas(tmp_path):
    """Regresion: con CRLF (lo normal en Windows) cabeza y cola se solapaban.

    Al reunir con "\\n", cada linea pesa 1 byte MENOS que en disco, asi que la
    cola podia remontar hasta dentro de la cabeza: contenido DUPLICADO y
    `lineas_omitidas` NEGATIVO (-112 con estos mismos numeros antes del fix),
    ademas de pasarse del presupuesto que la propia funcion promete.
    """
    n = 400
    crudo = b"".join(b"linea%03d\r\n" % i for i in range(n))
    (tmp_path / "win.txt").write_bytes(crudo)

    _, adjuntos, avisos = expandir("@win.txt", tmp_path,
                                   max_bytes_por_fichero=1024)
    cuerpo = adjuntos[0]["contenido"]

    assert adjuntos[0]["lineas_omitidas"] >= 0
    assert len(cuerpo.encode("utf-8")) <= 1024        # el presupuesto es real
    for i in range(n):                                # ni una linea repetida
        assert cuerpo.count("linea%03d" % i) <= 1
    if adjuntos[0]["lineas_omitidas"] == 0:
        assert not any("truncado" in a for a in avisos)


def test_el_troceo_respeta_el_presupuesto_con_la_marca_incluida(tmp_path):
    """La marca '... [N lineas omitidas] ...' tambien gasta bytes del presupuesto."""
    lineas = [f"linea {i:04d}" for i in range(2000)]
    (tmp_path / "largo.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    _, adjuntos, _ = expandir("@largo.txt", tmp_path, max_bytes_por_fichero=1024)
    assert len(adjuntos[0]["contenido"].encode("utf-8")) <= 1024


def test_bytes_invalidos_no_inflan_por_encima_del_presupuesto(tmp_path):
    """errors='replace' vuelve cada byte malo en 3 bytes utf-8: hay que medir el TEXTO."""
    crudo = "camion de \xf1andu\n".encode("latin-1") * 300      # 4800 bytes en disco
    (tmp_path / "l1.txt").write_bytes(crudo)
    assert len(crudo) < 5000

    _, adjuntos, _ = expandir("@l1.txt", tmp_path, max_bytes_por_fichero=5000)
    assert adjuntos[0]["tipo"] == "fichero"
    assert len(adjuntos[0]["contenido"].encode("utf-8")) <= 5000


def test_no_repite_el_mismo_fichero_escrito_de_otra_forma(tmp_path):
    """Regresion: se deduplicaba por el texto tecleado, no por el destino real."""
    (tmp_path / "a.txt").write_text("uno\n", encoding="utf-8")
    texto, adjuntos, _ = expandir("@a.txt y tambien @./a.txt", tmp_path)
    assert len(adjuntos) == 1
    assert texto.count("--- @") == 1


def test_una_mencion_con_home_imposible_avisa_y_no_lanza(tmp_path, monkeypatch):
    """Regresion: `@~usuario_inexistente/x` levanta RuntimeError en POSIX.

    `expandir` promete que ninguna mencion mala tumba el turno; ese RuntimeError
    no es OSError y se escapaba del `except`. Se simula para que el test valga
    tambien en Windows (donde expanduser no llega a fallar).
    """
    def revienta(self):
        raise RuntimeError("Could not determine home directory.")
    monkeypatch.setattr(pathlib.Path, "expanduser", revienta)

    texto, adjuntos, avisos = expandir("mira @~nadie/x.py", tmp_path)
    assert adjuntos == []
    assert avisos == ["no existe: @~nadie/x.py"]
    assert texto == "mira @~nadie/x.py"


def test_gitignore_ilegible_no_tumba_el_autocompletado(tmp_path, monkeypatch):
    _arbol(tmp_path)
    real = pathlib.Path.read_text

    def revienta(self, *a, **k):
        if self.name == ".gitignore":
            raise PermissionError("no se puede leer")
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "read_text", revienta)

    assert "main.py" in completar_rutas("", tmp_path, limite=100)


def test_binario_solo_nombre_y_tamano(tmp_path):
    crudo = b"\x89PNG\r\n\x1a\n\x00\x00" + b"\xff" * 500
    (tmp_path / "logo.png").write_bytes(crudo)
    texto, adjuntos, _ = expandir("@logo.png", tmp_path)
    assert adjuntos[0]["tipo"] == "binario"
    assert adjuntos[0]["contenido"] == f"[binario] logo.png — {len(crudo)} bytes"
    assert "\xff" not in texto


def test_max_total_corta_y_avisa(tmp_path):
    (tmp_path / "a.txt").write_text("a" * 2000, encoding="utf-8")
    (tmp_path / "b.txt").write_text("b" * 2000, encoding="utf-8")
    texto, adjuntos, avisos = expandir("@a.txt @b.txt", tmp_path, max_total=2500)

    assert [a["ruta"] for a in adjuntos] == ["a.txt"]
    assert "--- @b.txt ---" not in texto
    assert any("presupuesto de 2500 bytes agotado" in a for a in avisos)


# ---------------------------------------------------------- completar_rutas

def _arbol(raiz):
    """Arbol chico con .gitignore, venv y basura, que es el caso real."""
    (raiz / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    (raiz / "main.py").write_text("", encoding="utf-8")
    (raiz / "mapa.py").write_text("", encoding="utf-8")
    (raiz / "notas.log").write_text("", encoding="utf-8")
    (raiz / "src").mkdir()
    (raiz / "src" / "mapa_hondo.py").write_text("", encoding="utf-8")
    (raiz / "src" / "pack.md").write_text("", encoding="utf-8")
    (raiz / "build").mkdir()
    (raiz / "build" / "mapa_build.py").write_text("", encoding="utf-8")
    (raiz / "venv312").mkdir()
    (raiz / "venv312" / "mapa_venv.py").write_text("", encoding="utf-8")
    (raiz / "__pycache__").mkdir()
    (raiz / "__pycache__" / "mapa.pyc").write_text("", encoding="utf-8")


def test_completar_ordena_por_prefijo_profundidad_y_alfabeto(tmp_path):
    _arbol(tmp_path)
    assert completar_rutas("ma", tmp_path) == [
        "main.py", "mapa.py", "src/mapa_hondo.py"]


def test_completar_pone_primero_el_que_empieza_aunque_este_mas_hondo(tmp_path):
    _arbol(tmp_path)
    # "pack.md" (hondo) empieza por 'pa'; los otros dos solo lo contienen y van
    # detras, ya entre ellos por profundidad.
    assert completar_rutas("pa", tmp_path) == [
        "src/pack.md", "mapa.py", "src/mapa_hondo.py"]


def test_completar_respeta_gitignore_y_excluidos_siempre(tmp_path):
    _arbol(tmp_path)
    todos = completar_rutas("", tmp_path, limite=100)
    assert "notas.log" not in todos                    # .gitignore: *.log
    assert not any(r.startswith("build") for r in todos)   # .gitignore: build/
    assert not any(r.startswith("venv312") for r in todos)
    assert not any("__pycache__" in r for r in todos)
    assert "main.py" in todos and "src/" in todos


def test_completar_dentro_de_un_directorio(tmp_path):
    _arbol(tmp_path)
    assert completar_rutas("src/", tmp_path) == ["src/mapa_hondo.py", "src/pack.md"]
    assert completar_rutas("src\\ma", tmp_path) == ["src/mapa_hondo.py"]
    assert completar_rutas("sr", tmp_path) == ["src/"]


def test_completar_limite_y_raiz_inexistente(tmp_path):
    _arbol(tmp_path)
    assert len(completar_rutas("", tmp_path, limite=2)) == 2
    assert completar_rutas("ma", tmp_path / "no_existe") == []
