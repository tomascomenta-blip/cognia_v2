"""
CYCLE 12 — router: la POLÍTICA META-RAZONADORA aprendida (la innovación).

Un bandit contextual sobre cadenas, indexado por TIPO de problema. Aprende "qué forma de razonar
funciona para qué clase de problema". Lo que ENTRENA al router es la clave:
  mode="verifier"   -> recompensa = el verificador REAL (la realidad). El camino correcto.
  mode="confidence" -> recompensa = la confianza AUTO-reportada de la cadena (circular / Goodhart):
                       el fanfarrón (chain_direct, siempre ~0.95) secuestra la política.

Además: "preguntarle al usuario" bajo PRESUPUESTO. Cuando el router está genuinamente DUDOSO para un
tipo (las dos mejores cadenas tienen accuracy rastreada muy cerca) y queda presupuesto, consulta al
oráculo (el verificador) UNA vez, elige la cadena confirmada y descuenta presupuesto. La buena política
pregunta MUCHO temprano y MENOS con el tiempo (a medida que aprende), manteniendo el accuracy alto.
"""
import math
from random import Random

from cognia_x.reason.chains import CHAINS
from cognia_x.reason.problems import is_correct


class Router:
    def __init__(self, chain_names, mode="verifier", eps=0.1, seed=0,
                 unsure_margin=0.05, ucb_c=0.0):
        self.chain_names = list(chain_names)
        self.mode = mode
        self.eps = eps
        self.unsure_margin = unsure_margin
        self.ucb_c = ucb_c
        self.rng = Random(seed)
        # stats[type][chain] = [correct, total]  -> accuracy rastreada por (tipo, cadena)
        self.stats = {}
        self.questions = 0          # cuántas veces preguntó al usuario (oráculo)
        self.explore = True         # durante test se congela la exploración

    def _row(self, ptype):
        if ptype not in self.stats:
            self.stats[ptype] = {c: [0, 0] for c in self.chain_names}
        return self.stats[ptype]

    def _acc(self, ptype, chain):
        c, t = self._row(ptype)[chain]
        return c / t if t > 0 else 0.0

    def _total(self, ptype, chain):
        return self._row(ptype)[chain][1]

    def select(self, ptype):
        """epsilon-greedy (con UCB opcional) sobre las cadenas de ese tipo: explora temprano, explota después."""
        row = self._row(ptype)
        if self.explore and self.rng.random() < self.eps:
            return self.rng.choice(self.chain_names)
        n_type = sum(row[c][1] for c in self.chain_names) + 1
        best, best_score = None, -1.0
        for c in self.chain_names:
            score = self._acc(ptype, c)
            if self.ucb_c > 0.0:
                t = row[c][1]
                bonus = self.ucb_c * math.sqrt(math.log(n_type) / t) if t > 0 else 1e9
                score += bonus
            if score > best_score:
                best, best_score = c, score
        return best

    def update(self, ptype, chain, reward):
        """reward = 1.0 correcto / 0.0 incorrecto (verifier) o la confianza reportada (confidence)."""
        row = self._row(ptype)
        row[chain][0] += reward
        row[chain][1] += 1

    def _ranked(self, ptype):
        row = self._row(ptype)
        return sorted(self.chain_names, key=lambda c: self._acc(ptype, c), reverse=True)

    def _is_unsure(self, ptype):
        """Duda genuina: las dos mejores cadenas tienen accuracy rastreada dentro de un margen chico."""
        ranked = self._ranked(ptype)
        if len(ranked) < 2:
            return False
        top1, top2 = ranked[0], ranked[1]
        # si no hay datos suficientes para distinguirlas, también está dudoso
        if self._total(ptype, top1) < 2 or self._total(ptype, top2) < 2:
            return True
        return abs(self._acc(ptype, top1) - self._acc(ptype, top2)) <= self.unsure_margin

    def train_one(self, problem):
        """Un paso de entrenamiento online: elige cadena, corre, premia según el modo."""
        ptype = problem["type"]
        chain = self.select(ptype)
        pred, conf = CHAINS[chain](problem)
        if self.mode == "verifier":
            reward = 1.0 if is_correct(problem, pred) else 0.0
        elif self.mode == "confidence":
            reward = float(conf)        # circular: la cadena se premia a sí misma con su propia confianza
        else:
            raise ValueError(f"modo desconocido: {self.mode}")
        self.update(ptype, chain, reward)
        return chain, pred

    def solve(self, problem, ask_budget=0):
        """
        Resuelve un problema. Corre la cadena seleccionada; si el router está DUDOSO para este tipo y
        queda presupuesto, "le pregunta al usuario" = consulta el oráculo (verificador) UNA vez, elige
        la cadena que el oráculo confirma, descuenta presupuesto y registra la pregunta.
        Devuelve (pred, correcto, asked, budget_restante).
        """
        ptype = problem["type"]
        asked = False
        if ask_budget > 0 and self._is_unsure(ptype):
            # PREGUNTAR: probar las cadenas y quedarnos con una que el oráculo confirme
            asked = True
            self.questions += 1
            ask_budget -= 1
            confirmed = None
            for c in self.chain_names:
                pred, _ = CHAINS[c](problem)
                ok = is_correct(problem, pred)
                # aprovechamos la consulta para ACTUALIZAR lo aprendido (el oráculo es señal real)
                self.update(ptype, c, 1.0 if ok else 0.0)
                if ok and confirmed is None:
                    confirmed = (c, pred)
            if confirmed is not None:
                chain, pred = confirmed
                return pred, True, asked, ask_budget
            # ninguna acertó: caemos al mejor conocido
        chain = self.select(ptype)
        pred, _ = CHAINS[chain](problem)
        ok = is_correct(problem, pred)
        return pred, ok, asked, ask_budget

    def best_chain_per_type(self):
        return {t: self._ranked(t)[0] for t in self.stats}
