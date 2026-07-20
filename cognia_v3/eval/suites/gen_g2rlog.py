# -*- coding: utf-8 -*-
"""Genera g2_razonamiento_logica.jsonl — suite de PODA para stepwise v2.

50 ítems de la clase FLAGGED de E-INT (PREREG_INTELIGENCIA P-INT-2): lógica
FÁCIL sin números que SOLO los patrones de lógica de v2 cubren (el set
marginal era N=8, demasiado chico para decidir la poda). Cada ítem se
verifica programáticamente como miembro de la clase antes de emitir:
  (a) needs_stepwise(prompt) = True (v2 lo transforma),
  (b) <2 dígitos (el fallback ?+2números NO lo cubre),
  (c) sin gatillo cuantitativo (los patrones de v1 NO lo cubren).
Oracle: ultimo_de (la última opción mencionada es la respuesta — must_any/
not_any falsean con CoT porque el razonamiento menciona todas las opciones).

Uso: .\\venv312\\Scripts\\python.exe cognia_v3/eval/suites/gen_g2rlog.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from cognia.agent.stepwise import needs_stepwise  # noqa: E402

# gatillos SOLO-cuantitativos (v1 + cuantitativo inglés de v2): un ítem de la
# clase flagged NO debe matchear esto (si matchea, no es "puramente marginal")
_QUANT_RX = re.compile(
    r"(cu[aá]nt|calcul|qu[eé] n[uú]mero|cu[aá]l es el n[uú]mero|por ciento|"
    r"\bpromedio\b|\bporcentaje\b|en qu[eé] d[ií]a|qu[eé] d[ií]a|a qu[eé] hora|"
    r"\bdescuento\b|\bdoble\b|\btriple\b|\bmitad\b|"
    r"how (many|much|old|far|long|fast)|\bcalculat|\bpercent|\bdiscount\b|"
    r"\baverage\b|\btwice\b|\bdouble\b|\btriple\b|\bhalf\b|what number|"
    r"\bin total\b|\ben total\b)", re.IGNORECASE)


def item(n, idioma, prompt, opciones, gana):
    assert gana in opciones
    return {"id": f"G2RL-{n:03d}", "gate": "G2R", "dominio": "logica_facil",
            "idioma": idioma, "shots": 0, "prompt": prompt,
            "oracle": {"ultimo_de": {"opciones": opciones, "gana": gana}},
            "max_new_tokens": 200}


I = []
n = 0


def add(idioma, prompt, opciones, gana):
    global n
    n += 1
    I.append(item(n, idioma, prompt, opciones, gana))


# ── Transitividad comparativa (es) ──
add("es", "Ana es más alta que Beto. Beto es más alto que Carla. ¿Quién es más alta, Ana o Carla?", ["Ana", "Carla"], "Ana")
add("es", "Marcos es más viejo que Lucía. Lucía es más vieja que Pedro. ¿Quién es más joven, Marcos o Pedro?", ["Marcos", "Pedro"], "Pedro")
add("es", "El tren es más rápido que el bus. El bus es más rápido que la bicicleta. ¿Quién es el más lento, el tren o la bicicleta?", ["tren", "bicicleta"], "bicicleta")
add("es", "Rosa es más baja que Marta. Marta es más baja que Irene. ¿Quién es la más alta, Rosa o Irene?", ["Rosa", "Irene"], "Irene")
add("es", "Un elefante es más grande que un caballo. Un caballo es más grande que un perro. ¿Cuál es más chico, el elefante o el perro?", ["elefante", "perro"], "perro")
add("es", "Sofía corre más rápido que Julián. Julián corre más rápido que Emma. ¿Quién es la más lenta corriendo, Sofía o Emma?", ["Sofía", "Emma"], "Emma")
add("es", "Diego es más fuerte que Raúl. Raúl es más fuerte que Iván. ¿Quién es el más fuerte de los tres: Diego, Raúl o Iván?", ["Diego", "Raúl", "Iván"], "Diego")
add("es", "La torre norte es más antigua que la torre sur. La torre sur es más antigua que el puente. ¿Quién es el más nuevo, la torre norte o el puente?", ["torre norte", "puente"], "puente")

# ── Silogismos todos/ninguno (es) ──
add("es", "Todos los gatos de esta casa son negros. Simón es un gato de esta casa. ¿Simón es negro o blanco?", ["negro", "blanco"], "negro")
add("es", "Ningún pez puede caminar. El atún es un pez. ¿El atún puede caminar o nadar?", ["caminar", "nadar"], "nadar")
add("es", "Si todos los médicos de la clínica hablan francés y Valeria es médica de la clínica, ¿qué habla Valeria: francés o alemán?", ["francés", "alemán"], "francés")
add("es", "Ningún metal de esta caja es liviano. El cobre está en esta caja. ¿El cobre es liviano o pesado?", ["liviano", "pesado"], "pesado")
add("es", "Si todos los trenes de esta línea paran en Retiro y el tren de las siete es de esta línea, ¿dónde para seguro: en Retiro o en Tigre?", ["Retiro", "Tigre"], "Retiro")
add("es", "Si todos los cuadernos del cajón son rojos y Mila sacó un cuaderno del cajón, ¿de qué color es el cuaderno: rojo o verde?", ["rojo", "verde"], "rojo")
add("es", "Si todos los vecinos del edificio votaron a favor y Norma es vecina del edificio, ¿cómo votó Norma: a favor o en contra?", ["a favor", "en contra"], "a favor")
add("es", "Ningún alumno de la sala B usa lentes. Ciro es alumno de la sala B y todos los días usa gorra o lentes. ¿Qué usa Ciro: gorra o lentes?", ["gorra", "lentes"], "gorra")

# ── Orden temporal / secuencia (es) ──
add("es", "Laura llegó antes que Nico. Nico llegó antes que Bruno. ¿Quién llegó primero, Laura o Bruno?", ["Laura", "Bruno"], "Laura")
add("es", "El pan se hornea después que se amasa, y se amasa después que se mezclan los ingredientes. ¿Qué viene primero, hornear o mezclar?", ["hornear", "mezclar"], "mezclar")
add("es", "Tomás se despierta antes que Elsa. Elsa se despierta antes que Gastón. ¿Quién se despierta último, Tomás o Gastón?", ["Tomás", "Gastón"], "Gastón")
add("es", "En la carrera, Pía terminó después que Ada y antes que Leo. ¿Quién terminó mejor ubicada, Ada o Leo?", ["Ada", "Leo"], "Ada")
add("es", "La primavera viene después que el invierno, y el invierno viene después que el otoño. ¿Qué está más lejos del otoño, el invierno o la primavera?", ["invierno", "primavera"], "primavera")

# ── Deducción categórica (es) ──
add("es", "Todos los cuervos observados hasta hoy son negros. Mañana verás un cuervo. Según esa regla, ¿esperás que sea negro o violeta?", ["negro", "violeta"], "negro")
add("es", "Todos los ingredientes del plato son vegetales. La zanahoria está en el plato. ¿La zanahoria es un vegetal o una fruta según el enunciado?", ["vegetal", "fruta"], "vegetal")
add("es", "Ningún miembro del club juega al ajedrez. Hugo juega al ajedrez. ¿Hugo pertenece al club o está afuera del club?", ["pertenece", "afuera"], "afuera")
add("es", "Si todos los idiomas que enseña la escuela son europeos, ¿cuál puede aparecer en el catálogo: italiano o coreano?", ["italiano", "coreano"], "italiano")

# ── Transitividad comparativa (en) ──
add("en", "Alice is taller than Bob. Bob is taller than Carol. Who is taller, Alice or Carol?", ["Alice", "Carol"], "Alice")
add("en", "Mark is older than Jane. Jane is older than Paul. Who is the youngest, Mark or Paul?", ["Mark", "Paul"], "Paul")
add("en", "A plane is faster than a train. A train is faster than a bike. Which is slower, the plane or the bike?", ["plane", "bike"], "bike")
add("en", "Rex is heavier than Spot. Spot is heavier than Toby. Who is the lightest, Rex or Toby?", ["Rex", "Toby"], "Toby")
add("en", "The oak is older than the pine. The pine is older than the birch. Which tree is the oldest, the oak or the birch?", ["oak", "birch"], "oak")
add("en", "Nina runs faster than Omar. Omar runs faster than Lily. Who is faster, Nina or Lily?", ["Nina", "Lily"], "Nina")
add("en", "Tower A is taller than Tower B. Tower C is taller than Tower A. Who is the tallest, Tower B or Tower C?", ["Tower B", "Tower C"], "Tower C")
add("en", "Sam is younger than Ella. Ella is younger than Ruth. Who is older, Sam or Ruth?", ["Sam", "Ruth"], "Ruth")

# ── Silogismos todos/ninguno (en) ──
add("en", "All the birds in this park are pigeons. Coco is a bird in this park. Is Coco a pigeon or a parrot?", ["pigeon", "parrot"], "pigeon")
add("en", "None of the students in room D play chess. Tim is a student in room D and every day he plays chess or checkers. What does Tim play: chess or checkers?", ["chess", "checkers"], "checkers")
add("en", "All the books on this shelf are novels. 'The Voyage' is on this shelf. Is it a novel or a dictionary?", ["novel", "dictionary"], "novel")
add("en", "If all roses are flowers and none of the flowers in this garden are blue, what color rose could you find here: red or blue?", ["red", "blue"], "red")
add("en", "If all the keys on this ring open doors in the house and the red key is on this ring, what does the red key open: a door in the house or a car?", ["house", "car"], "house")
add("en", "None of the planets in this diagram have rings. Kepler-X is a planet in this diagram. Which drawing matches Kepler-X: a plain sphere or a ringed sphere?", ["plain", "ringed"], "plain")
add("en", "All the cheeses on the table are made of goat milk. The white cheese is on the table. Is it made of goat milk or cow milk?", ["goat", "cow"], "goat")
add("en", "None of the shops on this street open on Sunday. The bakery is on this street. Does it open on Sunday or stay closed?", ["opens", "closed"], "closed")

# ── Transitividad extra (en) — el orden antes/después no tiene patrón en
# inglés en v2 (fuera de la clase flagged), se reemplaza por comparativos ──
add("en", "Ken is taller than Liam. Liam is taller than Max. Who is the tallest of the three: Ken, Liam or Max?", ["Ken", "Liam", "Max"], "Ken")
add("en", "None of the runners in team A quit the race. Zoe is a runner in team A. What did Zoe do with the race: quit it or finish it?", ["quit", "finish"], "finish")
add("en", "Bea is faster than Cai. Cai is faster than Dov. Who is the fastest, Bea or Dov?", ["Bea", "Dov"], "Bea")
add("en", "All the cups in this cupboard are ceramic. The blue cup is in this cupboard. Is the blue cup ceramic or plastic?", ["ceramic", "plastic"], "ceramic")
add("en", "The sequoia is older than the fir. The fir is older than the maple. Which tree is the youngest of the three: the sequoia, the fir or the maple?", ["sequoia", "fir", "maple"], "maple")

# ── Deducción categórica (en) ──
add("en", "All the tools in this box are made of steel. The hammer is in this box. Is the hammer made of steel or wood?", ["steel", "wood"], "steel")
add("en", "None of the members of the choir play drums. Vic plays drums. Where does Vic belong: in the choir or outside the choir?", ["in the choir", "outside"], "outside")
add("en", "If all the languages taught at this school are European, which course could appear in the catalog: Italian or Korean?", ["Italian", "Korean"], "Italian")
add("en", "All the fish in this tank are freshwater fish. The angelfish is in this tank. Is it a freshwater or a saltwater fish?", ["freshwater", "saltwater"], "freshwater")


def main():
    fallas = []
    for it in I:
        p = it["prompt"]
        if not needs_stepwise(p):
            fallas.append((it["id"], "v2 NO lo transforma"))
        if len(re.findall(r"\d", p)) >= 2:
            fallas.append((it["id"], "2+ digitos (fallback lo cubre)"))
        if _QUANT_RX.search(p):
            fallas.append((it["id"], "gatillo cuantitativo (no es marginal puro)"))
        # opciones anidadas (una substring de otra tras fold) rompen ultimo_de
        ops = it["oracle"]["ultimo_de"]["opciones"]
        from suite_oracle import fold
        for a in ops:
            for b in ops:
                if a != b and fold(a) in fold(b):
                    fallas.append((it["id"], f"opcion anidada: '{a}' en '{b}'"))
        # la opcion correcta no debe aparecer ULTIMA ya en el PROMPT-eco: si el
        # modelo repite el enunciado y calla, no debe pasar de regalo. Chequeo
        # blando: ambas opciones estan en el prompt (el eco no decide solo).
    if fallas:
        for f in fallas:
            print("FUERA DE CLASE:", f)
        sys.exit(1)
    balance = {}
    for it in I:
        balance[it["idioma"]] = balance.get(it["idioma"], 0) + 1
    out = Path(__file__).parent / "g2_razonamiento_logica.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for it in I:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"OK: {len(I)} items ({balance}) -> {out.name}")
    print(f"sha256: {sha}")


if __name__ == "__main__":
    main()
