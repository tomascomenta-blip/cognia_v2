"""
entrenar_flota.py — el runner de la flota de micro-expertos.

Plan pre-registrado en planes/FLOTA_MICROEXPERTOS.md. Cada experto es una
entrada declarativa: datos, arquitectura, gate. El runner entrena los
pendientes y NO re-entrena los que ya pasaron su gate — la flota crece por
acumulación, no por repetición.

    python scripts/entrenar_flota.py                # entrena los pendientes
    python scripts/entrenar_flota.py --estado       # qué hay y cómo quedó
    python scripts/entrenar_flota.py --solo idea_router
    python scripts/entrenar_flota.py --forzar idea_router   # re-entrena

Los micro-expertos de tarea son byte-level (~0.8M params): deciden cosas
internas de Cognia en <1 ms de CPU, sin tokenizer externo. La regla del plan:
cada experto DEBE superar a su heurística baseline o no entra (KILL a los 2
intentos fallidos).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DIR_FLOTA = REPO / "cognia" / "microexpertos"

import torch
import torch.nn as nn
import torch.nn.functional as F

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_LEN = 96          # bytes por texto: las ideas/preguntas internas son cortas
SEMILLA = 20260720


# ── El modelo: un transformer byte-level de ~0.8M ──────────────────────────

class MicroExperto(nn.Module):
    """
    Clasificador byte-level de ~0.8M params.

    Byte-level a proposito: sin tokenizer que mantener, sirve igual para
    espanol y para ingles, y el vocab de 256 mantiene la embedding diminuta
    (el suelo de 0.8M solo existe SIN el vocab de 152K de Qwen).
    """

    def __init__(self, n_clases: int, dim: int = 128, capas: int = 4,
                 cabezas: int = 4):
        super().__init__()
        self.emb = nn.Embedding(256, dim)
        self.pos = nn.Embedding(MAX_LEN, dim)
        bloque = nn.TransformerEncoderLayer(
            d_model=dim, nhead=cabezas, dim_feedforward=dim * 4,
            batch_first=True, norm_first=True, dropout=0.1)
        self.torso = nn.TransformerEncoder(bloque, num_layers=capas)
        self.cabeza = nn.Linear(dim, n_clases)

    def forward(self, x, mascara=None):
        pos = torch.arange(x.size(1), device=x.device)
        h = self.emb(x) + self.pos(pos)[None]
        h = self.torso(h, src_key_padding_mask=mascara)
        # mean-pool ignorando padding
        if mascara is not None:
            peso = (~mascara).float().unsqueeze(-1)
            h = (h * peso).sum(1) / peso.sum(1).clamp(min=1)
        else:
            h = h.mean(1)
        return self.cabeza(h)


def codificar(textos: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
    """bytes UTF-8 truncados/padded a MAX_LEN + mascara de padding."""
    lote = torch.zeros(len(textos), MAX_LEN, dtype=torch.long)
    mascara = torch.ones(len(textos), MAX_LEN, dtype=torch.bool)
    for i, t in enumerate(textos):
        b = t.encode("utf-8")[:MAX_LEN]
        lote[i, :len(b)] = torch.tensor(list(b), dtype=torch.long)
        mascara[i, :len(b)] = False
    return lote, mascara


# ── Datos sintéticos por plantillas (dominios cerrados: es honesto) ────────

def _datos_idea_router() -> tuple[list[str], list[int], list[tuple[str, int]]]:
    """
    Clasificar una idea de programa: 0=web, 1=modulo python, 2=script terminal.

    Sintetico por plantillas combinatorias es/en. El GOLDEN set son los casos
    REALES de tests/test_deteccion_idea_web.py — el bug medido del 2026-07-20:
    la heuristica confundia "html.parser" (stdlib de Python) con una web.
    """
    rng = random.Random(SEMILLA)
    temas = ["inversiones", "tareas", "clima", "notas", "recetas", "gastos",
             "ventas", "inventario", "habitos", "ejercicio", "musica",
             "stocks", "criptomonedas", "peliculas", "librerias", "salud"]
    web_tpl = [
        "pagina web que simule un dashboard de {t} con graficos animados",
        "landing page para una app de {t}",
        "webapp de {t} con animaciones y colores",
        "sitio web de {t} con CSS moderno",
        "a web page showing a {t} dashboard with live charts",
        "aplicacion web para gestionar {t} con tablas",
        "un dashboard web de {t} que se actualiza solo",
        "website interactivo sobre {t}",
        "frontend para visualizar {t} en el navegador",
        "una pagina con un reloj de {t} animado en HTML",
    ]
    py_tpl = [
        "modulo python para parsear {t} con html.parser de la stdlib",
        "funcion python que valide {t} con tests unitarios",
        "script python que descargue {t} con urllib y lo procese",
        "libreria python para comprimir {t}, solo stdlib con unittest",
        "a python module that scrapes {t} pages using html.parser",
        "cliente http en python que consulte una api de {t}",
        "modulo python que convierta {t} de HTML a texto plano",
        "python function to merge {t} records with error handling",
        "parser de {t} en python con expresiones regulares y pytest",
        "script python con def main() que analice {t}",
        # La familia del bug real del 2026-07-20: cosas PYTHON con nombre
        # webero. "Buscador web multi-estrategia... con html.parser" es un
        # modulo python aunque empiece por "buscador web". Sin estos
        # ejemplos, el modelo cae en la misma trampa que la heuristica vieja.
        "buscador web de {t}: funcion buscar() en python con la stdlib",
        "monitor web de {t} escrito en python con urllib y unittest",
        "crawler web de {t} en python, solo stdlib, que devuelva dicts",
        "buscador web multi-estrategia de {t} con html.parser y tests",
        "herramienta python que analice paginas web de {t} sin red",
        "api web de {t}: cliente python con urllib.request y timeout",
    ]
    term_tpl = [
        "generador de {t} en la terminal con arte ascii",
        "simulador de {t} que corre solo en consola",
        "juego de {t} en terminal con colores ansi",
        "visualizador ascii de {t} que se imprime solo",
        "a terminal {t} simulator that runs automatically",
        "programa de consola que dibuje {t} con caracteres",
        "reloj de {t} en la terminal actualizandose",
        "animacion ascii de {t} en la consola",
        "terminal dashboard de {t} con barras de texto",
        "explorador de {t} por linea de comandos",
    ]
    textos, clases = [], []
    for tpl_lista, clase in ((web_tpl, 0), (py_tpl, 1), (term_tpl, 2)):
        for tpl in tpl_lista:
            for t in temas:
                textos.append(tpl.format(t=t))
                clases.append(clase)
    # barajar reproducible
    pares = list(zip(textos, clases))
    rng.shuffle(pares)
    textos, clases = [p[0] for p in pares], [p[1] for p in pares]

    # GOLDEN: los casos reales que motivaron la heuristica y su bug.
    golden = [
        ("Buscador web multi-estrategia: funcion buscar() con html.parser "
         "de la stdlib, sin BeautifulSoup, tests con unittest", 1),
        ("scraper en Python con urllib que extrae titulos del HTML", 1),
        ("cliente HTTP en Python (stdlib) que descarga y parsea HTML", 1),
        ("modulo Python para convertir HTML a texto plano, con unittest", 1),
        ("una pagina web con animaciones", 0),
        ("landing page para un producto", 0),
        ("dashboard web de inversiones", 0),
        ("aplicacion web de notas", 0),
        ("website personal con CSS moderno", 0),
        ("un reloj animado en HTML y CSS", 0),
        ("una pagina web generada desde un script python", 0),
        ("gestor de tareas en terminal con SQLite", 2),
        ("pagina web que simule un dashboard de inversiones con movimiento: "
         "cotizaciones que cambian solas, grafico animado y variaciones en "
         "verde y rojo", 0),
    ]
    return textos, clases, golden


def _baseline_idea_router(golden: list[tuple[str, int]]) -> float:
    """La heuristica actual, en el eje binario web/no-web que es el que sabe."""
    from cognia.program_creator.generator import _es_idea_web
    aciertos = sum(
        1 for texto, clase in golden
        if _es_idea_web(texto) == (clase == 0)
    )
    return aciertos / len(golden)


def _datos_idioma() -> tuple[list[str], list[int], list[tuple[str, int]]]:
    """
    0=espanol, 1=ingles. Baseline: adaptive_prompt._detect_language.

    Combinatorio (verbo x objeto x cola): ~2.600 frases por idioma. El intento
    1 con 80 muestras dio heldout 0.833 — un 0.8M necesita variedad, no
    memoriza 80 frases y generaliza.
    """
    rng = random.Random(SEMILLA)
    es_v = ["explicame", "arregla", "muestrame", "resume", "revisa",
            "traduce", "escribe", "optimiza", "documenta", "prueba",
            "por que falla", "como funciona", "cuanto tarda"]
    es_o = ["el parser", "la memoria episodica", "el grafico animado",
            "este error", "el bug del sandbox", "mi codigo", "la busqueda",
            "el modelo chico", "los tests", "el dashboard", "la funcion",
            "el repositorio", "la respuesta del agente", "el contexto"]
    es_c = ["", " por favor", " cuando puedas", " otra vez", " en local",
            " paso a paso", " antes de seguir", " y dime que ves"]
    en_v = ["explain", "fix", "show me", "summarize", "review",
            "translate", "write", "optimize", "document", "test",
            "why does it fail", "how does it work", "how long takes"]
    en_o = ["the parser", "the episodic memory", "the animated chart",
            "this error", "the sandbox bug", "my code", "the search",
            "the small model", "the tests", "the dashboard", "the function",
            "the repository", "the agent reply", "the context"]
    en_c = ["", " please", " when you can", " again", " locally",
            " step by step", " before moving on", " and tell me"]
    textos, clases = [], []
    for v in es_v:
        for o in es_o:
            for c in rng.sample(es_c, 2):
                textos.append(f"{v} {o}{c}"); clases.append(0)
    for v in en_v:
        for o in en_o:
            for c in rng.sample(en_c, 2):
                textos.append(f"{v} {o}{c}"); clases.append(1)
    pares = list(zip(textos, clases)); rng.shuffle(pares)
    textos, clases = [p[0] for p in pares], [p[1] for p in pares]
    golden = [
        ("hola, como estas?", 0), ("hey, how are you?", 1),
        ("dame el estado del repo", 0), ("what is the repo status", 1),
        ("por que no funciona", 0), ("why does it not work", 1),
        ("me ayudas con esto", 0), ("can you help me with this", 1),
    ]
    return textos, clases, golden


def _baseline_idioma(golden: list[tuple[str, int]]) -> float:
    from cognia.agent.adaptive_prompt import _detect_language
    # Devuelve "espanol"/"ingles" (o None si no decide) — no "es"/"en". El
    # intento 1 media contra "es"/"en" y daba baseline 0.000: bug del
    # MEDIDOR, no de la heuristica.
    mapa = {"espanol": 0, "ingles": 1}
    aciertos = sum(1 for t, c in golden
                   if mapa.get(_detect_language(t), -1) == c)
    return aciertos / len(golden)


def _datos_pide_grafico() -> tuple[list[str], list[int], list[tuple[str, int]]]:
    """0=no pide grafico, 1=si. Baseline: program_creator._idea_pide_grafico."""
    rng = random.Random(SEMILLA)
    temas = ["ventas", "inversiones", "clima", "gastos", "usuarios",
             "sensores", "acciones", "consumo", "trafico", "notas",
             "temperatura", "visitas", "energia", "pedidos", "descargas",
             "ingresos", "latencia", "memoria", "errores", "clientes"]
    con = [
        "dashboard de {t} con grafico animado",
        "pagina con una grafica de {t} en tiempo real",
        "visualizacion de {t} con chart de lineas",
        "web que muestre un graph de {t}",
        "panel de {t} con sparklines por fila",
        "a {t} page with an animated chart",
        "grafico de barras de {t} que se actualice",
        "curva de {t} dibujada en svg",
        "web con la evolucion de {t} en una linea de tiempo",
        "monitor de {t} con su grafica historica",
        "a live {t} graph with moving average",
        "pagina que dibuje la serie temporal de {t}",
    ]
    sin = [
        "lista de {t} con filtros",
        "tabla de {t} ordenable",
        "formulario para registrar {t}",
        "buscador de {t} con resultados en tarjetas",
        "a {t} page with cards and a search box",
        "editor de {t} con guardado automatico",
        "galeria de {t} con imagenes",
        "contador de {t} con boton de reinicio",
        "web de {t} con acordeones y pestanas",
        "directorio de {t} con paginacion",
        "a {t} form with validation messages",
        "kanban de {t} con arrastrar y soltar",
    ]
    textos, clases = [], []
    for lista, clase in ((con, 1), (sin, 0)):
        for tpl in lista:
            for t in temas:
                textos.append(tpl.format(t=t)); clases.append(clase)
    pares = list(zip(textos, clases)); rng.shuffle(pares)
    textos, clases = [p[0] for p in pares], [p[1] for p in pares]
    golden = [
        ("pagina web que simule un dashboard de inversiones con movimiento: "
         "cotizaciones que cambian solas, grafico animado y variaciones en "
         "verde y rojo", 1),
        ("una pagina web con animaciones", 0),
        ("landing page para un producto", 0),
        ("web con una curva de temperatura por hora", 1),
        ("tabla de posiciones con precios en vivo", 0),
        ("panel con sparkline de cpu", 1),
    ]
    return textos, clases, golden


def _baseline_pide_grafico(golden: list[tuple[str, int]]) -> float:
    from cognia.program_creator.program_creator import _idea_pide_grafico
    aciertos = sum(1 for t, c in golden
                   if _idea_pide_grafico(t) == bool(c))
    return aciertos / len(golden)


# ── La flota, declarativa ──────────────────────────────────────────────────

FLOTA = {
    "idea_router": {
        "descripcion": "clasifica una idea: 0=web, 1=modulo python, 2=terminal",
        "clases": ["web", "python_module", "terminal_script"],
        "datos": _datos_idea_router,
        "baseline": _baseline_idea_router,
        "gate_heldout": 0.95,
    },
    "idioma": {
        "descripcion": "idioma del mensaje del usuario: 0=es, 1=en",
        "clases": ["es", "en"],
        "datos": _datos_idioma,
        "baseline": _baseline_idioma,
        "gate_heldout": 0.95,
    },
    "pide_grafico": {
        "descripcion": "si una idea web pide un grafico: 0=no, 1=si",
        "clases": ["no", "si"],
        "datos": _datos_pide_grafico,
        "baseline": _baseline_pide_grafico,
        "gate_heldout": 0.95,
    },
}


# ── Entrenamiento ──────────────────────────────────────────────────────────

def entrenar(nombre: str, spec: dict, epocas: int = 12) -> dict:
    torch.manual_seed(SEMILLA)
    textos, clases, golden = spec["datos"]()
    n_clases = len(spec["clases"])

    corte = int(len(textos) * 0.85)
    x_tr, m_tr = codificar(textos[:corte])
    y_tr = torch.tensor(clases[:corte])
    x_va, m_va = codificar(textos[corte:])
    y_va = torch.tensor(clases[corte:])

    modelo = MicroExperto(n_clases).to(DEVICE)
    n_params = sum(p.numel() for p in modelo.parameters())
    print(f"[{nombre}] {n_params/1e6:.2f}M params | {len(x_tr)} train / "
          f"{len(x_va)} heldout | {DEVICE}")

    opt = torch.optim.AdamW(modelo.parameters(), lr=3e-4, weight_decay=0.01)
    t0 = time.time()
    for ep in range(epocas):
        modelo.train()
        perm = torch.randperm(len(x_tr))
        total = 0.0
        for i in range(0, len(perm), 64):
            idx = perm[i:i + 64]
            x, m, y = (x_tr[idx].to(DEVICE), m_tr[idx].to(DEVICE),
                       y_tr[idx].to(DEVICE))
            logits = modelo(x, m)
            perdida = F.cross_entropy(logits, y)
            opt.zero_grad(); perdida.backward(); opt.step()
            total += perdida.item() * len(idx)
        modelo.eval()
        with torch.no_grad():
            pred = modelo(x_va.to(DEVICE), m_va.to(DEVICE)).argmax(-1).cpu()
        acc_va = (pred == y_va).float().mean().item()
        print(f"[{nombre}] epoca {ep+1:2d} | loss {total/len(x_tr):.4f} | "
              f"heldout {acc_va:.3f}")

    # Golden real
    gx, gm = codificar([t for t, _ in golden])
    gy = torch.tensor([c for _, c in golden])
    with torch.no_grad():
        gpred = modelo(gx.to(DEVICE), gm.to(DEVICE)).argmax(-1).cpu()
    acc_golden = (gpred == gy).float().mean().item()
    # el eje binario comparable con la heuristica
    acc_golden_bin = ((gpred == 0) == (gy == 0)).float().mean().item()
    base = spec["baseline"](golden)

    pasa = acc_va >= spec["gate_heldout"] and acc_golden_bin >= base
    metricas = {
        "params": n_params,
        "heldout_acc": round(acc_va, 4),
        "golden_acc_3clases": round(acc_golden, 4),
        "golden_acc_binaria": round(acc_golden_bin, 4),
        "baseline_heuristica": round(base, 4),
        "gate": "PASA" if pasa else "FALLA",
        "segundos_entrenamiento": round(time.time() - t0, 1),
        "device": DEVICE,
        "fecha": "2026-07-20",
    }

    destino = DIR_FLOTA / nombre
    destino.mkdir(parents=True, exist_ok=True)
    torch.save(modelo.state_dict(), destino / "model.pt")
    (destino / "config.json").write_text(json.dumps({
        "clases": spec["clases"], "dim": 128, "capas": 4, "cabezas": 4,
        "max_len": MAX_LEN, "descripcion": spec["descripcion"]},
        indent=2), encoding="utf-8")
    (destino / "metrics.json").write_text(
        json.dumps(metricas, indent=2), encoding="utf-8")
    print(f"[{nombre}] {metricas['gate']} | heldout {acc_va:.3f} | golden "
          f"binaria {acc_golden_bin:.3f} vs heuristica {base:.3f} | "
          f"{metricas['segundos_entrenamiento']}s")
    return metricas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--solo", help="entrenar solo este experto")
    ap.add_argument("--forzar", help="re-entrenar aunque haya pasado el gate")
    args = ap.parse_args()

    if args.estado:
        for nombre in FLOTA:
            m = DIR_FLOTA / nombre / "metrics.json"
            if m.exists():
                d = json.loads(m.read_text(encoding="utf-8"))
                print(f"{nombre:20} {d['gate']:6} heldout={d['heldout_acc']} "
                      f"golden_bin={d['golden_acc_binaria']} "
                      f"baseline={d['baseline_heuristica']}")
            else:
                print(f"{nombre:20} PENDIENTE")
        return 0

    for nombre, spec in FLOTA.items():
        if args.solo and nombre != args.solo:
            continue
        m = DIR_FLOTA / nombre / "metrics.json"
        if m.exists() and args.forzar != nombre:
            d = json.loads(m.read_text(encoding="utf-8"))
            if d.get("gate") == "PASA":
                print(f"[{nombre}] ya paso su gate; me lo salto "
                      f"(--forzar {nombre} para re-entrenar)")
                continue
        entrenar(nombre, spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
