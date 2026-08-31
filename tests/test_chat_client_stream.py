# -*- coding: utf-8 -*-
"""
tests/test_chat_client_stream.py — la rama de streaming opt-in de completar()
=============================================================================
T1 (2026-08-17). Lo que estos tests fijan:

1. SIN los kwargs nuevos el body es BYTE A BYTE el de siempre. No es una
   intencion, es una comparacion exacta contra un golden literal: cualquier
   clave que se cuele (stream, stream_options, lo que sea) rompe el test.
2. Con on_token el body lleva stream:true Y stream_options.include_usage:true.
   Lo segundo importa tanto como lo primero: sin include_usage llama-server
   no manda el chunk de usage, `usage` vuelve vacio y el presupuesto de
   tokens del motor sumaria 0 EN SILENCIO (medido en :8080).
3. cancelado() corta de verdad: el cliente deja de leer y el server se queda
   con chunks sin enviar.

NADA DE MOCKS DEL TRANSPORTE (regla del repo): se levanta un servidor HTTP
real en un hilo que habla SSE con chunked encoding de verdad, y el cliente
lo consume con urllib como consumiria a llama-server.
"""
from __future__ import annotations

import datetime
import http.client
import ipaddress
import json
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cognia.agent import chat_client
from cognia.agent.chat_client import RespuestaChat, completar

MENSAJES = [{"role": "user", "content": "hola ñ"}]

# Frames grandes en el modo lento: hay que desbordar el buffer del socket
# para que el server NOTE que el cliente se fue (si todo entra en el buffer
# del SO, el write nunca falla y el test no probaria nada).
_RELLENO = "x" * 2048
_FRAMES_LENTO = 400
# Cuanto se queda MUDO el server del modo "mudo" si el test no lo libera. Es
# el caso real: el backend mando un token y se puso a pensar.
_MUDO_S = 5.0
# Modo "sano_largo": un stream SANO que tarda MAS que el timeout del turno
# pero que nunca se calla mas de _PAUSA_SANA_S. Es el caso del hallazgo #3:
# con el deadline de PARED moria un turno que estaba andando perfecto.
_FRAMES_SANO = 40
_PAUSA_SANA_S = 0.08
# Tope de pings del modo keepalive_eterno, para que un fallo del test no deje
# un hilo escupiendo para siempre.
_MAX_PINGS = 400


