"""
Regresion de LA FRONTERA DE BYTES en cognia/agent/tools.py.

Los cuatro fallos que cubren estos tests estaban REPRODUCIDOS contra ficheros
reales el 2026-08-13, con este mismo venv (locale cp1252):

  (1) `ejecutar` devolvia al modelo "unsupported operand type(s) for +:
      'NoneType' and 'str'" + un traceback suelto en la consola, porque
      subprocess.run(text=True) sin encoding decodifica en el HILO LECTOR con el
      locale y ahi el UnicodeDecodeError no lanza: deja r.stdout=None.
  (2) `editar_archivo` sobre un latin-1 reescribia el fichero ENTERO con U+FFFD
      donde habia acentos, y contestaba "OK (1 bloque)".
  (3) `escribir_archivo` sobre un latin-1 existente NO escribia nada
      ("'utf-8' codec can't decode byte 0xf1") por culpa de la lectura previa,
      que solo alimenta el diff cosmetico.
  (4) cambiar UNA linea CRLF-izaba el fichero entero (write_text traduce \\n a
      os.linesep).
  (5) `buscar` no encontraba una palabra acentuada en un utf-8: falso negativo
      INVISIBLE (leia con el locale).
  (6) py_validar/json_validar reportaban "ERROR" de sintaxis ante lo que era un
      problema de CODIFICACION.

Regla de este fichero (regla del repo): se verifica en BYTES. Un assert sobre el
texto ya decodificado no habria visto ninguno de estos bugs.
"""

import subprocess
import sys

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T

