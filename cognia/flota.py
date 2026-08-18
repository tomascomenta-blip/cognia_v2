"""
cognia/flota.py — la logica de servir_flota como modulo DEL PAQUETE.

POR QUE EXISTE (WP6 2026-08-09): scripts/ no viaja en el wheel, asi que un
`pip install cognia-ai` dejaba al usuario sin manera de levantar la flota que
el propio doctor le pedia arrancar. La logica de combos vive aca (importable
tanto instalado como en el repo) y scripts/servir_flota.py DELEGA en este
modulo — sin duplicar, que era como el :8088 sirvio un modelo retirado
durante semanas (dos fuentes de verdad, memoria del repo 2026-07-25).

    cognia flota arrancar [combo] [patron]   # levanta el combo (default: pensar)
    cognia flota estado                      # que GGUF REAL sirve cada puerto
    cognia flota parar [--todos]             # para la flota por PID (--todos: la maquina entera)
    cognia flota dormir                      # duerme roles con idle vencido (summoner)
    cognia flota liberar <rol>               # duerme un rol del summoner por PID
    cognia flota ctx <N> [cache]             # relanza el cerebro a una celda MEDIDA

Los combos reusan scripts/servir_modelo.py y servir_vlm.py (eleccion de
binario/modelo NO duplicada). Esos scripts solo existen en un checkout del
repo o un editable install: si no estan, arrancar falla con la explicacion
honesta en vez de degradar en silencio.

Solo stdlib + cognia.backend_activo (que tambien es solo stdlib).
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# combo -> lista de (script, args). El orden importa: el cerebro primero.
# Regla de VRAM (16GB): en el lazo conviven a lo sumo un 14B-clase (~9GB) +
# VL-3B (~3.2GB). gpt-oss-20b (13.7GB) y VL-7B corren SOLOS.
COMBOS = {
    "construir": [
        ("servir_modelo.py", []),                             # coder-14b + draft
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "construir-ui": [
        # UIGEN como cerebro TOTAL del lazo (vision + html + reparaciones).
        # ctx 12288 y no 8192: UIGEN piensa largo ANTES del HTML y con 8k el
        # fence salia truncado aunque max_tokens fuera 12000 (medido
        # 2026-07-25). KV a 12k ~2.2GB: cabe con VL-3B (~14GB).
        ("servir_modelo.py", ["--modelo", "UIGEN", "--sin-draft",
                              "--ctx", "12288"]),
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "pensar": [
        # ctx 16384 y no 8192: gpt-oss-20b es un modelo de RAZONAMIENTO y con
        # 8192 cortaba tareas reales por la mitad (finish_reason='length' a
        # los 7931 tokens, medido 2026-07-25: pass@1 25% con 8192 contra 100%
        # con 16384 en el mismo banco). Cabe: 12.2 GB de 16.3, corre solo.
        ("servir_modelo.py", ["--modelo", "gpt-oss", "--sin-draft",
                              "--ctx", "16384"]),
    ],
    "pensar-qwythos": [
        # CEREBRO PRINCIPAL desde 2026-08-09 (pedido del dueño). Qwythos-9B
        # (Qwen3.5 abliterado, 1M ctx) hace tool-calling NATIVO servido con
        # --jinja — verificado a mano: finish_reason=tool_calls, arguments
        # JSON. ctx 32768 y no el 8192 default: es un razonador (piensa fuerte
        # antes de responder) y 8192 lo cortaba; a 8192 usa 6.75 GB de 16.3,
        # asi que 32768 (~4 GB mas de KV) cabe holgado y corre SOLO.
        # QWEN3.5 Y NO QWEN2.5 (corregido 2026-08-17, leido del GGUF con
        # cognia.agent.gguf_meta): general.architecture='qwen35',
        # general.base_model.0.name='Qwen3.5 9B', context_length=1048576 (yarn
        # 4.0 sobre 262144) y 33 bloques de los que solo 9 llevan attn_k — los
        # otros 24 son SSM. Lo decia mal aca y en model_profiles.py:65; ver
        # ahi el fallo que costo de verdad (COGNIA_THINKING mudo).
        ("servir_modelo.py", ["--modelo", "qwythos", "--sin-draft",
                              "--ctx", "32768"]),
    ],
    "pensar-en-lazo": [
        ("servir_modelo.py", ["--modelo", "OpenReasoning", "--sin-draft"]),
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "pensar-nemotron": [
        # CEREBRO ALTERNATIVO (2026-08-14). Nemotron 3.5 Lightning 30B-A3B:
        # MoE hibrido Mamba2 con ventana NATIVA de 1.048.576 tokens, MEDIDA
        # entera en esta maquina (prompt real de 1.046.706 tokens, aguja
        # recuperada, 14.622 MiB de VRAM de los 16.311).
        # Sin --ctx aca a proposito: servir_modelo.PERFILES_ARRANQUE le pone
        # el millon con los flags medidos (KV q8_0, --no-mmap, batch 4096 /
        # ubatch 1024 = +59% de prefill). Poner un --ctx aca lo pisaria.
        # Que corre despacio es parte del trato: 508 tok/s de prefill al
        # millon y ~14 tok/s de generacion a esa profundidad. Para el uso
        # normal del agente el RLM sale 229x mas barato (medido el mismo dia,
        # mismo pajar: 9 s y 4.728 tokens contra 2.061 s y 1.046.706).
        ("servir_modelo.py", ["--modelo", "nemotron-3.5", "--sin-draft"]),
    ],
    "pensar-qwen38": [
        # Qwen3.8-27B Ridge (2026-08-18). Denso 27,78B hibrido: de sus 64
        # bloques solo 16 llevan atencion completa (full_attention_interval=4),
        # los otros 48 son Gated-DeltaNet -> el KV es de 16 capas, no de 64.
        # Corre SOLO: 11,73 GiB de pesos de los 15,9 disponibles.
        # Sin --ctx aca a proposito, igual que pensar-nemotron: los flags
        # (ctx, KV, MTP) los pone servir_modelo.PERFILES_ARRANQUE con lo
        # MEDIDO en esta maquina, y un --ctx aca los pisaria.
        ("servir_modelo.py", ["--modelo", "Ridge"]),
    ],
    "juzgar": [
        ("servir_vlm.py", ["--modelo", "VL-7B"]),
    ],
    # Modo MODELO UNICO: un solo GGUF en :8080 hace todo. El patron del
    # modelo se agrega en main() (argv extra); --sin-draft porque el draft
    # 0.5b solo ayuda a la familia coder.
    "solo": [
        ("servir_modelo.py", ["--sin-draft"]),
    ],
}

# El combo que arranca `cognia flota arrancar` sin argumento: el CEREBRO
# PRINCIPAL. Desde 2026-08-09 es Qwythos-9B (pedido del dueño); gpt-oss-20b
# sigue disponible como combo 'pensar' para quien lo quiera o para reproducir
# los bancos b1_* que lo mapean por nombre.
COMBO_DEFAULT = "pensar-qwythos"

PUERTOS = ((8080, "cerebro/pensador"), (8081, "VLM/arbitro"))

# Los puertos que esta flota puede parar por PID. 8082 es el worker del
# summoner (llama chico para hijos RLM): tambien es nuestro, y el martillo
# global se lo llevaba por delante sin nombrarlo. Fuera de esta lista no se
# mata nada: los jobs (8096-8099) no son llama-server y se apagan por su
# propio /apagar desde summoner.liberar().
PUERTOS_LLAMA = (8080, 8081, 8082)

# Trozo (en minusculas) del nombre del GGUF -> combo que lo sirve en :8080.
# Para que el doctor/estado puedan decir no solo QUE modelo responde sino a
# QUE combo esperado corresponde (o que no corresponde a ninguno: la averia
# historica del :8088 era exactamente un server rancio con otro modelo).
# OJO CON EL ORDEN: el match es por substring y gana el PRIMERO que case, asi
# que lo especifico va ANTES que lo generico. 'nemotron' a secas mapeaba a
# 'pensar-en-lazo' (por OpenReasoning-Nemotron-14B) y con el 3.5 instalado
# habria dicho que el cerebro de 30B es el combo del 14B: el mismo modo de
# fallo que la averia del :8088 (un server rancio atribuido al combo que no es).
CEREBROS = {
    "qwythos": "pensar-qwythos",
    "gpt-oss": "pensar",
    "uigen": "construir-ui",
    "openreasoning": "pensar-en-lazo",
    "nemotron-3.5": "pensar-nemotron",
    # 'qwen3.8' y no 'qwen3': el 'qwen3' corto se llevaria Qwen3-1.7B y
    # Qwen3-4B-Thinking, que no son cerebros de este combo. Sexta vez que el
    # substring corto intenta robar; combo_de_modelo() ordena por longitud.
    "qwen3.8": "pensar-qwen38",
    "nemotron": "pensar-en-lazo",
    "qwen2.5-coder-14b": "construir",
}


def combo_de_modelo(nombre_gguf: str) -> Optional[str]:
    """A que combo pertenece el GGUF servido en :8080, o None si a ninguno.

    De patron MAS LARGO a mas corto. Iterar en orden de inserccion hacia que
    el resultado dependiera de en que linea escribio alguien su entrada: hoy
    'nemotron-3.5' esta ANTES de 'nemotron' por suerte, y con las claves al
    reves un Nemotron 3.5 caia en 'pensar-en-lazo' (el combo del
    OpenReasoning-14B, otro modelo y otro contexto viable). model_profiles y
    servir_modelo ya ordenaban asi; esta tabla era la que faltaba."""
    bajo = (nombre_gguf or "").lower()
    for trozo in sorted(CEREBROS, key=len, reverse=True):
        if trozo in bajo:
            return CEREBROS[trozo]
    return None


def _scripts_dir() -> Optional[Path]:
    """Donde viven servir_modelo.py / servir_vlm.py.

    Solo en un checkout del repo (o editable install, que apunta al repo):
    cognia/ y scripts/ son hermanos. En un wheel normal no estan — se
    devuelve None y arrancar() lo explica en vez de reventar con un
    FileNotFoundError criptico."""
    candidato = Path(__file__).resolve().parent.parent / "scripts"
    if (candidato / "servir_modelo.py").is_file():
        return candidato
    return None


def _responde(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def props_puerto(puerto: int) -> dict:
    """{'modelo', 'n_ctx', 'puerto'} del server en ese puerto, {} si no
    responde. forzar=True: el cache de backend_activo miente tras un
    reinicio en el mismo puerto, y estado/doctor quieren el AHORA."""
    from cognia import backend_activo
    return backend_activo.props(f"http://127.0.0.1:{puerto}", forzar=True)


def _cmd_kill(pid: int) -> list:
    """Kill SELECTIVO, por PID. El martillo por nombre de imagen vive SOLO en
    _parar_todos(), detras de la opcion explicita --todos."""
    if os.name == "nt":
        return ["taskkill", "/PID", str(pid), "/F"]
    return ["kill", "-TERM", str(pid)]


def _parar_todos() -> int:
    """El martillo GLOBAL por nombre de imagen: mata TODOS los llama-server de
    la maquina, sean o no de esta flota. Queda disponible (a veces es lo que
    uno quiere: limpiar restos de una corrida vieja) pero SOLO si se pide con
    `cognia flota parar --todos`. Nunca se dispara solo."""
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"],
                           capture_output=True, text=True)
    else:
        r = subprocess.run(["pkill", "-f", "llama-server"],
                           capture_output=True, text=True)
    print("Detenidos TODOS los llama-server de la maquina."
          if r.returncode == 0 else "No habia llama-server vivo.")
    return 0


def parar(todos: bool = False) -> int:
    """Detiene los llama-server DE LA FLOTA: puerto por puerto y por PID.

    POR QUE (2026-08-13): esto era un `taskkill` por nombre de imagen, es
    decir un martillo que mata a TODOS los llama-server de la maquina — y
    arrancar() lo disparaba solo al cambiar de combo (:217-219). En esta
    maquina conviven corridas ajenas en el mismo binario: matar por nombre se
    lleva por delante el cerebro de otro proceso sin decir una palabra. Ahora
    se enumera por puerto con cognia.puertos.pid_llama_del_puerto (que exige
    loopback exacto Y que el proceso sea un llama-server: tailscaled tambien
    escucha en el :8080 de la IP de la malla) y se mata con kill por PID.

    Lo que ocupa un puerto de la flota SIN ser un llama-server se AVISA y no
    se toca: matar a ciegas es peor que la averia que se esta arreglando.
    `todos=True` (CLI: --todos) recupera el martillo global, explicito."""
    if todos:
        return _parar_todos()
    from cognia import puertos
    matados, fallidos, ajenos = [], [], []
    for puerto in PUERTOS_LLAMA:
        pid = puertos.pid_llama_del_puerto(puerto)
        if pid is None:
            otro = puertos.pid_del_puerto(puerto)
            if otro is not None:
                ajenos.append((puerto, otro))
            continue
        r = subprocess.run(_cmd_kill(pid), capture_output=True, text=True)
        (matados if r.returncode == 0 else fallidos).append((puerto, pid))
    for puerto, pid in matados:
        print(f"  :{puerto} detenido (pid {pid}).")
    for puerto, pid in fallidos:
        print(f"  :{puerto}: no pude matar el pid {pid} (permisos?).",
              file=sys.stderr)
    for puerto, pid in ajenos:
        print(f"  :{puerto} lo ocupa el pid {pid} y NO es un llama-server: "
              f"no lo toco.")
    if not matados:
        print("No habia llama-server de la flota vivo."
              + ("" if not fallidos else " (hubo kills fallidos)"))
    return 0


def estado() -> int:
    """Que responde en cada puerto y QUE GGUF sirve de verdad (via /props).

    Antes solo decia RESPONDE/no responde: un server rancio sirviendo otro
    modelo era invisible — la averia del :8088 con el 7B retirado."""
    for puerto, rol in PUERTOS:
        p = props_puerto(puerto)
        if not p:
            print(f"  :{puerto} ({rol}): no responde")
            continue
        modelo = p.get("modelo") or "desconocido"
        combo = combo_de_modelo(modelo)
        extra = f" [combo '{combo}']" if combo else ""
        ctx = p.get("n_ctx")
        ctx_txt = f", ctx {ctx}" if ctx else ""
        print(f"  :{puerto} ({rol}): RESPONDE — {modelo}{ctx_txt}{extra}")
    # Bloque ADITIVO (ola 2): roles del summoner. Import perezoso y protegido:
    # sin summoner (o con su estado ilegible) el estado clasico de puertos ya
    # se imprimio intacto — se avisa, jamas se degrada en silencio. Salida
    # ASCII: la consola del dueno es cp1252 (estado_roles ya lo garantiza).
    try:
        from cognia import summoner
        lineas = summoner.estado_roles()
    except Exception as e:
        print(f"  (roles del summoner no disponibles: {e})")
        return 0
    print("  roles (summoner):")
    for rol_s, linea in lineas.items():
        print(f"    {rol_s:8s} {linea}")
    return 0


def arrancar(modo: str, patron: str = "") -> int:
    """Levanta el combo `modo`. `patron` solo aplica al modo 'solo'."""
    if modo not in COMBOS:
        print(f"Combo desconocido: {modo!r}. Validos: "
              f"{sorted(COMBOS) + ['parar', 'estado']}", file=sys.stderr)
        return 1
    if patron and modo != "solo":
        print(f"El combo {modo!r} no lleva argumentos extra.", file=sys.stderr)
        return 1

    scripts = _scripts_dir()
    if scripts is None:
        print("No encuentro scripts/servir_modelo.py: los combos se sirven "
              "desde un checkout del repo (o un editable install: "
              "pip install -e <repo>). En una instalacion pip normal arranca "
              "el server a mano o fija COGNIA_LLM_URL.", file=sys.stderr)
        return 1

    combo = COMBOS[modo]
    if modo == "solo" and patron:
        # patron de modelo elegido por el usuario (match por substring en
        # servir_modelo.elegir): "solo qwythos", "solo gpt-oss", etc.
        combo = [(script, ["--modelo", patron] + args)
                 for script, args in combo]

    # Cambiar de combo con restos del anterior = OOM confuso. Se para primero,
    # pero SOLO lo de la flota y por PID (2026-08-13): este mismo camino
    # disparaba el martillo global y mataba llama-servers ajenos que nadie
    # habia pedido tocar.
    if _responde(8080) or _responde(8081):
        print("Habia servidores vivos: los detengo antes del combo nuevo.")
        parar()

    for script, args in combo:
        orden = [sys.executable, str(scripts / script)] + args
        print(f"-> {script} {' '.join(args)}")   # ascii: la consola es cp1252
        r = subprocess.run(orden)
        if r.returncode != 0:
            print(f"{script} fallo (codigo {r.returncode}); no sigo con el "
                  f"combo a medias.", file=sys.stderr)
            return r.returncode
    print(f"\nCombo '{modo}' listo.")
    estado()
    return 0


def main(argv: Optional[list] = None) -> int:
    """CLI: acepta tanto `cognia flota <accion>` como la forma historica del
    script (`servir_flota.py <combo>`), para no romper la memoria muscular."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 1
    accion = argv[0]
    if accion == "parar":
        # --todos = el martillo global (todos los llama-server de la maquina).
        # Sin el, solo se paran los puertos de la flota y por PID.
        return parar(todos="--todos" in argv[1:])
    if accion == "estado":
        return estado()
    if accion == "arrancar":
        modo = argv[1] if len(argv) > 1 else COMBO_DEFAULT
        if len(argv) == 1:
            print(f"(combo por defecto: {COMBO_DEFAULT})")
        return arrancar(modo, patron=argv[2] if len(argv) > 2 else "")
    # Acciones ADITIVAS (ola 2) que despachan al summoner con import perezoso.
    # Cada una avisa y devuelve 1 si el summoner no esta: degradacion visible.
    if accion == "dormir":
        try:
            from cognia import summoner
        except Exception as e:
            print(f"summoner no disponible: {e}", file=sys.stderr)
            return 1
        dormidos = summoner.barrido()
        print("Dormidos por inactividad: "
              + (", ".join(dormidos) if dormidos else "ninguno"))
        return 0
    if accion == "liberar":
        if len(argv) < 2:
            print("Uso: cognia flota liberar <rol>", file=sys.stderr)
            return 1
        try:
            from cognia import summoner
        except Exception as e:
            print(f"summoner no disponible: {e}", file=sys.stderr)
            return 1
        if summoner.liberar(argv[1]):
            print(f"Rol '{argv[1]}' liberado.")
            return 0
        print(f"Rol '{argv[1]}' no estaba vivo (o no se pudo liberar).")
        return 1
    if accion == "ctx":
        if len(argv) < 2 or not argv[1].isdigit():
            print("Uso: cognia flota ctx <N> [cache]", file=sys.stderr)
            return 1
        try:
            from cognia import summoner
        except Exception as e:
            print(f"summoner no disponible: {e}", file=sys.stderr)
            return 1
        try:
            r = summoner.escalar_ctx(int(argv[1]),
                                     cache=argv[2] if len(argv) > 2 else "")
        except Exception as e:
            # SummonerError ya salio por stderr + bus dentro del summoner;
            # se repite corto aca para que el exit code tenga su porque.
            print(f"escalar_ctx fallo: {e}", file=sys.stderr)
            return 1
        print(f"Cerebro en n_ctx {r.get('n_ctx')} cache {r.get('cache')}"
              + (" (relanzado)" if r.get("relanzado") else " (ya alcanzaba)"))
        return 0
    # Forma historica: el combo directo como primer argumento.
    if accion in COMBOS:
        return arrancar(accion, patron=argv[1] if len(argv) > 1 else "")
    print(f"Accion desconocida: {accion!r}. Usa: arrancar [combo] | estado | "
          f"parar [--todos] | dormir | liberar <rol> | ctx <N> [cache]  "
          f"(combos: {sorted(COMBOS)})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