class _Manejador(BaseHTTPRequestHandler):
    """/v1/chat/completions de juguete. Responde segun estado['modo']."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # sin ruido en el output del pytest
        pass

    def _chunk(self, data: bytes) -> bool:
        """Bytes crudos dentro de UN chunk HTTP. False si el cliente se fue."""
        try:
            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
            self.wfile.flush()
            return True
        except Exception:
            return False

    def _sse(self, obj) -> bool:
        """Un frame SSE dentro de un chunk HTTP. False si el cliente se fue."""
        crudo = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        return self._chunk(b"data: " + crudo + b"\n\n")

    def do_POST(self):
        est = self.server.estado
        n = int(self.headers.get("Content-Length") or 0)
        est["cuerpos"].append(self.rfile.read(n))
        modo = est["modo"]

        # "json_entero": el server IGNORA stream:true y contesta el JSON
        # entero con application/json (un proxy delante, u otro backend). El
        # cuerpo es EL MISMO que el de no_stream a proposito: por el camino
        # no-stream parsea perfecto, asi que la unica diferencia es que se
        # pidio SSE y no se recibio SSE.
        if modo in ("no_stream", "json_entero"):
            cuerpo = json.dumps({
                "choices": [{"message": {"content": "ok"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 14, "completion_tokens": 37,
                          "total_tokens": 51},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        if modo == "stream":
            self._sse({"choices": [{"delta": {"reasoning_content": "pien"}}]})
            self._sse({"choices": [{"delta": {"reasoning_content": "so"}}]})
            for t in ("hola", " ", "mundo"):
                self._sse({"choices": [{"delta": {"content": t}}]})
            self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            # chunk final de include_usage: choices vacio + usage
            self._sse({"choices": [],
                       "usage": {"prompt_tokens": 14, "completion_tokens": 37,
                                 "total_tokens": 51}})
            self._sse(b"[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "tool_calls":
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1",
                 "function": {"name": "leer", "arguments": "{\"ru"}}]}}]})
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "ta\": \"a.py\"}"}}]}}]})
            self._sse({"choices": [{"delta": {},
                                    "finish_reason": "tool_calls"}]})
            self._sse({"choices": [], "usage": {"completion_tokens": 9}})
            self._sse(b"[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "muerto":
            # Corte de red a mitad: dos frames y la conexion se cae sin
            # terminador chunked -> el cliente tiene que ver IncompleteRead.
            self._sse({"choices": [{"delta": {"content": "par"}}]})
            self._sse({"choices": [{"delta": {"content": "cial"}}]})
            try:
                self.connection.close()
            except Exception:
                pass

        elif modo == "sin_usage":
            # El server IGNORA stream_options.include_usage (es un pedido, no
            # una garantia) pero manda timings, como hace llama.cpp.
            for t in ("ho", "la"):
                self._sse({"choices": [{"delta": {"content": t}}]})
            self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
                       "timings": {"prompt_n": 7, "predicted_n": 16}})
            self._sse(b"[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "sucio":
            # Renglones data: que no son JSON mezclados con frames buenos.
            self._sse(b"{no es json")
            self._sse({"choices": [{"delta": {"content": "hola"}}]})
            self._sse(b"tampoco }")
            self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            self._sse(b"[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "sin_nada":
            # Ni usage ni timings: no se puede saber cuantos tokens fueron.
            self._sse({"choices": [{"delta": {"content": "ho"}}]})
            self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            self._sse(b"[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "sin_salto_final":
            # Server no conforme: el ultimo frame se va SIN el \n final y con
            # el se iba su finish_reason.
            self._sse({"choices": [{"delta": {"content": "hola"}}]})
            ult = (b'data: {"choices": [{"delta": {}, "finish_reason": '
                   b'"length"}], "usage": {"completion_tokens": 3}}')
            self.wfile.write(b"%x\r\n" % len(ult) + ult + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "goteo":
            # El MISMO stream, escrito de a UN byte: el deschunkeo propio
            # tiene que aguantar que el framing venga partido en cualquier
            # lado (es lo que hace un proxy o una red con MTU chico).
            crudo = b""
            for t in ("go", "te", "o"):
                d = json.dumps({"choices": [{"delta": {"content": t}}]}).encode()
                d = b"data: " + d + b"\n\n"
                crudo += b"%x\r\n" % len(d) + d + b"\r\n"
            d = b"data: [DONE]\n\n"
            crudo += b"%x\r\n" % len(d) + d + b"\r\n" + b"0\r\n\r\n"
            for i in range(len(crudo)):
                self.wfile.write(crudo[i:i + 1])
                self.wfile.flush()

        elif modo == "tool_calls_mudo":
            # Arranca un tool call y se calla con los arguments a medias.
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1",
                 "function": {"name": "borrar", "arguments": "{\"ru"}}]}}]})
            est["silencio"].wait(timeout=_MUDO_S)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            est["fin"].set()

        elif modo == "mudo":
            # UN token y silencio, que es lo que hace un backend pensando. El
            # frame "TARDE" sale recien cuando el test libera el evento: si el
            # cliente lo entrega, es que despacho DESPUES del corte.
            self._sse({"choices": [{"delta": {"content": "t0"}}]})
            est["silencio"].wait(timeout=_MUDO_S)
            self._sse({"choices": [{"delta": {"content": "TARDE"}}]})
            est["fin"].set()

        elif modo == "tool_cola":
            # Un tool call COMPLETO y EJECUTABLE cuyo ultimo renglon se va SIN
            # el \n final (la "cola" que el arreglo del 2026-08-17 aprendio a
            # procesar). Es el escenario del hallazgo #2: cancelar justo en la
            # consulta de esa cola dejaba cortado=False con los tool calls
            # armados y ejecutables.
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c9",
                 "function": {"name": "borrar_todo",
                              "arguments": "{\"ru"}}]}}]})
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "ta\": \"/\"}"}}]}}]})
            ult = (b'data: {"choices": [{"delta": {}, "finish_reason": '
                   b'"tool_calls"}], "usage": {"completion_tokens": 9}}')
            self.wfile.write(b"%x\r\n" % len(ult) + ult + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "sano_largo":
            # Stream SANO y LARGO: tarda mas que el timeout del turno pero no
            # se calla nunca mas de _PAUSA_SANA_S. Es un modelo generando a
            # ritmo normal, no un cuelgue.
            for i in range(_FRAMES_SANO):
                if not self._sse({"choices": [{"delta": {"content": f"t{i}"}}]}):
                    break
                est["enviados"] = i + 1
                time.sleep(_PAUSA_SANA_S)
            self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            self._sse({"choices": [],
                       "usage": {"completion_tokens": _FRAMES_SANO}})
            self._sse(b"[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            est["fin"].set()

        elif modo == "keepalive_eterno":
            # Un proxy que pinguea para siempre porque el backend de atras no
            # contesta nunca. La INACTIVIDAD no dispara (llegan bytes cada
            # 50 ms): lo unico que puede rescatar el turno es el reloj de
            # PARED.
            for _ in range(_MAX_PINGS):
                if not self._chunk(b": ping\n\n"):
                    break
                if est["silencio"].wait(0.05):
                    break
            est["fin"].set()

        elif modo == "solo_keepalives":
            # El transporte SI habla SSE (manda comentarios) pero el backend
            # de atras murio en el prefill y no sale ni un frame de datos.
            self._chunk(b": ping\n\n")
            self._chunk(b": ping\n\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        elif modo == "lento":
            for i in range(_FRAMES_LENTO):
                if not self._sse({"choices": [
                        {"delta": {"content": f"t{i}" + _RELLENO}}]}):
                    break
                est["enviados"] = i + 1
                time.sleep(0.005)
            est["fin"].set()


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass          # el cliente que aborta es LO ESPERADO en el test de corte


def _arrancar(srv, monkeypatch, esquema: str):
    srv.estado = {"modo": "no_stream", "cuerpos": [], "enviados": 0,
                  "fin": threading.Event(), "silencio": threading.Event()}
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    # La auditoria escribe a disco: aca es ruido.
    from cognia import backend_activo
    monkeypatch.setattr(backend_activo, "registrar", lambda *a, **kw: {})
    chat_client._KV_SUCIO["v"] = False
    srv.url = f"{esquema}://127.0.0.1:{srv.server_address[1]}"
    return srv


def _apagar(srv):
    chat_client._KV_SUCIO["v"] = False
    srv.estado["silencio"].set()      # que ningun handler quede esperando
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def server(monkeypatch):
    """Server SSE real en 127.0.0.1:puerto-libre. estado['modo'] lo dirige."""
    srv = _arrancar(_Server(("127.0.0.1", 0), _Manejador), monkeypatch, "http")
    yield srv
    _apagar(srv)


# --- TLS de verdad (hallazgo #1) -----------------------------------------

def _cert_autofirmado(carpeta) -> str:
    """Un PEM (clave + certificado) autofirmado para 127.0.0.1, al vuelo.

    Con SAN IPAddress y basicConstraints CA para que el MISMO PEM sirva de
    ancla de confianza del cliente: asi el test corre con verificacion de
    certificado ENCENDIDA (TLS de verdad, no un TLS con los chequeos
    apagados)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nombre)
            .issuer_name(nombre)
            .public_key(clave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(ahora - datetime.timedelta(minutes=5))
            .not_valid_after(ahora + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                           critical=True)
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False)
            .sign(clave, hashes.SHA256()))
    pem = carpeta / "cognia_tls_test.pem"
    pem.write_bytes(
        clave.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption())
        + cert.public_bytes(serialization.Encoding.PEM))
    return str(pem)


