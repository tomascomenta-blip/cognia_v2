"""
record.py — PermanentRecord: "la pérdida de conocimiento es un fallo del sistema" (§7).

POR QUÉ: la directiva v2 manda registro append-only y verificable. Este módulo es la PIEZA común:
- append_jsonl(path, obj): la única forma de escribir en el engine (todos los stores la usan).
- PermanentRecord(dirpath): journaliza CADA escritura del engine en journal.jsonl, y ofrece
  verify_no_loss() que reconstruye desde el journal la IDENTIDAD de cada registro añadido
  (store + key + hash sha256 del contenido) y comprueba que CADA UNO siga vivo como línea del
  archivo real. Si falta una identidad journaleada, ok=False. Así "pérdida de conocimiento = fallo"
  es CHEQUEABLE por CONTENIDO, no por conteo: un borrado compensado por un add no relacionado
  (delete+add) ya NO pasa desapercibido. Honestidad sobre los límites:
  - El check asume archivos NO compactados, de crecimiento monótono (append-only). Una compactación
    legítima (descartar líneas de estado superado de un registro versionado para dejar solo el
    estado vigente) eliminaría hashes journaleados y haría ok=False; eso requiere re-baselinear el
    journal, no es un bug del check.
  - Registros versionados (p.ej. hypotheses, que appendean una nueva línea por transición de estado):
    cada estado es un add journaleado con su propio hash, así que TODOS los estados históricos deben
    seguir presentes. Esto es consistente con append-only.

Escalabilidad obligatoria (§6):
- Complejidad temporal: append = O(1) amortizado (open en modo 'a' + una línea). verify_no_loss =
  O(n) sobre el total de líneas (journal + stores): un barrido lineal del histórico (recomputa un
  hash sha256 por línea). Honesto: NO es O(1).
- Complejidad espacial: append = O(1) (una línea en RAM). verify_no_loss = O(h) con h = nº de hashes
  vivos por store (un set de hashes por store que se escanea); lee línea por línea, no parsea de más.
- Comportamiento en CPU: I/O-bound (disco), no CPU-bound; trivial en 2c/4t sin GPU.
- Multi-dispositivo: JSONL es portable; copiar el dir a otro nodo conserva el journal y los stores.
- Distribución futura: para fusionar histórico de varios nodos, concatenar journals + stores y
  re-verificar (la verificación tolera append-only; un merge nunca debe REDUCIR un store).
"""
import hashlib
import json
import os


def _content_hash(obj):
    """sha256 estable del contenido de un registro (json canónico, sort_keys). stdlib, O(tamaño obj)."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def append_jsonl(path, obj):
    """Append una línea JSON a path (lo crea si falta). O(1) amortizado. Devuelve obj."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')
    return obj


def count_lines(path):
    """Cuenta líneas no vacías de un JSONL (registros vivos). O(n), O(1) memoria."""
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _now():
    # POR QUÉ guarda con try/except: dentro de un workflow puede no haber reloj fiable; en CLI normal
    # time.time() está bien. Nunca fabricamos un timestamp falso: si falla, queda el placeholder.
    try:
        import time
        return time.time()
    except Exception:
        return None


class PermanentRecord:
    def __init__(self, dirpath):
        self.dirpath = dirpath
        os.makedirs(dirpath, exist_ok=True)
        self.journal_path = os.path.join(dirpath, 'journal.jsonl')

    def store_path(self, store):
        """Ruta del archivo JSONL de un store nombrado (sources, decisions, ...)."""
        return os.path.join(self.dirpath, store + '.jsonl')

    def journaled_append(self, store, obj, key=''):
        """Escribe obj en el store Y registra la operación en el journal. La forma canónica de escribir.

        El journal guarda la IDENTIDAD de contenido (hash sha256 del obj) además de store/op/key, para
        que verify_no_loss compruebe presencia POR CONTENIDO y no solo por conteo de líneas.
        """
        append_jsonl(self.store_path(store), obj)
        append_jsonl(self.journal_path, {
            'ts_placeholder': _now(),
            'store': store,
            'op': 'add',
            'key': key,
            'hash': _content_hash(obj),
        })
        return obj

    def _live_hashes(self, store):
        """Set de hashes de contenido de las líneas vivas de un store. O(n) tiempo, O(h) memoria."""
        path = self.store_path(store)
        hashes = set()
        if not os.path.exists(path):
            return hashes
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                hashes.add(_content_hash(obj))
        return hashes

    def verify_no_loss(self):
        """
        Reconstruye desde el journal la IDENTIDAD (store + hash de contenido) de cada registro añadido
        y comprueba que CADA UNO siga vivo como línea del archivo real. ok=False si falta alguna
        identidad journaleada. A diferencia de un chequeo por conteo, esto detecta delete+add: borrar
        un registro y añadir otro no relacionado deja el conteo igual pero el hash borrado ya no está.

        Compat: eventos de journal viejos SIN campo 'hash' (de antes de este cambio) caen al chequeo por
        conteo para ese store (no podemos verificar contenido de lo que no journaleó su hash); se honra
        así el histórico previo sin reescribirlo.
        """
        # store -> {'hashes': set(...), 'legacy_count': int} acumulado desde el journal.
        expected = {}
        if os.path.exists(self.journal_path):
            with open(self.journal_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if ev.get('op') != 'add':
                        continue
                    store = ev.get('store', '?')
                    bucket = expected.setdefault(store, {'hashes': set(), 'legacy_count': 0})
                    h = ev.get('hash')
                    if h:
                        bucket['hashes'].add(h)
                    else:
                        bucket['legacy_count'] += 1

        details = []
        ok = True
        for store, bucket in sorted(expected.items()):
            live_hashes = self._live_hashes(store)
            missing_hashes = bucket['hashes'] - live_hashes
            n_live = count_lines(self.store_path(store))
            # journaled = registros con identidad de contenido + los legacy contados sin hash.
            n_journaled = len(bucket['hashes']) + bucket['legacy_count']
            # Falta contenido si algún hash journaleado no está vivo, O si (legacy) hay encogimiento neto.
            content_ok = len(missing_hashes) == 0
            legacy_ok = n_live >= n_journaled
            store_ok = content_ok and legacy_ok
            if not store_ok:
                ok = False
            details.append({
                'store': store,
                'journaled': n_journaled,
                'live': n_live,
                'missing': len(missing_hashes),
                'ok': store_ok,
            })
        return {'ok': ok, 'details': details}
