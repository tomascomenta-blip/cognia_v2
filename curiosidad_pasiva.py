"""
curiosidad_pasiva.py — Módulo de Curiosidad Pasiva para Cognia v3
==================================================================
Cognia "sueña" cuando está inactiva: investiga por iniciativa propia
temas que le interesan basándose en su propia memoria.

COMPORTAMIENTO:
  1. Cada N minutos (configurable), el hilo despierta
  2. Revisa qué conceptos tienen poca información o muchas conexiones sin resolver
  3. Elige uno usando un puntaje de "curiosidad" (brechas de conocimiento + importancia)
  4. Lo investiga en Wikipedia / DuckDuckGo
  5. Guarda lo aprendido en la memoria de Cognia
  6. Vuelve a dormir

DIFERENCIA CON dormir (sleep()):
  - sleep()          → consolida lo ya aprendido (comprime, olvida, genera objetivos)
  - curiosidad_pasiva → ADQUIERE conocimiento nuevo sobre temas que Cognia ya sabe que no sabe

USO EN web_app.py:
    from curiosidad_pasiva import CuriosidadPasiva, register_routes_curiosidad
    curiosidad = CuriosidadPasiva(get_cognia)
    curiosidad.iniciar()
    register_routes_curiosidad(app, curiosidad)

USO STANDALONE:
    python curiosidad_pasiva.py

CONFIGURACIÓN (variables de entorno):
    COGNIA_CURIOSIDAD_INTERVALO=1800   (segundos entre ciclos, default 30 min)
    COGNIA_CURIOSIDAD_MAX_DIA=10       (máximo investigaciones por día)
"""

import threading
import time
import json
import os
import sys
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Configuración
INTERVALO_SEGUNDOS = int(os.environ.get("COGNIA_CURIOSIDAD_INTERVALO", 1800))  # 30 min
MAX_POR_DIA = int(os.environ.get("COGNIA_CURIOSIDAD_MAX_DIA", 10))


def db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.text_factory = str
    return conn


# ── Selector de conceptos a investigar ───────────────────────────────

def calcular_score_curiosidad(concept: str, support: int, confidence: float,
                               kg_edges: int, last_investigado: Optional[str]) -> float:
    """
    Calcula qué tan "curioso" debería ser Cognia sobre un concepto.
    
    Puntaje alto = concepto que Cognia conoce vagamente pero tiene potencial.
    
    Factores:
      - Bajo soporte episódico (pocas observaciones) → más curioso
      - Confianza media (ni muy alta ni muy baja) → más curioso
      - Muchos edges en el KG (concepto conectado pero poco conocido) → más curioso
      - No investigado recientemente → más curioso
    """
    # Baja confianza pero no ignorancia total: 0.3-0.6 es la zona más interesante
    sweet_spot = 1.0 - abs(confidence - 0.45) * 2
    sweet_spot = max(0.0, sweet_spot)
    
    # Poco soporte = mucho potencial de aprendizaje
    support_score = 1.0 / (1.0 + support * 0.3)
    
    # Muchos edges = concepto relevante pero sub-investigado
    kg_score = min(1.0, kg_edges * 0.1)
    
    # Penalizar si fue investigado recientemente (últimas 6 horas)
    recency_penalty = 0.0
    if last_investigado:
        try:
            dt = datetime.fromisoformat(last_investigado)
            hours_ago = (datetime.now() - dt).total_seconds() / 3600
            if hours_ago < 6:
                recency_penalty = 0.8
            elif hours_ago < 24:
                recency_penalty = 0.3
        except Exception:
            pass
    
    score = (0.4 * sweet_spot + 0.3 * support_score + 0.3 * kg_score) * (1 - recency_penalty)
    return round(score, 4)



def limpiar_concepto_para_busqueda(concept: str) -> str:
    """
    Convierte un label interno en un término buscable para Wikipedia/DuckDuckGo.
    Maneja tres problemas comunes en los labels de Cognia:
      1. Truncado a 25 chars: "inteligencia_artificial_g" -> "inteligencia artificial"
      2. Underscores como separadores: "deep_learning" -> "deep learning"
      3. Paréntesis sin cerrar (subcategorías Wikipedia): "neural_network_(machine_l" -> "neural network"
    """
    texto = concept
    # Si el label tiene exactamente 25 chars, fue truncado por SQLite UNIQUE constraint
    # Eliminar el último fragmento (que es una palabra cortada a la mitad)
    if len(concept) == 25:
        ultimo_sep = max(concept.rfind('_'), concept.rfind(' '))
        if ultimo_sep > 5:
            texto = concept[:ultimo_sep]
    # Reemplazar underscores por espacios
    texto = texto.replace("_", " ").strip()
    # Quitar paréntesis sin cerrar (subcategorías de Wikipedia como "(machine learning)")
    texto = re.sub(r'\s*\([^)]*$', '', texto).strip()
    # Quitar fragmentos de 1-2 chars al final (iniciales sueltas, letras huérfanas)
    texto = re.sub(r'(\s+\w{1,2}\.?)+$', '', texto).strip()
    return texto if len(texto) > 2 else concept.replace("_", " ").split("(")[0].strip()