@pytest.fixture
def server_tls(monkeypatch, tmp_path):
    """EL MISMO server SSE, servido sobre TLS real.

    El disparador del hallazgo #1 es COGNIA_LLM_URL=https://... (apuntar el
    agente a otro equipo, documentado en cognia/arranque.py). Nada de mocks:
    handshake, records y cifrado de verdad; lo unico que se inyecta es el
    ancla de confianza del cliente (urllib no expone el context por kwarg)."""
    pem = _cert_autofirmado(tmp_path)
    srv = _Server(("127.0.0.1", 0), _Manejador)
    ctx_srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx_srv.load_cert_chain(pem)
    srv.socket = ctx_srv.wrap_socket(srv.socket, server_side=True)
    ctx_cli = ssl.create_default_context(cafile=pem)
    monkeypatch.setattr(http.client, "_create_https_context",
                        lambda *a, **kw: ctx_cli)
    # urllib.request.HTTPSHandler CONSTRUYE el contexto en su __init__ y el
    # opener global se arma una sola vez: sin tirarlo, el segundo test TLS
    # reusaria el ancla de confianza del primero y saldria
    # CERTIFICATE_VERIFY_FAILED. (Se descubrio asi: el primer test pasaba y
    # los siguientes no.)
    urllib.request._opener = None
    srv = _arrancar(srv, monkeypatch, "https")
    yield srv
    _apagar(srv)
    urllib.request._opener = None


# --- 1. el body de hoy, byte a byte -------------------------------------

def test_body_sin_kwargs_nuevos_es_identico_al_de_hoy(server):
    """Golden literal. Si un dia alguien agrega una clave 'inofensiva' al
    body por defecto, este test lo dice; el orden y el ensure_ascii=False
    tambien quedan fijados."""
    resp = completar(MENSAJES, url=server.url, temperature=0.7, top_p=0.9,
                     max_tokens=1234, razonador=False)
    assert resp.ok and resp.texto == "ok"
    esperado = ('{"messages": [{"role": "user", "content": "hola ñ"}], '
                '"temperature": 0.7, "top_p": 0.9, '
                '"max_tokens": 1234}').encode("utf-8")
    assert server.estado["cuerpos"][0] == esperado
    assert resp.cortado is False


def test_body_con_todas_las_opciones_viejas_tambien_identico(server):
    """El golden completo: tools + response_format + reasoning_effort en el
    orden historico. Cubre que la rama nueva no reordene nada."""
    tools = [{"type": "function", "function": {"name": "t"}}]
    rf = {"type": "json_schema",
          "json_schema": {"name": "s", "schema": {"type": "object"}}}
    completar(MENSAJES, tools=tools, url=server.url, temperature=0.7,
              top_p=0.9, max_tokens=1234, razonador=False,
              response_format=rf, reasoning_effort="high")
    esperado = ('{"messages": [{"role": "user", "content": "hola ñ"}], '
                '"temperature": 0.7, "top_p": 0.9, "max_tokens": 1234, '
                '"tools": [{"type": "function", "function": '
                '{"name": "t"}}], '
                '"response_format": {"type": "json_schema", "json_schema": '
                '{"name": "s", "schema": {"type": "object"}}}, '
                '"chat_template_kwargs": {"reasoning_effort": "high"}'
                '}').encode("utf-8")
    assert server.estado["cuerpos"][0] == esperado


# --- 2. con streaming ----------------------------------------------------

def test_on_token_manda_stream_y_include_usage(server):
    server.estado["modo"] = "stream"
    vistos, pensado = [], []
    resp = completar(MENSAJES, url=server.url, max_tokens=1234,
                     razonador=False, on_token=vistos.append,
                     on_reasoning=pensado.append)

    cuerpo = json.loads(server.estado["cuerpos"][0])
    assert cuerpo["stream"] is True
    # SIN esto el usage vuelve None y el presupuesto suma 0 en silencio.
    assert cuerpo["stream_options"] == {"include_usage": True}

    assert vistos == ["hola", " ", "mundo"]      # llegaron de a fragmentos
    assert pensado == ["pien", "so"]
    assert resp.texto == "hola mundo"
    assert resp.reasoning_content == "pienso"
    assert resp.finish_reason == "stop"
    assert resp.cortado is False
    assert resp.usage == {"prompt_tokens": 14, "completion_tokens": 37,
                          "total_tokens": 51}


