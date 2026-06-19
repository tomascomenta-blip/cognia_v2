"""
cli.py — vista de línea de comandos del Investigation Engine.

POR QUÉ: el engine debe ser inspeccionable sin abrir un REPL. `python -m cognia_x.research.cli <cmd>`:
  status  -> conteos de sources/decisions/hypotheses/ceilings + nº de límites asumidos.
  verify  -> corre record.verify_no_loss() e imprime OK/FAIL (exit 0/1) — "pérdida = fallo" chequeable.
  ceilings-> imprime los CeilingRecord registrados.
  assumed -> imprime el backlog de límites asumidos (invitación a refutar).
Usa un dir de datos por defecto cognia_x/research/store/ (lo crea si falta; gitignoreado).

Escalabilidad obligatoria (§6):
- Complejidad temporal: status/verify/ceilings/assumed son O(n) (escanean los JSONL del store).
- Complejidad espacial: O(1)..O(k) (cuentan por línea / acumulan solo lo que imprimen).
- Comportamiento en CPU: I/O-bound; trivial en 2c/4t sin GPU.
- Multi-dispositivo / distribución: opera sobre un dir de store JSONL portable, fusionable por concat.
"""
import argparse
import os
import sys

from cognia_x.research.record import PermanentRecord, count_lines
from cognia_x.research.ceiling import CeilingTracker

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'store')


def _safe_utf8():
    # POR QUÉ: en consolas Windows (cp1252) los acentos rompen; intentamos UTF-8 sin fallar si no se puede.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def cmd_status(store):
    rec = PermanentRecord(store)
    counts = {
        'sources': count_lines(rec.store_path('sources')),
        'decisions': count_lines(rec.store_path('decisions')),
        'hypotheses': count_lines(rec.store_path('hypotheses')),
        'ceilings': count_lines(rec.store_path('ceilings')),
    }
    assumed = len(CeilingTracker(store).assumed_limits())
    print("Investigation Engine — store: {}".format(store))
    for k in ('sources', 'decisions', 'hypotheses', 'ceilings'):
        print("  {:<11}: {}".format(k, counts[k]))
    print("  {:<11}: {}".format('asumidos', assumed))
    return 0


def cmd_verify(store):
    res = PermanentRecord(store).verify_no_loss()
    for d in res['details']:
        flag = 'OK' if d['ok'] else 'FAIL'
        print("  [{}] {:<11} journaled={} live={} missing={}".format(
            flag, d['store'], d['journaled'], d['live'], d.get('missing', 0)))
    if res['ok']:
        print("verify: OK (sin pérdida de conocimiento)")
        return 0
    print("verify: FAIL (un store tiene menos registros vivos que los journaleados)")
    return 1


def cmd_ceilings(store):
    recs = CeilingTracker(store)
    path = recs.record.store_path('ceilings')
    n = count_lines(path)
    print("ceilings registrados: {}".format(n))
    import json
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                print("  - [{}] {}: {}".format(
                    d.get('real_or_assumed', '?'), d.get('subsystem', '?'), d.get('known_limit', '')))
    return 0


def cmd_assumed(store):
    recs = CeilingTracker(store).assumed_limits()
    print("límites ASUMIDOS (backlog de refutación): {}".format(len(recs)))
    for r in recs:
        print("  - {}: {}".format(r.subsystem, r.known_limit))
    return 0


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cli',
                                description='Investigation Engine — vista CLI')
    p.add_argument('cmd', choices=['status', 'verify', 'ceilings', 'assumed'])
    p.add_argument('--store', default=DEFAULT_STORE, help='dir de datos (default: cognia_x/research/store/)')
    args = p.parse_args(argv)

    os.makedirs(args.store, exist_ok=True)
    if args.cmd == 'status':
        return cmd_status(args.store)
    if args.cmd == 'verify':
        return cmd_verify(args.store)
    if args.cmd == 'ceilings':
        return cmd_ceilings(args.store)
    if args.cmd == 'assumed':
        return cmd_assumed(args.store)
    return 2


if __name__ == '__main__':
    sys.exit(main())
