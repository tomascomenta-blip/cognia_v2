"""
c56_vram_serializa.py — ¿cuanto cuesta REALMENTE consultar al pensador?

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\c56_vram_serializa.py

LA AFIRMACION A FALSEAR (razon 5.6): "la VRAM serializa lo que un MoE
paraleliza; consultar al pensador en medio de la construccion no es una llamada,
es descargar un modelo de la GPU y cargar otro: segundos a decenas de segundos
por consulta. En la practica el sistema no lo hace, y por eso el constructor
construye sin pensar".

El dueno la reformulo bien: "es un COSTE DE SWAP, no un limite". Esto lo mide.

TRES CONDICIONES, mismo trabajo (construir + 2 consultas al pensador):

  A) SIN CONSULTA   — el constructor solo. La linea base: lo que hace hoy.
  B) CON SWAP       — para cada consulta se descarga el constructor y se carga
                      el pensador grande (gpt-oss-20b), se pregunta, y se
                      vuelve. Es lo que costaria hacerlo con la flota actual.
  C) RESIDENTE      — un pensador PEQUENO (Qwen3-4B-Thinking, 2.33GB) vive en
                      un segundo puerto junto al constructor. Consultar es una
                      llamada HTTP, sin mover un byte.

Presupuesto de VRAM (16GB): coder-14b ~9GB + Qwen3-4B ~2.4GB = ~11.4GB. Entra.
Por eso la condicion C es POSIBLE, y por eso la pregunta del dueno era la
correcta: el limite no es la VRAM, es que nadie monto el pensador chico.

Solo mide TIEMPO. La calidad de la consulta es otro experimento.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PUERTO_CEREBRO = 8080
PUERTO_PENSADOR = 8082          # el chico residente, fuera del 8080/8081 de la flota

CONSULTA = ("En una pagina web de un juego de memoria, ¿en que estado deben "
            "estar las cartas al cargar y por que? Responde en dos frases.")
CONSTRUCCION = ("Escribe el HTML de un boton que incrementa un contador. "
                "Solo el bloque de codigo.")


def _responde(puerto: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _flota(modo: str) -> float:
    t0 = time.time()
    subprocess.run([sys.executable, str(RAIZ / "scripts" / "servir_flota.py"),
                    modo], capture_output=True, text=True)
    return time.time() - t0


def _servir_chico() -> float:
    """Levanta el pensador pequeno en :8082 SIN tocar el cerebro de :8080."""
    t0 = time.time()
    subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "servir_modelo.py"),
         "--modelo", "Qwen3-4B-Thinking", "--sin-draft",
         "--puerto", str(PUERTO_PENSADOR), "--ctx", "4096"],
        capture_output=True, text=True)
    return time.time() - t0


def _preguntar(puerto: int, prompt: str, max_tokens: int = 200) -> tuple[str, float]:
    cuerpo = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2, "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{puerto}/v1/chat/completions", data=cuerpo,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
        txt = d["choices"][0]["message"]["content"]
    except Exception as exc:
        txt = f"ERROR {exc}"
    return txt, time.time() - t0


def main(argv: list) -> int:
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 2
    filas = []

    print("Preparando: combo 'construir' en :8080 ...", flush=True)
    _flota("construir")
    if not _responde(PUERTO_CEREBRO):
        print("no hay cerebro en :8080", file=sys.stderr)
        return 1

    # ── A) sin consulta ───────────────────────────────────────────────────
    print(f"\n[A] SIN CONSULTA  (el constructor solo, n={n})", flush=True)
    for i in range(n):
        _, s = _preguntar(PUERTO_CEREBRO, CONSTRUCCION, 400)
        filas.append({"cond": "A_sin_consulta", "rep": i, "total_s": s,
                      "swap_s": 0.0, "consulta_s": 0.0})
        print(f"  r{i}: {s:.1f}s", flush=True)

    # ── C) pensador chico residente ───────────────────────────────────────
    print(f"\n[C] RESIDENTE  (Qwen3-4B-Thinking en :{PUERTO_PENSADOR})",
          flush=True)
    carga = _servir_chico()
    if not _responde(PUERTO_PENSADOR):
        print(f"  no arranco el pensador chico en :{PUERTO_PENSADOR} "
              f"(¿cabe en VRAM junto al 14B?). Salto la condicion C.",
              file=sys.stderr)
        residente_ok = False
    else:
        residente_ok = True
        print(f"  carga UNICA del pensador chico: {carga:.1f}s "
              f"(se paga una vez, no por consulta)", flush=True)
        for i in range(n):
            t0 = time.time()
            _, c1 = _preguntar(PUERTO_PENSADOR, CONSULTA, 200)
            _, cons = _preguntar(PUERTO_CEREBRO, CONSTRUCCION, 400)
            _, c2 = _preguntar(PUERTO_PENSADOR, CONSULTA, 200)
            tot = time.time() - t0
            filas.append({"cond": "C_residente", "rep": i, "total_s": tot,
                          "swap_s": 0.0, "consulta_s": c1 + c2})
            print(f"  r{i}: {tot:.1f}s  (2 consultas: {c1 + c2:.1f}s, "
                  f"swap: 0s)", flush=True)
        subprocess.run(["taskkill", "/F", "/FI",
                        f"WINDOWTITLE eq *{PUERTO_PENSADOR}*"],
                       capture_output=True)

    # ── B) con swap al pensador grande ────────────────────────────────────
    print(f"\n[B] CON SWAP  (descargar el 14B, cargar gpt-oss-20b, y volver)",
          flush=True)
    for i in range(n):
        t0 = time.time()
        s1 = _flota("pensar")
        _, c1 = _preguntar(PUERTO_CEREBRO, CONSULTA, 200)
        s2 = _flota("construir")
        _, cons = _preguntar(PUERTO_CEREBRO, CONSTRUCCION, 400)
        s3 = _flota("pensar")
        _, c2 = _preguntar(PUERTO_CEREBRO, CONSULTA, 200)
        s4 = _flota("construir")
        tot = time.time() - t0
        filas.append({"cond": "B_con_swap", "rep": i, "total_s": tot,
                      "swap_s": s1 + s2 + s3 + s4, "consulta_s": c1 + c2})
        print(f"  r{i}: {tot:.1f}s  (2 consultas: {c1 + c2:.1f}s, "
              f"4 swaps: {s1 + s2 + s3 + s4:.1f}s)", flush=True)

    # ── tabla ─────────────────────────────────────────────────────────────
    def med(cond, campo):
        v = [f[campo] for f in filas if f["cond"] == cond]
        return sum(v) / len(v) if v else 0.0

    print(f"\n\n{'=' * 78}")
    print("5.6 — ¿CUANTO CUESTA CONSULTAR AL PENSADOR? (medido, n=%d)" % n)
    print("=" * 78)
    print(f"{'CONDICION':<34}{'TOTAL':>12}{'de eso SWAP':>16}{'consultas':>14}")
    print("-" * 78)
    for cond, etiq in (("A_sin_consulta", "A) sin consultar (hoy)"),
                       ("C_residente", "C) pensador chico RESIDENTE"),
                       ("B_con_swap", "B) con swap al 20B")):
        if not any(f["cond"] == cond for f in filas):
            print(f"{etiq:<34}{'NO MEDIDO':>12}")
            continue
        print(f"{etiq:<34}{med(cond, 'total_s'):>11.1f}s"
              f"{med(cond, 'swap_s'):>15.1f}s{med(cond, 'consulta_s'):>13.1f}s")
    print("-" * 78)

    if residente_ok:
        b, c = med("B_con_swap", "total_s"), med("C_residente", "total_s")
        ahorro = b - c
        print(f"\n  Mantener residente al pensador chico ahorra {ahorro:.1f}s "
              f"por ciclo de 2 consultas")
        print(f"  ({ahorro / b:.0%} del tiempo de la condicion con swap).")
        print(f"\n  La VRAM no impedia consultar al pensador: coder-14b (~9GB) + "
              f"Qwen3-4B (~2.4GB)\n  entran juntos en los 16GB. Lo que faltaba "
              f"era montarlo, no la memoria.")

    salida = RAIZ / "cognia" / "program_creator" / "generated_programs" / "c56_vram.json"
    salida.write_text(json.dumps(filas, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
