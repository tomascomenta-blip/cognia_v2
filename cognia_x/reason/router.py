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

from cognia_x.reason.chains import CHAINS, graded_chain
from cognia_x.reason.problems import is_correct


class Router:
    def __init__(self, chain_names, mode="verifier", eps=0.1, seed=0,
                 unsure_margin=0.05, ucb_c=0.0, graded=False):
        self.chain_names = list(chain_names)
        self.mode = mode
        self.eps = eps
        # CYCLE 15: graded=True corre las cadenas con competencia GRADUADA (patinan, más en lo difícil).
        # Por defecto False -> comportamiento de CYCLE 12/13 intacto (corre CHAINS exactas).
        self.graded = graded
        self.unsure_margin = unsure_margin
        self.ucb_c = ucb_c
        self.rng = Random(seed)
        # stats[type][chain] = [correct, total]  -> accuracy rastreada por (tipo, cadena)
        self.stats = {}
        self.questions = 0          # cuántas veces preguntó al usuario (oráculo)
        self.explore = True         # durante test se congela la exploración
        self.locked_map = {}        # CYCLE 13: tipo->cadena fijada por "confiar ciego" (blind-single)

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

    def run_chain(self, chain, problem):
        """Corre una cadena: GRADUADA (CYCLE 15, patina) si graded=True, exacta (CYCLE 12) si no."""
        if self.graded:
            return graded_chain(chain, problem)
        return CHAINS[chain](problem)

    def train_one(self, problem):
        """Un paso de entrenamiento online: elige cadena, corre, premia según el modo."""
        ptype = problem["type"]
        chain = self.select(ptype)
        pred, conf = self.run_chain(chain, problem)
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

    def deploy_chain(self, ptype):
        """Cadena a desplegar para un tipo: la FIJADA (blind) si existe, si no la mejor aprendida."""
        if ptype in self.locked_map:
            return self.locked_map[ptype]
        return self.select(ptype)

    # ============================================================================
    # CYCLE 13 — robustez en el régimen REALISTA (se agrega sin tocar lo de CYCLE 12).
    #   (A) oráculo RUIDOSO: a veces te contestan mal. Innovación: preguntá a VARIOS y
    #       quedate con lo que más se repite (voto mayoritario) + acumulá la señal ruidosa
    #       sobre muchos intentos (ley de los grandes números -> la política converge igual).
    #   (B) FUERA-DE-DISTRIBUCIÓN: un tipo nunca visto. El router "sabe que no sabe" (no tiene
    #       evidencia para ese tipo) -> ESCALA (pregunta) en vez de adivinar confiado.
    # ============================================================================

    def _noisy_oracle(self, problem, chain, rng, p_noise):
        """
        El "usuario" verifica si la cadena acertó, pero a veces contesta MAL.
        Con prob (1-p_noise) devuelve el veredicto real; con prob p_noise lo FLIPEA.
        WHY: modela "le preguntás a alguien y te contesta mal" sin tocar el verificador real.
        """
        truth = is_correct(problem, CHAINS[chain](problem)[0])
        if rng.random() < p_noise:
            return not truth          # contestó mal: invierte el veredicto
        return truth

    def _ood_unsure(self, ptype, min_obs):
        """
        Duda por FALTA DE EVIDENCIA: el router "sabe que no sabe" si para este tipo todavía no tiene
        evidencia que SEPARE a la mejor cadena de la segunda. Dos gatillos:
          - poca evidencia en la mejor cadena rastreada (< min_obs observaciones), o
          - las dos mejores están EMPATADAS (accuracy dentro del margen) -> no hay con qué decidir.
        Se dispara fuerte en un tipo NUEVO (0 obs, todo empatado) y se apaga al ir aprendiéndolo.
        """
        ranked = self._ranked(ptype)
        if len(ranked) < 2:
            return False
        top1, top2 = ranked[0], ranked[1]
        if self._total(ptype, top1) < min_obs:
            return True   # casi no vio este tipo: no tiene base -> pregunta
        # empate cerca del azar (ninguna cadena se destaca) -> sigue inseguro.
        # NOTA: dos cadenas AMBAS competentes (accuracy alta) empatadas NO es incertidumbre
        # (cualquiera resuelve) -> no escala por ese empate legítimo.
        tied = abs(self._acc(ptype, top1) - self._acc(ptype, top2)) <= self.unsure_margin
        return tied and self._acc(ptype, top1) < 0.75

    def _noisy_endorsed_chain(self, problem, rng, p_noise):
        """
        El oráculo ruidoso te dice CUÁL cadena usar para este problema: pregunta por cada cadena
        si acertó (con ruido) y devuelve la primera que aparece endosada. Si ninguna queda endosada,
        endosa una al azar. WHY: una sola respuesta puede señalar una cadena EQUIVOCADA.
        """
        endorsed = [c for c in self.chain_names
                    if self._noisy_oracle(problem, c, rng, p_noise)]
        if endorsed:
            return rng.choice(endorsed)
        return rng.choice(self.chain_names)

    def solve_noisy(self, problem, mode="aggregate", p_noise=0.0, k=5, rng=None):
        """
        Resuelve preguntando a un oráculo RUIDOSO y APRENDE de esa señal (ruidosa).
          mode="blind"     -> la PRIMERA vez que ve un tipo, pregunta UNA vez, se queda con la cadena
                              que el oráculo endosó y la FIJA para siempre (confía ciego). Si esa única
                              respuesta fue ruidosa -> aprende el mapa EQUIVOCADO y no se corrige.
          mode="aggregate" -> pregunta K veces por cada cadena, vota por MAYORÍA, y ACUMULA sobre todos
                              los intentos (ley de los grandes números: el promedio ruidoso converge a
                              la competencia real -> recupera el mapa correcto aunque cada voto falle).
        Devuelve (pred, correcto_real, chain_elegida).
        """
        if rng is None:
            rng = self.rng
        ptype = problem["type"]
        if mode == "blind":
            # confía ciego en UNA respuesta por tipo y la fija
            if ptype not in self.locked_map:
                self.locked_map[ptype] = self._noisy_endorsed_chain(problem, rng, p_noise)
            chain = self.locked_map[ptype]
        else:
            # robust-aggregate: K votos por cadena, acumula, y deja que la estadística decida
            for c in self.chain_names:
                votes = [1 if self._noisy_oracle(problem, c, rng, p_noise) else 0 for _ in range(max(1, k))]
                verdict = 1.0 if (sum(votes) / len(votes)) >= 0.5 else 0.0   # voto mayoritario
                self.update(ptype, c, verdict)
            chain = self.select(ptype)
        pred, _ = CHAINS[chain](problem)
        return pred, is_correct(problem, pred), chain

    def solve_ood(self, problem, ask_budget=0, min_obs=8, p_noise=0.0, k=5, rng=None):
        """
        Resuelve "sabiendo lo que no sabe": si tiene poca evidencia para este tipo (OOD) y queda
        presupuesto, ESCALA (pregunta al oráculo, posiblemente ruidoso, con voto mayoritario) y
        aprende; si ya tiene evidencia, despliega la mejor cadena conocida.
        Devuelve (pred, correcto_real, asked, budget_restante).
        """
        if rng is None:
            rng = self.rng
        ptype = problem["type"]
        asked = False
        if ask_budget > 0 and self._ood_unsure(ptype, min_obs):
            asked = True
            self.questions += 1
            ask_budget -= 1
            reps = max(1, k)
            for c in self.chain_names:
                votes = [1 if self._noisy_oracle(problem, c, rng, p_noise) else 0 for _ in range(reps)]
                verdict = 1.0 if (sum(votes) / len(votes)) >= 0.5 else 0.0
                self.update(ptype, c, verdict)
        chain = self.select(ptype)
        pred, _ = CHAINS[chain](problem)
        return pred, is_correct(problem, pred), asked, ask_budget