# 'camión con acentuación' en latin-1: los 0xf3 son la evidencia que se persigue.
LATIN1 = "def f():\n    return 'camión con acentuación'\n".encode("latin-1")
FFFD = b"\xef\xbf\xbd"          # U+FFFD en utf-8: la marca de la perdida


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Workspace del agente = tmp_path (mismo patron que test_agent_tools)."""
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("COGNIA_SENTINEL", "0")   # el sentinel no es lo que se mide
    return tmp_path


def _bloque(viejo, nuevo):
    return f"<<<<<<< SEARCH\n{viejo}\n=======\n{nuevo}\n>>>>>>> REPLACE"


# ── (1) subprocess: bytes que el locale no sabe decodificar ────────────

def test_ejecutar_no_devuelve_nonetype_con_bytes_no_decodificables(workspace):
    """El repro exacto: un hijo que escribe 0x90 crudo (invalido en utf-8 Y en
    cp1252). Antes: r.stdout=None -> "'NoneType' and 'str'"."""
    cmd = (f'"{sys.executable}" -c '
           f'"import sys;sys.stdout.buffer.write(b\'\\xff\\x90ok\')"')
    out = T.run_tool("ejecutar", cmd, _ctx())
    assert "NoneType" not in out, out
    assert "Traceback" not in out, out
    assert "ok" in out, out


def test_ejecutar_imprime_cirilico_sin_traceback(workspace):
    """print(chr(0x0410)): sin PYTHONUTF8 en el hijo, es el HIJO el que revienta
    al escribir un caracter que no existe en cp1252."""
    out = T.run_tool("ejecutar", f'"{sys.executable}" -c "print(chr(0x0410))"',
                     _ctx())
    assert "NoneType" not in out, out
    assert "UnicodeEncodeError" not in out, out
    assert "А" in out, out


def test_shell_fuerza_utf8_en_el_hijo(workspace):
    """El env del hijo lleva el modo UTF-8: sin esto el fix de arriba depende de
    la suerte del locale."""
    env = T._env_utf8()
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert "PATH" in env or "Path" in env      # es el entorno REAL, no uno vacio


# ── (2) editar_archivo no puede perder los bytes del dueno ─────────────

def test_editar_archivo_latin1_conserva_los_acentos(workspace):
    """El bug mas caro: cambiar 'def f' por 'def g' borraba TODOS los acentos."""
    p = workspace / "lat.py"
    p.write_bytes(LATIN1)
    out = T.run_tool("editar_archivo",
                     f"{p} | {_bloque('def f():', 'def g():')}", _ctx())
    assert "OK" in out, out
    b = p.read_bytes()
    assert b"\xf3" in b, b            # los acentos latin-1 siguen ahi
    assert FFFD not in b, b           # y no hay ni un solo U+FFFD
    assert b.startswith(b"def g():"), b


def test_editar_archivo_no_escribe_lo_que_no_puede_decodificar(workspace):
    """0x90 no es utf-8 ni cp1252 valido: reescribir el fichero entero seria
    perder ese byte. Contrato: ERROR y el fichero INTACTO."""
    p = workspace / "raro.bin.txt"
    crudo = b"linea uno\n\x90\x81 basura\nlinea tres\n"
    p.write_bytes(crudo)
    out = T.run_tool("editar_archivo",
                     f"{p} | {_bloque('linea uno', 'linea 1')}", _ctx())
    assert "ERROR" in out, out
    assert p.read_bytes() == crudo    # ni un byte tocado


def test_editar_archivo_sube_a_utf8_y_lo_dice(workspace):
    """Si el REPLACE trae un caracter que no cabe en la codificacion original,
    se sube a utf-8 y se AVISA (escribir '?' silenciosos seria peor)."""
    p = workspace / "lat2.py"
    p.write_bytes(LATIN1)
    out = T.run_tool("editar_archivo",
                     f"{p} | {_bloque('def f():', 'def f():  # flecha →')}",
                     _ctx())
    assert "OK" in out and "utf-8" in out, out
    assert "→".encode("utf-8") in p.read_bytes()


def test_leer_archivo_latin1_no_muestra_reemplazos(workspace):
    """Lo que el modelo VE tiene que ser el texto real: si lee 'cami<FFFD>n',
    el bloque SEARCH que copie despues no casara nunca."""
    p = workspace / "lat3.py"
    p.write_bytes(LATIN1)
    out = T.run_tool("leer_archivo", str(p), _ctx())
    assert "camión con acentuación" in out, out
    assert "�" not in out, out


# ── (3) el diff cosmetico nunca puede bloquear la escritura ────────────

def test_escribir_archivo_sobre_latin1_si_escribe(workspace):
    """Antes: "'utf-8' codec can't decode byte 0xf1" y el fichero sin tocar."""
    p = workspace / "n.txt"
    p.write_bytes("niño piña".encode("latin-1"))
    out = T.run_tool("escribir_archivo", f"{p} | contenido nuevo", _ctx())
    assert "OK" in out, out
    assert p.read_bytes() == b"contenido nuevo"


def test_escribir_archivo_sobre_binario_si_escribe(workspace):
    """Ni siquiera unos bytes que ninguna codificacion acepta pueden impedir
    SOBRESCRIBIR (el contenido viejo se descarta entero, por definicion)."""
    p = workspace / "b.txt"
    p.write_bytes(b"\x90\x81\xff\xfe raro")
    out = T.run_tool("escribir_archivo", f"{p} | texto sano", _ctx())
    assert "OK" in out, out
    assert p.read_bytes() == b"texto sano"


# ── (4) fin de linea: cambiar 1 linea no reescribe el fichero ──────────

def test_editar_archivo_no_crlfiza_un_fichero_lf(workspace):
    p = workspace / "nl.txt"
    p.write_bytes(b"a = 1\nb = 2\n")
    out = T.run_tool("editar_archivo", f"{p} | {_bloque('a = 1', 'a = 9')}",
                     _ctx())
    assert "OK" in out, out
    assert p.read_bytes() == b"a = 9\nb = 2\n"


def test_editar_archivo_conserva_crlf_de_un_fichero_crlf(workspace):
    """Simetrico: un fichero que YA es CRLF no se pasa a LF (seria el mismo
    diff-de-fichero-entero, en el otro sentido)."""
    p = workspace / "nlw.txt"
    p.write_bytes(b"a = 1\r\nb = 2\r\n")
    T.run_tool("editar_archivo", f"{p} | {_bloque('a = 1', 'a = 9')}", _ctx())
    assert p.read_bytes() == b"a = 9\r\nb = 2\r\n"


def test_editar_archivo_conserva_el_crlf_de_un_utf16(workspace):
    """El mismo bug 4, pero en un codec ANCHO: en utf-16 el CRLF va CODIFICADO
    (\\r\\x00\\n\\x00 en LE), asi que contar b"\\r\\n" sobre los bytes crudos no
    casa nunca y el fichero entero salia pasado a LF. Importa en esta maquina:
    PowerShell 5.1 escribe utf-16 con Out-File por defecto."""
    p = workspace / "ps16.txt"
    p.write_bytes("a\r\nb\r\n".encode("utf-16"))
    out = T.run_tool("editar_archivo", f"{p} | {_bloque('a', 'z')}", _ctx())
    assert "OK" in out, out
    b = p.read_bytes()
    assert b.count(b"\r\x00\n\x00") == 2, b        # los DOS CRLF, en bytes
    assert b.startswith(b"\xff\xfe"), b            # y el BOM sigue ahi
    assert b.decode("utf-16") == "z\r\nb\r\n"


def test_leer_texto_cuenta_el_fin_de_linea_en_el_texto_si_el_codec_es_ancho(
        workspace):
    """Contrato directo del helper: utf-16 CRLF -> nl='\\r\\n' (contado sobre el
    texto), utf-16 LF -> nl='\\n'. Sin esto _escribir_texto normaliza el
    fichero entero."""
    p = workspace / "w16.txt"
    p.write_bytes("uno\r\ndos\r\n".encode("utf-16"))
    assert T._leer_texto(p) == ("uno\ndos\n", "utf-16", "\r\n")
    p.write_bytes("uno\ndos\n".encode("utf-16"))
    assert T._leer_texto(p) == ("uno\ndos\n", "utf-16", "\n")


def test_editar_archivo_conserva_acentos_y_crlf_de_un_utf16(workspace):
    """Codec + BOM + acentos + fin de linea, los cuatro a la vez, que es como
    llegan los ficheros que PowerShell deja en el disco del dueno."""
    p = workspace / "ps16b.txt"
    p.write_bytes("linea uno\r\nniño\r\n".encode("utf-16"))
    T.run_tool("editar_archivo",
               f"{p} | {_bloque('linea uno', 'linea DOS')}", _ctx())
    b = p.read_bytes()
    assert FFFD not in b, b
    assert b.decode("utf-16") == "linea DOS\r\nniño\r\n"


def test_escribir_archivo_nuevo_no_traduce_saltos(workspace):
    p = workspace / "nuevo.txt"
    T.run_tool("escribir_archivo", f"{p} | una\ndos", _ctx())
    assert p.read_bytes() == b"una\ndos"


def test_apendar_archivo_respeta_el_fin_de_linea_del_fichero(workspace):
    p = workspace / "log.txt"
    p.write_bytes(b"primera\n")
    T.run_tool("apendar_archivo", f"{p} | segunda", _ctx())
    assert p.read_bytes() == b"primera\nsegunda\n"


def test_apendar_archivo_respeta_la_codificacion_del_fichero(workspace):
    """Apendar utf-8 a una bitacora cp1252 la deja mixta: ilegible entera."""
    p = workspace / "bitacora.txt"
    p.write_bytes("linea con eñe\n".encode("cp1252"))
    T.run_tool("apendar_archivo", f"{p} | otra con acción", _ctx())
    b = p.read_bytes()
    assert FFFD not in b, b
    assert b.decode("cp1252") == "linea con eñe\notra con acción\n"


# ── (5) buscar: el falso negativo invisible ────────────────────────────

def test_buscar_encuentra_palabra_acentuada_en_utf8(workspace):
    p = workspace / "utf8.py"
    p.write_bytes("def función_rara():\n    pass\n".encode("utf-8"))
    out = T.run_tool("buscar", f"función_rara | {p}", _ctx())
    assert "sin coincidencias" not in out, out
    assert "función_rara" in out, out       # y sin mojibake en la linea


def test_buscar_encuentra_acentuada_sin_ripgrep(workspace, monkeypatch):
    """El mismo caso por el camino de FALLBACK (scan en Python). Se apaga rg
    vaciando el PATH: en esta maquina rg SI esta instalado y tapaba el bug del
    escaneo, que es el que se dispara en cualquier maquina sin ripgrep."""
    monkeypatch.setenv("PATH", "")
    p = workspace / "utf8b.py"
    p.write_bytes("def función_rara():\n    pass\n".encode("utf-8"))
    with pytest.raises((FileNotFoundError, OSError)):
        subprocess.run(["rg", "--version"], capture_output=True)   # rg apagado
    out = T.run_tool("buscar", f"función_rara | {p}", _ctx())
    assert "sin coincidencias" not in out, out
    assert "función_rara" in out, out


def test_buscar_no_se_cuelga_con_un_binario_en_el_ambito(workspace, monkeypatch):
    """El scan salta binarios por el byte NUL; el que NO tiene NUL pero tampoco
    decodifica no puede tumbar la busqueda."""
    monkeypatch.setenv("PATH", "")
    (workspace / "raro.txt").write_bytes(b"\x90\x81 basura sin nul\n")
    (workspace / "sano.txt").write_bytes(b"aguja aqui\n")
    out = T.run_tool("buscar", f"aguja | {workspace}", _ctx())
    assert "aguja" in out, out


# ── (6) codificacion != sintaxis ───────────────────────────────────────

def test_py_validar_acepta_un_py_latin1(workspace):
    """El fichero es Python VALIDO; lo unico raro es su codificacion."""
    p = workspace / "lat4.py"
    p.write_bytes(LATIN1)
    out = T.run_tool("py_validar", str(p), _ctx())
    assert "sintaxis OK" in out, out


def test_py_validar_respeta_el_cookie_pep263(workspace):
    p = workspace / "cookie.py"
    p.write_bytes(("# -*- coding: latin-1 -*-\n"
                   "x = 'acción'\n").encode("latin-1"))
    assert "sintaxis OK" in T.run_tool("py_validar", str(p), _ctx())


def test_py_validar_nombra_la_codificacion_y_no_dice_sintaxis(workspace):
    p = workspace / "roto.py"
    p.write_bytes(b"x = 1\n\x90\x81\n")
    out = T.run_tool("py_validar", str(p), _ctx())
    assert "CODIFICACION" in out, out
    assert "cp1252" in out or "utf-8" in out, out


def test_py_validar_sigue_cazando_la_sintaxis_mala(workspace):
    p = workspace / "malo.py"
    p.write_bytes(b"def f(:\n    pass\n")
    out = T.run_tool("py_validar", str(p), _ctx())
    assert "ERROR linea" in out, out


def test_json_validar_acepta_un_json_cp1252(workspace):
    p = workspace / "j.json"
    p.write_bytes('{"a": "niño"}'.encode("cp1252"))
    out = T.run_tool("json_validar", str(p), _ctx())
    assert "JSON valido" in out, out
    assert "cp1252" in out, out          # el aviso nombra la codificacion


def test_json_validar_sigue_cazando_el_json_malo(workspace):
    p = workspace / "malo.json"
    p.write_bytes(b'{"a": }')
    assert "ERROR" in T.run_tool("json_validar", str(p), _ctx())


# ── helpers de la frontera (contrato directo) ──────────────────────────

def test_leer_texto_detecta_bom_de_powershell(workspace):
    """PowerShell 5.1 escribe utf-8 CON BOM; leerlo como 'utf-8' pelado deja un
    \\ufeff invisible al principio que se cuela en los bloques SEARCH."""
    p = workspace / "ps.txt"
    p.write_bytes(b"\xef\xbb\xbfhola\n")
    texto, codec, nl = T._leer_texto(p)
    assert texto == "hola\n" and codec == "utf-8-sig" and nl == "\n"
    T._escribir_texto(p, texto, codec, nl)
    assert p.read_bytes() == b"\xef\xbb\xbfhola\n"       # el BOM vuelve intacto


def test_decodificar_bytes_nunca_levanta():
    assert T._decodificar_bytes(b"") == ""
    assert T._decodificar_bytes(None) == ""
    assert T._decodificar_bytes("ya str") == "ya str"
    assert T._decodificar_bytes(b"\x90\x81\xff") != ""   # latin-1 como red