def elegir_concepto_para_investigar(db_path: str, top_k: int = 5) -> Optional[str]:
    """
    Selecciona el concepto más interesante para investigar.
    Cruza semantic_memory con knowledge_graph para encontrar brechas.
    """
    conn = db_connect(db_path)
    c = conn.cursor()
    
    # Obtener conceptos semánticos con sus métricas
    c.execute("""
        SELECT sm.concept, sm.support, sm.confidence, sm.last_updated
        FROM semantic_memory sm
        WHERE length(sm.concept) > 3
          AND sm.concept NOT LIKE '%investigado%'
          AND sm.concept NOT GLOB '*[0-9][0-9][0-9][0-9][0-9]*'
        ORDER BY sm.support ASC
        LIMIT 100
    """)
    conceptos = c.fetchall()
    
    if not conceptos:
        conn.close()
        return None
    
    # Contar edges en el KG por concepto
    candidates = []
    for concept, support, confidence, last_updated in conceptos:
        c.execute("""
            SELECT COUNT(*) FROM knowledge_graph
            WHERE subject=? OR object=?
        """, (concept, concept))
        kg_edges = c.fetchone()[0]
        
        # Buscar si fue investigado antes (via context_tags en episodic_memory)
        c.execute("""
            SELECT MAX(timestamp) FROM episodic_memory
            WHERE label=? AND context_tags LIKE '%wikipedia%'
        """, (concept,))
        row = c.fetchone()
        last_investigado = row[0] if row else None
        
        score = calcular_score_curiosidad(concept, support, confidence, kg_edges, last_investigado)
        candidates.append((concept, score))
    
    conn.close()
    
    if not candidates:
        return None
    
    # ── Boost para conceptos mencionados en conversaciones recientes ──
    # Hace que curiosidad_pasiva "reflexione" sobre lo que acaba de charlar,
    # en lugar de elegir algo aleatorio de la memoria.
    try:
        conn2 = db_connect(db_path)
        c2 = conn2.cursor()
        c2.execute("""
            SELECT DISTINCT label FROM episodic_memory
            WHERE label IS NOT NULL
              AND context_tags LIKE '%chat%'
              AND forgotten = 0
            ORDER BY timestamp DESC LIMIT 30
        """)
        labels_recientes = {r[0] for r in c2.fetchall()}
        conn2.close()
    except Exception:
        labels_recientes = set()

    boosted = []
    for concept, score in candidates:
        # Boost 1.8x si el concepto fue mencionado en las últimas conversaciones
        boost = 1.8 if concept in labels_recientes else 1.0
        boosted.append((concept, score * boost))
    boosted.sort(key=lambda x: -x[1])
    candidates = boosted

    # Ordenar por score y elegir aleatoriamente entre los top_k
    # (para no siempre elegir el mismo)
    import random
    top = candidates[:top_k]
    
    # Ponderar aleatoriamente por score
    total = sum(s for _, s in top)
    if total == 0:
        return top[0][0]
    
    r = random.random() * total
    cumsum = 0
    for concept, score in top:
        cumsum += score
        if r <= cumsum:
            return concept
    
    return top[0][0]


