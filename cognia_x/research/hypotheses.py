"""
hypotheses.py — HypothesisRegistry: falsabilidad + refutar-antes-de-aceptar + DoD, en código (§3).

POR QUÉ: la directiva v2 hereda del protocolo epistémico v1 que una hipótesis no se "acepta" ni se
"refuta" por gusto. mark_supported/mark_refuted lanzan PrematureVerdictError salvo que se cumpla TODO:
  - prediction no vacía            (es falsable: predice algo observable).
  - evidence_for >= 1              (hay algo a favor).
  - evidence_against >= 1          (se CONSIDERÓ evidencia en contra: refutar-antes-de-aceptar).
  - adversarial_verdict no vacío   (pasó por crítica adversaria).
  - experiment_ref no vacío        (afirmación empírica = experimento CORRIDO, no opinión).
Un experimento refutado cierra con status='refutada' + su lección; NUNCA se borra (append-only).

Escalabilidad obligatoria (§6):
- Complejidad temporal: add = O(1) amortizado (append). get(id) = O(n) (escanea el JSONL buscando id).
  mark_*: O(n) (get para validar/leer + un append del nuevo estado). Honesto: get es lineal, no índice.
- Complejidad espacial: O(1) por add. get carga una hipótesis a la vez (lee línea por línea), O(1)
  además del registro devuelto.
- Comportamiento en CPU: I/O-bound; comparaciones de strings/longitudes triviales en 2c/4t sin GPU.
- Multi-dispositivo: JSONL portable; "última escritura del id gana" al leer (estado más reciente).
- Distribución futura: merge append-only; get debe devolver el ÚLTIMO registro del id (estado vigente).
"""
import json
import os

from cognia_x.research.record import PermanentRecord
from cognia_x.research.schema import Hypothesis, to_dict, from_dict


class PrematureVerdictError(Exception):
    """Se lanza al marcar apoyada/refutada una hipótesis sin cumplir falsabilidad + DoD."""
    pass


class HypothesisRegistry:
    def __init__(self, path):
        self.record = PermanentRecord(path)

    def add(self, hyp):
        """Append una Hypothesis (journaleada). Devuelve la hipótesis."""
        d = to_dict(hyp) if isinstance(hyp, Hypothesis) else dict(hyp)
        self.record.journaled_append('hypotheses', d, key=d.get('id', ''))
        return from_dict(Hypothesis, d)

    def get(self, hid):
        """
        Devuelve el ESTADO VIGENTE (último registro escrito) de la hipótesis id, o None.
        O(n): escanea todo el JSONL; el último match gana (append-only = la última escritura es la vigente).
        """
        path = self.record.store_path('hypotheses')
        if not os.path.exists(path):
            return None
        found = None
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('id') == hid:
                    found = d
        return from_dict(Hypothesis, found) if found is not None else None

    def _check_dod(self, hyp):
        """Compuerta DoD compartida. Lanza PrematureVerdictError con el motivo exacto si falta algo."""
        missing = []
        if not (hyp.prediction or '').strip():
            missing.append("prediction vacía (no falsable)")
        if len(hyp.evidence_for) < 1:
            missing.append("evidence_for vacía")
        if len(hyp.evidence_against) < 1:
            missing.append("evidence_against vacía (no se consideró refutación)")
        if not (hyp.adversarial_verdict or '').strip():
            missing.append("adversarial_verdict vacío")
        if not (hyp.experiment_ref or '').strip():
            missing.append("experiment_ref vacío (afirmación empírica sin experimento corrido)")
        if missing:
            raise PrematureVerdictError(
                "Veredicto prematuro sobre '{}': {}".format(hyp.id, "; ".join(missing))
            )

    def _set_status(self, hid, status):
        hyp = self.get(hid)
        if hyp is None:
            raise PrematureVerdictError("Hipótesis '{}' no existe".format(hid))
        self._check_dod(hyp)
        hyp.status = status
        # append del nuevo estado (append-only: no mutamos líneas viejas, agregamos la vigente).
        self.record.journaled_append('hypotheses', to_dict(hyp), key=hid)
        return hyp

    def mark_supported(self, hid):
        """Marca status='apoyada' solo si cumple falsabilidad + refutar-antes + DoD; si no, lanza."""
        return self._set_status(hid, 'apoyada')

    def mark_refuted(self, hid):
        """Marca status='refutada' solo si cumple falsabilidad + refutar-antes + DoD; si no, lanza."""
        return self._set_status(hid, 'refutada')