def test_solo_cancelado_ya_enciende_el_stream(server):
    """Los tres kwargs son disparadores: se puede querer cortar sin mirar."""
    server.estado["modo"] = "stream"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     cancelado=lambda: False)
    cuerpo = json.loads(server.estado["cuerpos"][0])
    assert cuerpo["stream"] is True
    assert cuerpo["stream_options"]["include_usage"] is True
    assert resp.texto == "hola mundo" and resp.cortado is False


def test_response_format_sobrevive_al_stream(server):
    server.estado["modo"] = "stream"
    rf = {"type": "json_schema",
          "json_schema": {"name": "s", "schema": {"type": "object"}}}
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     response_format=rf, on_token=lambda t: None)
    cuerpo = json.loads(server.estado["cuerpos"][0])
    assert cuerpo["response_format"] == rf and cuerpo["stream"] is True
    assert resp.ok


def test_tool_calls_troceados_se_rearman(server):
    """El stream parte id/name/arguments en varios deltas: la respuesta tiene
    que quedar igual que la del no-stream."""
    server.estado["modo"] = "tool_calls"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "c1" and tc.nombre == "leer"
    assert tc.argumentos == {"ruta": "a.py"}


# --- 3. el corte ---------------------------------------------------------

def test_cancelado_corta_y_no_se_piden_mas_chunks(server):
    server.estado["modo"] = "lento"
    vistos = []
    t0 = time.time()
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=vistos.append,
                     cancelado=lambda: len(vistos) >= 2)
    tardo = time.time() - t0

    # Se corto: marca por los dos lados y ok sigue True (cortar no es fallar)
    assert resp.cortado is True
    assert resp.finish_reason == "cancelado"
    assert resp.ok and resp.error == ""
    # Lo acumulado esta y es PARCIAL
    assert vistos and resp.texto.startswith("t0")
    assert len(vistos) < 10, f"siguio leyendo: {len(vistos)} fragmentos"
    # Y el server se quedo con frames sin mandar: dejamos que note el corte.
    server.estado["fin"].wait(timeout=10)
    assert server.estado["enviados"] < _FRAMES_LENTO, (
        "el server envio TODO: el cliente no corto nada")
    assert tardo < 10, f"el corte tardo {tardo:.2f}s"


def test_cancelado_antes_del_primer_chunk_no_lee_nada(server):
    server.estado["modo"] = "lento"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     cancelado=lambda: True)
    assert resp.cortado is True and resp.texto == ""
    assert resp.usage == {}      # cortar deja SIN usage: documentado, no cero
    server.estado["fin"].wait(timeout=10)


def test_cancelacion_fuera_de_banda_con_el_backend_mudo(server):
    """EL test que faltaba (hallazgo #2, 2026-08-17).

    Los dos tests de corte de arriba disparan la cancelacion con datos que YA
    llegaron (`len(vistos) >= 2`, `lambda: True`): el lector nunca esta
    bloqueado cuando la bandera se pone, asi que la feature PARECIA andar.

    El caso real es el otro: el usuario aprieta Esc desde OTRO HILO mientras
    el backend mando un token y se puso a pensar. Con el codigo del
    2026-08-17 (chequeo solo arriba del bucle + read1 bloqueante) esto
    tardaba lo que el backend tardara en volver a hablar — acotado unicamente
    por el timeout general (hasta 1800 s) — y ADEMAS entregaba a on_token el
    token que llego DESPUES del corte.
    """
    server.estado["modo"] = "mudo"
    vistos = []
    corte = threading.Event()
    threading.Timer(0.3, corte.set).start()

    t0 = time.time()
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=vistos.append, cancelado=corte.is_set)
    tardo = time.time() - t0
    # Recien ahora se libera al server (el frame tardio ya no puede llegar a
    # tiempo de confundir la medicion).
    server.estado["silencio"].set()

    assert resp.cortado is True and resp.finish_reason == "cancelado"
    assert tardo < 0.9, (
        f"el corte fuera de banda tardo {tardo:.2f}s: la cancelacion depende "
        "de que el backend hable, no del usuario")
    assert vistos == ["t0"], f"se despacharon tokens post-corte: {vistos}"
    assert resp.texto == "t0"
    server.estado["fin"].wait(timeout=10)


# --- 4. la red se muere a mitad ------------------------------------------

def test_corte_de_red_a_mitad_no_se_traga_ni_pierde_lo_parcial(server):
    server.estado["modo"] = "muerto"
    vistos = []
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=vistos.append)
    assert resp.error, "el fallo de red se trago en silencio"
    assert resp.ok is False
    assert resp.cortado is False          # murio, no lo cortamos nosotros
    assert vistos == ["par", "cial"]
    assert resp.texto == "parcial"        # lo que llego no se pierde


# --- 5. el transporte que no habla SSE (hallazgo #1) ---------------------

def test_200_sin_sse_vuelve_error_y_no_respuesta_vacia(server):
    """Un 200 con el JSON entero (proxy / otro backend) salia ok=True con
    texto='' — 'el modelo no dijo nada' en vez de 'el transporte se rompio'.
    El MISMO cuerpo por el camino no-stream se parsea perfecto: se comprueba
    abajo para que quede claro que la diferencia es el transporte."""
    server.estado["modo"] = "json_entero"
    vistos = []
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=vistos.append)
    assert resp.ok is False, f"paso como exito: {resp}"
    assert "sin SSE" in resp.error and "0 frames" in resp.error
    assert "choices" in resp.error          # dice QUE contesto, no solo que fallo
    assert vistos == []

    # el mismo cuerpo, sin pedir stream: se parsea entero
    server.estado["modo"] = "no_stream"
    normal = completar(MENSAJES, url=server.url, razonador=False)
    assert normal.ok and normal.texto == "ok"
    assert normal.usage["completion_tokens"] == 37