def contar_investigaciones_hoy(db_path: str) -> int:
    """Cuenta cuántas investigaciones autónomas se hicieron hoy."""
    conn = db_connect(db_path)
    c = conn.cursor()
    hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        SELECT COUNT(*) FROM episodic_memory
        WHERE context_tags LIKE '%wikipedia%'
          AND timestamp LIKE ?
    """, (f"{hoy}%",))
    n = c.fetchone()[0]
    conn.close()
    return n


# ── Ciclo de curiosidad ───────────────────────────────────────────────

def ciclo_curiosidad(ai, db_path: str) -> dict:
    """
    Ejecuta un ciclo completo de curiosidad pasiva:
      1. Verifica si hay cuota disponible
      2. Elige un concepto interesante
      3. Lo investiga
      4. Guarda en memoria
      5. Retorna resumen del ciclo
    """
    resultado = {
        "timestamp": datetime.now().isoformat(),
        "investigado": False,
        "concepto": None,
        "titulo_wiki": None,
        "hechos_guardados": 0,
        "razon_skip": None
    }
    
    # 1. Cuota diaria
    investigaciones_hoy = contar_investigaciones_hoy(db_path)
    if investigaciones_hoy >= MAX_POR_DIA:
        resultado["razon_skip"] = f"Cuota diaria alcanzada ({investigaciones_hoy}/{MAX_POR_DIA})"
        return resultado
    
    # 2. Elegir concepto
    concepto = elegir_concepto_para_investigar(db_path)
    if not concepto:
        resultado["razon_skip"] = "No hay conceptos candidatos en la memoria semántica"
        return resultado
    
    resultado["concepto"] = concepto
    
    # 3. Investigar
    try:
        from investigador import buscar_wikipedia, buscar_duckduckgo, extraer_hechos_simples, guardar_en_cognia
        
        termino_busqueda = limpiar_concepto_para_busqueda(concepto)
        wiki = buscar_wikipedia(termino_busqueda)
        if not wiki:
            wiki = buscar_duckduckgo(termino_busqueda)
        
        if not wiki:
            resultado["razon_skip"] = f"No encontré información sobre '{concepto}'"
            return resultado
        
        titulo = wiki["titulo"]
        extracto = wiki["extracto"]
        
        # Evitar guardar el mismo artículo dos veces si el título ya está en memoria
        conn = db_connect(db_path)
        c = conn.cursor()
        titulo_label = titulo.lower().replace(" ", "_")
        c.execute("""
            SELECT COUNT(*) FROM episodic_memory
            WHERE label=? AND context_tags LIKE '%wikipedia%'
        """, (titulo_label,))
        ya_guardado = c.fetchone()[0]
        conn.close()
        
        if ya_guardado > 0:
            resultado["razon_skip"] = f"'{titulo}' ya fue investigado antes"
            return resultado
        
        # 4. Guardar
        hechos = extraer_hechos_simples(titulo, extracto)
        guardado = guardar_en_cognia(ai, titulo, extracto, hechos, f"curiosidad_pasiva:{concepto}")
        
        resultado["investigado"] = True
        resultado["titulo_wiki"] = titulo
        resultado["url"] = wiki["url"]
        resultado["hechos_guardados"] = guardado.get("hechos_grafo", 0)
        resultado["episodios_guardados"] = guardado.get("episodios", 0)
        
    except Exception as e:
        resultado["razon_skip"] = f"Error durante investigación: {e}"
    
    return resultado


# ── Clase principal ───────────────────────────────────────────────────

class CuriosidadPasiva:
    """
    Hilo de fondo que ejecuta ciclos de curiosidad pasiva.
    
    Ejemplo de uso:
        from curiosidad_pasiva import CuriosidadPasiva
        curiosidad = CuriosidadPasiva(get_cognia_func)
        curiosidad.iniciar()
        # ...
        curiosidad.detener()
    """
    
    def __init__(self, ai_getter, db_path: str = "cognia_memory.db",
                 intervalo: int = INTERVALO_SEGUNDOS):
        self.ai_getter = ai_getter
        self.db_path = db_path
        self.intervalo = intervalo
        self._hilo: Optional[threading.Thread] = None
        self._activo = False
        self._log = []          # Historial de los últimos ciclos
        self._log_max = 50
        self._lock = threading.Lock()
        self._ultimo_ciclo: Optional[dict] = None
    
    def iniciar(self):
        """Inicia el hilo de curiosidad pasiva."""
        if self._activo:
            return
        self._activo = True
        self._hilo = threading.Thread(
            target=self._loop,
            name="CuriosidadPasiva",
            daemon=True  # Se detiene cuando termina el proceso principal
        )
        self._hilo.start()
        print(f"[CuriosidadPasiva] Iniciada. Intervalo: {self.intervalo}s, "
              f"máx/día: {MAX_POR_DIA}")
    
    def detener(self):
        """Detiene el hilo de curiosidad pasiva."""
        self._activo = False
        if self._hilo:
            self._hilo.join(timeout=5)
        print("[CuriosidadPasiva] Detenida.")
    
    def forzar_ciclo(self) -> dict:
        """Ejecuta un ciclo inmediatamente (para testing o desde la UI)."""
        try:
            ai = self.ai_getter()
            resultado = ciclo_curiosidad(ai, self.db_path)
            self._registrar(resultado)
            return resultado
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now().isoformat()}
    
    def estado(self) -> dict:
        """Retorna el estado actual del módulo."""
        investigaciones_hoy = contar_investigaciones_hoy(self.db_path)
        return {
            "activo": self._activo,
            "intervalo_segundos": self.intervalo,
            "max_por_dia": MAX_POR_DIA,
            "investigaciones_hoy": investigaciones_hoy,
            "ultimo_ciclo": self._ultimo_ciclo,
            "historial_reciente": self._log[-5:] if self._log else []
        }
    
    def _loop(self):
        """Loop principal del hilo."""
        # Esperar un minuto al inicio para que Cognia termine de cargar
        time.sleep(60)
        
        while self._activo:
            try:
                ai = self.ai_getter()
                resultado = ciclo_curiosidad(ai, self.db_path)
                self._registrar(resultado)
                
                if resultado["investigado"]:
                    print(f"[CuriosidadPasiva] ✨ Investigué '{resultado['titulo_wiki']}' "
                          f"(concepto: {resultado['concepto']}, "
                          f"+{resultado['hechos_guardados']} hechos)")
                elif resultado.get("razon_skip"):
                    print(f"[CuriosidadPasiva] ⏭ Salté: {resultado['razon_skip']}")
                    
            except Exception as e:
                print(f"[CuriosidadPasiva] ❌ Error en ciclo: {e}")
            
            # Dormir hasta el siguiente ciclo
            # Usar sleep(1) en loop para poder detener el hilo rápido
            for _ in range(self.intervalo):
                if not self._activo:
                    break
                time.sleep(1)
    
    def _registrar(self, resultado: dict):
        with self._lock:
            self._ultimo_ciclo = resultado
            self._log.append(resultado)
            if len(self._log) > self._log_max:
                self._log.pop(0)


# ── Integración con Flask ─────────────────────────────────────────────

def register_routes_curiosidad(app, curiosidad: CuriosidadPasiva):
    """Registra los endpoints de curiosidad pasiva en la app Flask."""
    from flask import jsonify, request
    
    @app.route("/api/curiosidad/estado")
    def api_curiosidad_estado():
        return jsonify(curiosidad.estado())
    
    @app.route("/api/curiosidad/forzar", methods=["POST"])
    def api_curiosidad_forzar():
        resultado = curiosidad.forzar_ciclo()
        return jsonify(resultado)
    
    @app.route("/api/curiosidad/historial")
    def api_curiosidad_historial():
        return jsonify(curiosidad._log[-20:])
    
    print("[OK] Endpoints de CuriosidadPasiva registrados: "
          "/api/curiosidad/estado, /api/curiosidad/forzar, /api/curiosidad/historial")


# ── CLI standalone ───────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Cognia — Curiosidad Pasiva")
    parser.add_argument("--ciclo", action="store_true", help="Ejecutar un ciclo ahora y salir")
    parser.add_argument("--estado", action="store_true", help="Mostrar estado y salir")
    parser.add_argument("--daemon", action="store_true", help="Correr en modo daemon")
    parser.add_argument("--db", default="cognia_memory.db", help="Ruta a la DB")
    args = parser.parse_args()
    
    from cognia import Cognia
    _ai = None
    
    def get_ai():
        global _ai
        if _ai is None:
            _ai = Cognia(args.db)
        return _ai
    
    curiosidad = CuriosidadPasiva(get_ai, db_path=args.db)
    
    if args.estado:
        estado = curiosidad.estado()
        print(json.dumps(estado, indent=2, ensure_ascii=False))
    
    elif args.ciclo:
        print("Ejecutando ciclo de curiosidad...")
        resultado = curiosidad.forzar_ciclo()
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    
    elif args.daemon:
        print(f"Iniciando modo daemon (intervalo: {INTERVALO_SEGUNDOS}s)")
        print("Presiona Ctrl+C para detener.")
        curiosidad.iniciar()
        try:
            while True:
                time.sleep(60)
                estado = curiosidad.estado()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Investigaciones hoy: {estado['investigaciones_hoy']}/{MAX_POR_DIA}")
        except KeyboardInterrupt:
            print("\nDeteniendo...")
            curiosidad.detener()
    
    else:
        print(__doc__)
        print("\nUso:")
        print("  python curiosidad_pasiva.py --ciclo       # Un ciclo ahora")
        print("  python curiosidad_pasiva.py --estado      # Ver estado")
        print("  python curiosidad_pasiva.py --daemon      # Modo continuo")
