"""
ceiling.py — CeilingTracker: techo teórico por subsistema, real vs asumido (§5).

POR QUÉ: la directiva manda, por subsistema, registrar el límite conocido, qué lo impide, clasificar
cada bloqueo en físico/diseño/histórico, y separar límite REAL (probado) de ASUMIDO (heredado sin
prueba). "Un límite asumido es una invitación a refutar, no una pared." assumed_limits() devuelve el
BACKLOG de refutación: todos los CeilingRecord marcados 'asumido'.

Escalabilidad obligatoria (§6):
- Complejidad temporal: add = O(b) con b = nº de bloqueos del registro (valida cada kind); el append
  es O(1) amortizado. assumed_limits = O(n) (escanea todo el JSONL filtrando por 'asumido').
- Complejidad espacial: add = O(1). assumed_limits = O(a) con a = nº de límites asumidos devueltos;
  lee línea por línea, no carga el histórico entero en memoria de golpe.
- Comportamiento en CPU: I/O-bound; validaciones de membresía en sets, triviales en 2c/4t sin GPU.
- Multi-dispositivo: JSONL portable.
- Distribución futura: merge append-only; assumed_limits se recomputa sobre el histórico fusionado.
"""
import json
import os

from cognia_x.research.record import PermanentRecord
from cognia_x.research.schema import CeilingRecord, to_dict, from_dict

VALID_KINDS = {'fisico', 'diseno', 'historico'}
VALID_REAL_OR_ASSUMED = {'real', 'asumido'}


class CeilingTracker:
    def __init__(self, path):
        self.record = PermanentRecord(path)

    def add(self, rec):
        """
        Append un CeilingRecord (journaleado). Valida que cada blocker.kind esté en {fisico,diseno,
        historico} y que real_or_assumed esté en {real,asumido}; ValueError si no. Devuelve el registro.
        """
        d = to_dict(rec) if isinstance(rec, CeilingRecord) else dict(rec)

        roa = d.get('real_or_assumed', '')
        if roa not in VALID_REAL_OR_ASSUMED:
            raise ValueError(
                "real_or_assumed inválido: {!r} (debe ser uno de {})".format(roa, sorted(VALID_REAL_OR_ASSUMED))
            )
        blockers = d.get('blockers', []) or []
        # POR QUÉ: §5 manda CLASIFICAR qué impide el límite. Un techo sin ningún bloqueo clasificado
        # registraría "qué impide" en blanco; la validación por-bloqueo no alcanza si la lista es vacía.
        if not blockers:
            raise ValueError(
                "CeilingRecord '{}' requiere >=1 blocker clasificado (§5: clasificar qué impide el "
                "límite en fisico/diseno/historico).".format(d.get('subsystem', '?'))
            )
        for b in blockers:
            kind = b.get('kind') if isinstance(b, dict) else None
            if kind not in VALID_KINDS:
                raise ValueError(
                    "blocker.kind inválido: {!r} (debe ser uno de {})".format(kind, sorted(VALID_KINDS))
                )

        self.record.journaled_append('ceilings', d, key=d.get('subsystem', ''))
        return from_dict(CeilingRecord, d)

    def assumed_limits(self):
        """Devuelve los CeilingRecord marcados 'asumido' (el backlog de refutación). O(n)."""
        path = self.record.store_path('ceilings')
        out = []
        if not os.path.exists(path):
            return out
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('real_or_assumed') == 'asumido':
                    out.append(from_dict(CeilingRecord, d))
        return out