def test_frames_malformados_se_pueden_leer(server):
    """El contador dejo de ser de solo escritura: viaja en la respuesta."""
    server.estado["modo"] = "sucio"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.ok and resp.texto == "hola"
    assert resp.frames_malformados == 2


# --- 6. el usage cuando el server ignora include_usage (hallazgo #3) -----

def test_usage_sale_de_timings_si_no_hay_chunk_de_usage(server):
    """include_usage es un PEDIDO. Sin el chunk, el numero esta igual en
    timings.predicted_n (lo mismo que lee node/llama_backend.py:1143).

    prompt_n NO se usa como prompt_tokens: cuenta lo PROCESADO, y con el KV
    cacheado no es el prompt (medido en :8080/b10434: usage dice
    prompt_tokens=40 y las timings del mismo turno dicen prompt_n=1)."""
    server.estado["modo"] = "sin_usage"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.ok and resp.texto == "hola" and resp.finish_reason == "stop"
    assert resp.usage == {"completion_tokens": 16}
    assert "prompt_tokens" not in resp.usage      # el 7 de prompt_n no cuenta
    assert resp.usage_estimado is True      # se sabe POR QUE VIA salio
    assert resp.completion_tokens == 16


def test_no_saber_los_tokens_es_distinguible_de_cero(server):
    """Sin usage y sin timings: None, no 0. Un llamador que sume
    `usage.get(...) or 0` mezcla 'no se pudo saber' con 'no genero nada'."""
    server.estado["modo"] = "sin_nada"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.ok and resp.usage == {}
    assert resp.completion_tokens is None
    assert resp.usage_estimado is False
    # y el caso contrario: 0 tokens de verdad SI es 0
    assert RespuestaChat(usage={"completion_tokens": 0}).completion_tokens == 0


def test_usage_del_stream_normal_no_cambia(server):
    """La red de timings no pisa el usage real cuando el server lo manda."""
    server.estado["modo"] = "stream"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.usage["completion_tokens"] == 37
    assert resp.usage_estimado is False
    assert resp.usage_via == "server"


def test_al_cortar_se_estiman_los_tokens_por_frames_de_contenido(server):
    """DEFECTO #5 (2026-08-17): al cortar no llega el chunk de usage NI las
    timings, asi que el usage volvia {} y el presupuesto del motor sumaba 0.
    Medido con /tokenize contra :8080: prompt 23 + generados 65 por corte,
    contabilizados como CERO (sub-cuenta del 56%).

    Los frames de contenido son la via directa: un frame = un token."""
    server.estado["modo"] = "lento"
    vistos = []
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=vistos.append,
                     cancelado=lambda: len(vistos) >= 3)
    server.estado["fin"].wait(timeout=10)
    assert resp.cortado is True and resp.ok
    assert resp.completion_tokens is not None, (
        "el corte volvio a contabilizarse como CERO tokens")
    assert resp.completion_tokens == len(vistos)
    assert resp.usage_estimado is True
    assert resp.usage_via == "frames"
    # Lo que NO se estima: el prompt. Inventarlo seria cambiar un cero
    # silencioso por un numero silenciosamente MAL (misma regla que prompt_n).
    assert "prompt_tokens" not in resp.usage


def test_un_corte_sin_un_solo_frame_sigue_siendo_desconocido(server):
    """No se inventa: 0 frames = 'no se pudo saber', que no es 0 tokens."""
    server.estado["modo"] = "lento"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     cancelado=lambda: True)
    server.estado["fin"].wait(timeout=10)
    assert resp.cortado is True and resp.usage == {}
    assert resp.completion_tokens is None
    assert resp.usage_estimado is False and resp.usage_via == ""


# --- 7. cancelado() que lanza (hallazgo #4) ------------------------------

def test_cancelado_que_lanza_no_mata_el_turno(server, capsys, monkeypatch):
    """Un cancelado() que cierra sobre un widget muerto no puede costar la
    tarea: no cancela, no aborta, avisa UNA vez."""
    monkeypatch.delenv("COGNIA_BACKEND_LOG", raising=False)
    server.estado["modo"] = "stream"

    def cancelado():
        raise RuntimeError("widget cerrado")

    resp = completar(MENSAJES, url=server.url, razonador=False,
                     cancelado=cancelado)
    assert resp.ok and resp.error == ""
    assert resp.texto == "hola mundo"      # el turno se completo entero
    assert resp.cortado is False
    err = capsys.readouterr().err
    assert "cancelado() fallo" in err
    # una linea por clase + el resumen; NO una por frame
    assert err.count("cancelado() fallo") == 1
    assert "avisos repetidos" in err and "cancelado x" in err


# --- 8. tope de avisos (hallazgo #8) -------------------------------------

