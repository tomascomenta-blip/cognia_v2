"""Validacion e2e del BoN-live-loop: corre varias tareas de codigo por /hacer y
verifica que la funcion generada es CORRECTA (ejecuta asserts). Prueba que el
wire (generar_codigo determinista + short-circuit) produce codigo correcto de
forma robusta, no solo en el smoke de es_primo.

(2026-07-16) TODO el flujo vive bajo el guard __main__: este modulo viaja en
el wheel y antes ejecutaba la corrida LIVE completa AL IMPORTARSE (instanciaba
Cognia, spawneaba llama-server y borraba factorial.py/fib.py/... del cwd del
usuario) — cazado cuando un import-walk de auditoria disparo la corrida.
"""
import sys, os, importlib.util

TASKS = [
    ("factorial.py", "Escribe una funcion factorial(n) recursiva que devuelva n! (factorial(0)=1)",
     "factorial", [(0,1),(5,120),(6,720)]),
    ("fib.py", "Crea una funcion fib(n) que devuelva el n-esimo numero de Fibonacci (fib(0)=0, fib(1)=1)",
     "fib", [(0,0),(1,1),(10,55)]),
    ("es_palindromo.py", "Genera una funcion es_palindromo(s) que devuelva True si el string s se lee igual al derecho y al reves",
     "es_palindromo", [("ana",True),("hola",False),("",True)]),
    ("mcd.py", "Escribe una funcion mcd(a, b) que devuelva el maximo comun divisor de a y b",
     "mcd", [(12,8,4),(17,5,1),(100,75,25)]),
]


def pf(msg): pass  # silencio los pasos internos


def main():
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    os.environ["COGNIA_AGENT_WORKSPACE"] = os.getcwd()
    from cognia.cognia import Cognia
    from cognia.cli import _run_agent_task

    ai = Cognia()
    results = []
    for fname, task, fn, cases in TASKS:
        try: os.remove(fname)
        except Exception: pass
        print(f"\n=== {fn} ===", flush=True)
        _run_agent_task(ai, task, pf, max_steps=6)
        ok, detail = False, "sin archivo"
        if os.path.exists(fname):
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], fname)
                mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
                f = getattr(mod, fn)
                passed = all(f(*c[:-1]) == c[-1] for c in cases)
                ok, detail = passed, f"{'todos' if passed else 'FALLA'} los casos {cases[:2]}"
            except Exception as e:
                detail = f"error: {type(e).__name__}: {str(e)[:80]}"
        print(f"  {fn}: {'PASS' if ok else 'FAIL'} -- {detail}", flush=True)
        results.append((fn, ok, detail))
        try: os.remove(fname)
        except Exception: pass

    n_ok = sum(1 for _,ok,_ in results if ok)
    print(f"\n=== BON-LIVE-BATCH: {n_ok}/{len(results)} funciones correctas via el agente ===", flush=True)
    for fn, ok, d in results: print(f"  [{'OK' if ok else 'XX'}] {fn}: {d}", flush=True)


if __name__ == "__main__":
    main()
