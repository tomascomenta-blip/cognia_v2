"""
CYCLE 14 — COMPOSER: aprender a ENCADENAR cadenas (un pequeño "programa de razonamiento").

La brecha honesta que dejaban CYCLE 12/13: todo problema se resolvía con UNA sola cadena. Acá los
problemas son COMPUESTOS: ninguna cadena de un paso alcanza; hay que ENCADENAR dos (o tres) operaciones
donde el OUTPUT del paso 1 es la ENTRADA del paso 2. El programa es una tupla ordenada de cadenas,
p.ej. ("unit_rate","backwards"). La IA NO sabe a priori cuál sirve: la DESCUBRE probando y verificando.

Construido SOBRE la lección central del lab (CYCLE 12): el programa se elige con el VERIFICADOR REAL
(la realidad), no con la confianza auto-reportada (circular -> secuestrable por el fanfarrón).

Modelo de ejecución (concreto):
  - Un programa es una tupla de nombres de STEP_CHAINS, longitud 1..max_len.
  - run_program corre las cadenas en orden, pasando el valor de cada paso como `intermediate` al siguiente.
  - La predicción final del programa = el valor que sale del ÚLTIMO paso.
  - Score = verificador real (is_correct) sobre problemas de entrenamiento.

El "brazo" del bandit ahora es una SECUENCIA, no una sola cadena (misma idea de CYCLE 12, espacio más
grande pero chico: con 5 step-chains hay 5 + 25 = 30 programas de longitud<=2, explorable a mano).
"""
from itertools import product
from random import Random

from cognia_x.reason.chains import STEP_CHAINS
from cognia_x.reason.problems import is_correct


def run_program(problem, program):
    """
    Ejecuta un PROGRAMA (tupla de nombres de step-chains) encadenando intermedios.
    Paso 1 corre con intermediate=None; cada paso siguiente recibe el valor del anterior.
    Devuelve (prediccion_final, confianza_minima_del_camino).
    """
    intermediate = None
    conf = 1.0
    pred = 0.0
    for name in program:
        pred, c = STEP_CHAINS[name](problem, intermediate)
        conf = min(conf, c)           # la confianza del programa es la del eslabón más débil
        intermediate = pred           # el output de este paso alimenta al siguiente
    return pred, conf


def enumerate_programs(max_len=2, names=None):
    """Todos los programas de longitud 1..max_len sobre las step-chains (el espacio de búsqueda)."""
    names = list(names) if names is not None else list(STEP_CHAINS)
    progs = []
    for L in range(1, max_len + 1):
        progs.extend(product(names, repeat=L))
    return progs


class Composer:
    """
    Bandit contextual sobre PROGRAMAS (secuencias de cadenas), indexado por TIPO de problema compuesto.
    Aprende online qué SECUENCIA funciona para cada tipo. mode controla la señal de recompensa:
      mode="verifier"   -> recompensa = verificador REAL (camino correcto, no circular).
      mode="confidence" -> recompensa = confianza auto-reportada del programa (circular / Goodhart):
                           un programa con un paso fanfarrón (step_direct, conf ~0.95) se auto-premia
                           aunque la respuesta compuesta sea incorrecta -> secuestra la política.
    """

    def __init__(self, max_len=2, mode="verifier", eps=0.15, seed=0, names=None):
        self.programs = enumerate_programs(max_len, names)
        self.mode = mode
        self.eps = eps
        self.rng = Random(seed)
        self.explore = True
        # stats[type][program] = [reward_acumulada, total]  -> accuracy/score rastreado por (tipo, programa)
        self.stats = {}

    def _row(self, ptype):
        if ptype not in self.stats:
            self.stats[ptype] = {prog: [0.0, 0] for prog in self.programs}
        return self.stats[ptype]

    def _score(self, ptype, prog):
        r, t = self._row(ptype)[prog]
        return r / t if t > 0 else 0.0

    def select(self, ptype):
        """epsilon-greedy sobre los PROGRAMAS de ese tipo: explora secuencias temprano, explota la mejor."""
        row = self._row(ptype)
        if self.explore and self.rng.random() < self.eps:
            return self.rng.choice(self.programs)
        best, best_score = None, -1.0
        for prog in self.programs:
            s = self._score(ptype, prog)
            if s > best_score:
                best, best_score = prog, s
        return best

    def update(self, ptype, prog, reward):
        row = self._row(ptype)
        row[prog][0] += reward
        row[prog][1] += 1

    def train_one(self, problem):
        """Un paso online: elige un programa, lo EJECUTA y lo premia segun el modo (verifier o confidence)."""
        ptype = problem["type"]
        prog = self.select(ptype)
        pred, conf = run_program(problem, prog)
        if self.mode == "verifier":
            reward = 1.0 if is_correct(problem, pred) else 0.0
        elif self.mode == "confidence":
            reward = float(conf)      # circular: el programa se premia con su propia confianza
        else:
            raise ValueError(f"modo desconocido: {self.mode}")
        self.update(ptype, prog, reward)
        return prog, pred

    def best_program_per_type(self):
        return {t: self._ranked(t)[0] for t in self.stats}

    def _ranked(self, ptype):
        return sorted(self.programs, key=lambda prog: self._score(ptype, prog), reverse=True)

    def deploy(self, ptype):
        """Programa a desplegar para un tipo: el mejor aprendido (exploracion congelada en eval)."""
        return self.select(ptype)