def test_un_on_token_roto_no_escupe_una_linea_por_token(server, capsys,
                                                        monkeypatch):
    monkeypatch.delenv("COGNIA_BACKEND_LOG", raising=False)
    server.estado["modo"] = "stream"

    def roto(_):
        raise ValueError("consola cerrada")

    resp = completar(MENSAJES, url=server.url, razonador=False, on_token=roto,
                     on_reasoning=roto)
    assert resp.ok and resp.texto == "hola mundo"
    err = capsys.readouterr().err
    assert err.count("callback de stream fallo") == 1
    # 5 fallos (2 de reasoning + 3 de content) resumidos en una linea
    assert "callback x5" in err


# --- 9. tool calls al cortar (hallazgo #5) -------------------------------

def test_al_cortar_no_hay_tool_calls_ejecutables(server):
    """Se cortaba con .tool_calls poblado desde fragmentos TRUNCADOS: un
    llamador con la forma de loop.py ejecutaba 'borrar' con
    argumentos={'args': '{\"ru'} despues de que el usuario cancelo."""
    server.estado["modo"] = "tool_calls_mudo"
    corte = threading.Event()
    threading.Timer(0.3, corte.set).start()
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     cancelado=corte.is_set)
    server.estado["silencio"].set()

    assert resp.cortado is True and resp.finish_reason == "cancelado"
    assert resp.tool_calls == [], "hay tool calls ejecutables tras el corte"
    assert len(resp.tool_calls_parciales) == 1
    tc = resp.tool_calls_parciales[0]
    assert tc.nombre == "borrar" and tc.argumentos_crudos == '{"ru'
    assert tc.argumentos_rotos is True     # y se ve que estaban truncados
    server.estado["fin"].wait(timeout=10)


def test_los_tool_calls_sanos_no_se_marcan_rotos(server):
    server.estado["modo"] = "tool_calls"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.tool_calls[0].argumentos_rotos is False
    assert resp.tool_calls_parciales == []


# --- 10. framing (hallazgos #6 y el deschunkeo propio) -------------------

def test_ultima_linea_sin_salto_final_no_se_pierde(server):
    """Un server que cierra sin \\n final se llevaba el ultimo frame Y su
    finish_reason."""
    server.estado["modo"] = "sin_salto_final"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.ok and resp.texto == "hola"
    assert resp.finish_reason == "length"          # se perdia entero
    assert resp.usage["completion_tokens"] == 3


def test_el_stream_llega_igual_partido_de_a_un_byte(server):
    """El deschunkeo es nuestro (http.client no sirve con lecturas no
    bloqueantes): tiene que aguantar el framing partido en cualquier lado."""
    server.estado["modo"] = "goteo"
    vistos = []
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=vistos.append)
    assert resp.ok, resp.error
    assert vistos == ["go", "te", "o"] and resp.texto == "goteo"


# --- 11. HTTPS: la rama SSE sobre TLS (hallazgo #1, 2026-08-17) ----------
# El diseño no bloqueante valia SOLO sobre TCP pelado. Sobre TLS,
# SSLSocket.recv_into NO devuelve None cuando bloquearia: LANZA
# ssl.SSLWantReadError (errno 2), y socket.SocketIO solo mapea a None los
# errno de _blocking_errnos (EAGAIN/EWOULDBLOCK). La excepcion subia y mataba
# el turno en el primer silencio del backend. Peor: _canal_no_bloqueante
# devolvia un canal VALIDO (setblocking(False) funciona sobre SSLSocket), asi
# que la rama de rescate bloqueante nunca corria y el aviso "perdi la garantia
# de corte" nunca salia.

def test_https_stream_completo(server_tls):
    """Sobre TLS, un stream normal tiene que salir IGUAL que sobre TCP."""
    server_tls.estado["modo"] = "stream"
    vistos, pensado = [], []
    resp = completar(MENSAJES, url=server_tls.url, razonador=False,
                     on_token=vistos.append, on_reasoning=pensado.append)
    assert resp.ok, f"la rama SSE revento sobre TLS: {resp.error}"
    assert vistos == ["hola", " ", "mundo"] and pensado == ["pien", "so"]
    assert resp.texto == "hola mundo" and resp.finish_reason == "stop"
    assert resp.usage["completion_tokens"] == 37


def test_https_corte_fuera_de_banda_con_el_backend_mudo(server_tls, capsys,
                                                        monkeypatch):
    """EL test del hallazgo #1: TLS + silencio del backend + Esc de otro hilo.

    ANTES: tardo=0,01s ok=False error='SSLWantReadError: The operation did not
    complete (read)' y texto='t0'. El turno moria en el primer silencio.

    El server se calla _MUDO_S=5 s: si el corte llegara en 0,3 s pero la
    lectura fuera BLOQUEANTE, completar() volveria recien a los 5 s. Que
    vuelva en <1,5 s es la prueba de que el canal no bloqueante FUNCIONA sobre
    TLS, no de que se haya degradado.
    """
    monkeypatch.delenv("COGNIA_BACKEND_LOG", raising=False)
    server_tls.estado["modo"] = "mudo"
    vistos = []
    corte = threading.Event()
    threading.Timer(0.3, corte.set).start()

    t0 = time.time()
    resp = completar(MENSAJES, url=server_tls.url, razonador=False,
                     on_token=vistos.append, cancelado=corte.is_set)
    tardo = time.time() - t0
    server_tls.estado["silencio"].set()

    assert resp.ok, f"sobre TLS el stream revento: {resp.error}"
    assert resp.cortado is True and resp.finish_reason == "cancelado"
    assert vistos == ["t0"], f"se despacharon tokens post-corte: {vistos}"
    assert resp.texto == "t0"
    assert tardo < 1.5, (
        f"el corte fuera de banda sobre TLS tardo {tardo:.2f}s")
    # Y NO se degrado a la rama bloqueante: el aviso de perdida de garantia
    # tiene que estar ausente porque no hubo perdida de garantia.
    assert "esperar a que el backend hable" not in capsys.readouterr().err
    server_tls.estado["fin"].wait(timeout=10)


def test_https_tool_calls_troceados_se_rearman(server_tls):
    """Un stream TLS con varios frames pegados en pocos records: el rearmado
    de tool calls sale igual que sobre TCP.

    (NO prueba el guard de sock.pending(): medido 2026-08-17, con el orden de
    bucle actual pending() nunca devuelve >0 porque siempre se lee antes de
    dormir. El guard es un seguro, no el arreglo de un cuelgue reproducido;
    esta dicho asi en _canal_no_bloqueante.)"""
    server_tls.estado["modo"] = "tool_calls"
    resp = completar(MENSAJES, url=server_tls.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.ok, resp.error
    assert resp.finish_reason == "tool_calls" and len(resp.tool_calls) == 1
    assert resp.tool_calls[0].argumentos == {"ruta": "a.py"}


# --- 12. barrido de TODOS los indices de cancelacion (hallazgo #2) -------
# El corte se decidia en TRES `if _corte_pedido(...)` sueltos y UNO de ellos
# — el del ultimo renglon sin \n — descartaba el frame pero NO marcaba
# `cortado`. Resultado medido ANTES del arreglo, cancelando en la consulta de
# la cola: cortado=False, finish='tool_calls' y .tool_calls con
# 'borrar_todo' EJECUTABLE, despues de que el usuario apreto Esc.
#
# El barrido no elige un indice "interesante": los prueba TODOS. La
# invariante se comprueba contra un hecho observable (cuantas veces se llamo
# de verdad a cancelado()), no contra un numero adivinado.

def _barrido(server, modo: str, k: int):
    """Corre el modo cancelando en la k-esima consulta de cancelado().

    Devuelve (respuesta, llamadas). `llamadas >= k` significa que el corte se
    PIDIO de verdad; si es menor, el stream termino antes de llegar a esa
    consulta y la respuesta completa es lo correcto."""
    server.estado["modo"] = modo
    cuenta = {"n": 0}

    def cancelado():
        cuenta["n"] += 1
        return cuenta["n"] >= k

    resp = completar(MENSAJES, url=server.url, razonador=False,
                     cancelado=cancelado)
    return resp, cuenta["n"]


@pytest.mark.parametrize("k", range(1, 13))
def test_barrido_cancelacion_con_cola_sin_salto_jamas_deja_tool_calls(server,
                                                                      k):
    resp, llamadas = _barrido(server, "tool_cola", k)
    if llamadas >= k:
        # Se pidio el corte: UNA sola verdad, por los dos lados, y CERO tool
        # calls ejecutables.
        assert resp.cortado is True, (
            f"k={k}: cancelado() dijo True y cortado quedo False "
            f"(finish={resp.finish_reason!r})")
        assert resp.finish_reason == "cancelado"
        assert resp.tool_calls == [], (
            f"k={k}: TOOL CALLS EJECUTABLES tras el corte: "
            f"{[tc.nombre for tc in resp.tool_calls]}")
    else:
        # Nunca se pidio: la respuesta completa es lo correcto.
        assert resp.cortado is False and resp.finish_reason == "tool_calls"
        assert [tc.nombre for tc in resp.tool_calls] == ["borrar_todo"]
        assert resp.tool_calls_parciales == []


@pytest.mark.parametrize("k", range(1, 13))
def test_barrido_cancelacion_sin_tools_no_reporta_truncado_como_completo(
        server, k):
    """La variante sin tools del mismo agujero: salia cortado=False,
    finish_reason='' y usage={} — una respuesta TRUNCADA reportada como
    completa."""
    resp, llamadas = _barrido(server, "sin_salto_final", k)
    if llamadas >= k:
        assert resp.cortado is True, (
            f"k={k}: truncado por corte reportado como completo "
            f"(finish={resp.finish_reason!r}, texto={resp.texto!r})")
        assert resp.finish_reason == "cancelado"
    else:
        assert resp.cortado is False and resp.finish_reason == "length"


def test_cortar_nunca_deja_tool_calls_ejecutables_es_estructural(server):
    """La invariante no depende de un `if` aguas abajo: al cortar, los tool
    calls se arman DIRECTO bajo otra clave (ver _crudo_desde_stream)."""
    acc = {"texto": ["x"], "razon": [], "finish": "tool_calls",
           "usage": {}, "timings": {}, "usage_estimado": False,
           "cortado": True,
           "tcs": {0: {"type": "function", "id": "c1",
                       "function": {"name": "borrar", "arguments": "{}"}}}}
    crudo = chat_client._crudo_desde_stream(acc)
    msg = crudo["choices"][0]["message"]
    assert "tool_calls" not in msg
    assert len(msg["tool_calls_parciales"]) == 1
    assert crudo["choices"][0]["finish_reason"] == "cancelado"


# --- 13. el timeout es INACTIVIDAD, no pared (hallazgo #3) ---------------

def test_stream_sano_y_largo_no_muere_por_el_reloj_de_pared(server):
    """ANTES: timeout=2.0 contra un server que tokeniza ~3 s sin silencios
    daba tardo=2.02s ok=False error='el stream no termino en 2s (recibidos 20
    frames)', se tiraban los 20 tokens YA entregados y loop.py cortaba la
    tarea. Un stream que nunca calla mas de 80 ms no es un cuelgue."""
    server.estado["modo"] = "sano_largo"
    vistos = []
    t0 = time.time()
    resp = completar(MENSAJES, url=server.url, razonador=False, timeout=2.0,
                     on_token=vistos.append)
    tardo = time.time() - t0

    assert resp.ok, f"murio un stream SANO: {resp.error}"
    assert len(vistos) == _FRAMES_SANO, f"llegaron {len(vistos)} tokens"
    assert resp.finish_reason == "stop"
    assert resp.usage["completion_tokens"] == _FRAMES_SANO
    assert tardo > 2.0, (
        f"el server tardo {tardo:.2f}s, menos que el timeout: el test no "
        "estaria probando nada")
    server.estado["fin"].wait(timeout=10)


def test_silencio_largo_de_verdad_si_corta(server):
    """La otra mitad: la INACTIVIDAD sigue protegiendo. Un backend que manda
    un token y se calla mas que el presupuesto tiene que morir por timeout."""
    server.estado["modo"] = "mudo"
    t0 = time.time()
    resp = completar(MENSAJES, url=server.url, razonador=False, timeout=0.5,
                     on_token=lambda t: None)
    tardo = time.time() - t0
    server.estado["silencio"].set()
    assert resp.ok is False and "TimeoutError" in resp.error
    assert "callo" in resp.error          # y dice que fue por SILENCIO
    assert resp.texto == "t0"             # lo que llego no se pierde
    assert tardo < 4.0, f"tardo {tardo:.2f}s"
    server.estado["fin"].wait(timeout=10)


def test_keepalives_eternos_no_cuelgan_el_turno_para_siempre(server):
    """El tope de PARED existe justo para esto: un proxy que pinguea cada
    50 ms nunca dispara la inactividad."""
    server.estado["modo"] = "keepalive_eterno"
    t0 = time.time()
    resp = completar(MENSAJES, url=server.url, razonador=False, timeout=0.6,
                     on_token=lambda t: None)
    tardo = time.time() - t0
    server.estado["silencio"].set()
    assert resp.ok is False and "TimeoutError" in resp.error
    assert "pared" in resp.error
    # pared = max(espera, min(espera*4, 3600)) = 2,4 s con timeout=0,6
    assert 1.5 < tardo < 6.0, f"el reloj de pared disparo a los {tardo:.2f}s"
    server.estado["fin"].wait(timeout=10)


# --- 14. los comentarios SSE SI son SSE (hallazgo #4) --------------------

def test_solo_keepalives_es_error_pero_con_la_causa_correcta(server):
    """ANTES el diagnostico era 'el server contesto 200 sin SSE: 0 frames
    validos... ¿un proxy delante, u otro backend?' y la muestra que el propio
    mensaje imprimia lo desmentia: b': ping\\n\\n: ping\\n\\n'. El error esta
    bien; la causa estaba mal."""
    server.estado["modo"] = "solo_keepalives"
    resp = completar(MENSAJES, url=server.url, razonador=False,
                     on_token=lambda t: None)
    assert resp.ok is False, f"paso como exito: {resp}"
    assert "sin SSE" not in resp.error, (
        f"el transporte HABLO SSE y el error dice lo contrario: {resp.error}")
    assert "keepalive" in resp.error
    assert "2 comentarios" in resp.error
    assert "ping" in resp.error            # la muestra sigue estando


# -- on_tool_frag: el latido de un turno que ESCRIBE (2026-08-31) ---------------

def test_on_tool_frag_recibe_los_argumentos_del_tool_call():
    """Un paso del agente que escribe un fichero no manda `content` ni
    razonamiento: solo argumentos de tool call. Sin este callback el turno se
    veia mudo durante minutos y el contador de tokens del spinner marcaba 0."""
    from cognia.agent import chat_client as cc

    trozos = []
    acc = {"texto": [], "razon": [], "tcs": {}, "finish": "", "usage": {},
           "cortado": False, "malformados": 0, "frames": 0, "comentarios": 0,
           "muestra": b"", "timings": {}, "usage_estimado": False,
           "usage_via": ""}
    avisos = cc._Avisos()
    for pedazo in ('{"path": "a.html"', ', "contenido": "<html>"}'):
        linea = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                 '"id":"t1","function":{"name":"escribir_archivo",'
                 '"arguments":%s}}]}}]}' % json.dumps(pedazo)).encode("utf-8")
        cc._procesar_linea(linea, acc, None, None, avisos, trozos.append)
    assert "".join(trozos) == '{"path": "a.html", "contenido": "<html>"}'


def test_sin_on_tool_frag_el_camino_es_el_de_siempre():
    """El callback es OPT-IN: sin el, ni se calcula el fragmento."""
    from cognia.agent import chat_client as cc

    acc = {"texto": [], "razon": [], "tcs": {}, "finish": "", "usage": {},
           "cortado": False, "malformados": 0, "frames": 0, "comentarios": 0,
           "muestra": b"", "timings": {}, "usage_estimado": False,
           "usage_via": ""}
    linea = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"t1",'
             b'"function":{"name":"listar","arguments":"{}"}}]}}]}')
    assert cc._procesar_linea(linea, acc, None, None, cc._Avisos()) is False
    assert acc["tcs"]
