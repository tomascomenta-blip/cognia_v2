"""
aprendizaje_profundo.py — Módulo de aprendizaje enciclopédico para Cognia v3
=============================================================================
Lee Wikipedia en cadena, extrae conocimiento estructurado y lo guarda en
TODOS los sistemas de memoria de Cognia:
  - EpisodicMemory   (observaciones con label y emoción)
  - SemanticMemory   (conceptos con vectores, asociaciones cruzadas)
  - KnowledgeGraph   (triples sujeto→relación→objeto)

USO EN CHAT:
  aprender adn
  aprender hormona
  aprender hgh
  aprender jacobo grinberg
  aprender proteina
  aprender peptido
  aprender insulina

ACTIVACIÓN DESDE web_app.py (antes del if __name__):
  from aprendizaje_profundo import register_routes_aprendizaje
  register_routes_aprendizaje(app, get_cognia)
"""

import json
import re
import time
import urllib.request
import urllib.parse
from typing import Optional

# ── Temas predefinidos con sus alias de Wikipedia ─────────────────────────────
# Cada tema tiene: página principal + páginas relacionadas que se leerán en cadena
TEMAS_PREDEFINIDOS = {
    # ── ADN y biología molecular ──────────────────────────────────────────────
    "adn": {
        "label": "adn",
        "paginas": [
            "DNA", "Nucleotide", "Deoxyribose", "Nitrogenous base",
            "Base pair", "Double helix", "DNA replication",
            "DNA transcription", "Chromatin", "Chromosome",
        ],
        "relaciones_extra": [
            ("adn", "compuesto_de", "nucleotido"),
            ("nucleotido", "tiene_componente", "base_nitrogenada"),
            ("nucleotido", "tiene_componente", "desoxirribosa"),
            ("nucleotido", "tiene_componente", "fosfato"),
            ("adn", "contiene_base", "adenina"),
            ("adn", "contiene_base", "timina"),
            ("adn", "contiene_base", "guanina"),
            ("adn", "contiene_base", "citosina"),
            ("adn", "proceso", "replicacion"),
            ("adn", "proceso", "transcripcion"),
            ("transcripcion", "produce", "arn_mensajero"),
            ("arn_mensajero", "proceso", "traduccion"),
            ("traduccion", "produce", "proteina"),
        ],
    },

    # ── Proteínas ─────────────────────────────────────────────────────────────
    "proteina": {
        "label": "proteina",
        "paginas": [
            "Protein", "Amino acid", "Peptide bond", "Protein folding",
            "Enzyme", "Protein structure", "Ribosome",
        ],
        "relaciones_extra": [
            ("proteina", "compuesta_de", "aminoacido"),
            ("aminoacidos", "unidos_por", "enlace_peptidico"),
            ("cadena_de_aminoacidos", "es_un", "peptido"),
            ("peptido_largo", "es_un", "polipeptido"),
            ("polipeptido_plegado", "es_un", "proteina"),
            ("proteina", "sintetizada_en", "ribosoma"),
            ("enzima", "es_un_tipo_de", "proteina"),
            ("anticuerpo", "es_un_tipo_de", "proteina"),
            ("hormona_peptidica", "es_un_tipo_de", "proteina"),
        ],
    },

    # ── Péptidos y polipéptidos ───────────────────────────────────────────────
    "peptido": {
        "label": "peptido",
        "paginas": [
            "Peptide", "Polypeptide chain", "Dipeptide",
            "Neuropeptide", "Peptide hormone", "Signal peptide",
        ],
        "relaciones_extra": [
            ("dipeptido", "tiene", "dos_aminoacidos"),
            ("oligopeptido", "tiene", "menos_de_10_aminoacidos"),
            ("polipeptido", "tiene", "mas_de_10_aminoacidos"),
            ("neuropeptido", "actua_en", "sistema_nervioso"),
            ("peptido_señal", "dirige", "proteina_a_organel"),
            ("peptido_hormona", "regula", "funcion_fisiologica"),
        ],
    },

    # ── Hormonas ──────────────────────────────────────────────────────────────
    "hormona": {
        "label": "hormona",
        "paginas": [
            "Hormone", "Endocrine system", "Steroid hormone",
            "Peptide hormone", "Thyroid hormone", "Cortisol",
            "Testosterone", "Estrogen", "Insulin", "Glucagon",
        ],
        "relaciones_extra": [
            ("hormona", "producida_por", "glandula_endocrina"),
            ("hormona_esteroidea", "derivada_de", "colesterol"),
            ("hormona_peptidica", "derivada_de", "aminoacidos"),
            ("insulina", "regula", "glucosa_en_sangre"),
            ("glucagon", "eleva", "glucosa_en_sangre"),
            ("cortisol", "producido_por", "glandula_suprarrenal"),
            ("testosterona", "producida_por", "testiculos"),
            ("estrogeno", "producido_por", "ovarios"),
            ("hormona_tiroidea", "regula", "metabolismo"),
            ("sistema_endocrino", "usa", "hormonas_como_mensajeros"),
        ],
    },

    # ── HGH - Hormona de crecimiento humano ───────────────────────────────────
    "hgh": {
        "label": "hgh",
        "paginas": [
            "Growth hormone", "Insulin-like growth factor 1",
            "Somatotropic cell", "Pituitary gland",
            "Growth hormone deficiency", "Somatostatin",
            "Growth hormone–releasing hormone",
        ],
        "relaciones_extra": [
            ("hgh", "nombre_completo", "hormona_de_crecimiento_humano"),
            ("hgh", "producida_por", "hipofisis_anterior"),
            ("hipofisis_anterior", "contiene", "celulas_somatotropas"),
            ("ghrh", "estimula", "liberacion_de_hgh"),
            ("somatostatina", "inhibe", "liberacion_de_hgh"),
            ("hgh", "estimula", "igf1"),
            ("igf1", "media", "efectos_de_crecimiento"),
            ("hgh", "efecto", "crecimiento_muscular"),
            ("hgh", "efecto", "lipólisis"),
            ("hgh", "efecto", "crecimiento_oseo"),
            ("hgh", "efecto", "sintesis_proteica"),
            ("deficiencia_hgh", "causa", "enanismo_hipofisario"),
            ("exceso_hgh", "causa", "acromegalia"),
            ("hgh", "secrecion_maxima", "durante_sueno_profundo"),
            ("ejercicio", "aumenta", "secrecion_hgh"),
            ("ayuno", "aumenta", "secrecion_hgh"),
        ],
    },

    # ── Jacobo Grinberg ───────────────────────────────────────────────────────
    "jacobo grinberg": {
        "label": "jacobo_grinberg",
        "paginas": [
            "Jacobo Grinberg-Zylberbaum",
            "Neurociencia",
            "Conciencia",
            "Campo morfogenético",
            "Sincronización neuronal",
        ],
        "busquedas_extra": [
            "Syntergic theory Grinberg",
            "Neuronal field consciousness Grinberg",
            "Grinberg brain synchrony experiment",
            "teoria sinteergica conciencia",
            "campo neuronal preespacio Grinberg",
        ],
        "relaciones_extra": [
            ("jacobo_grinberg", "es_un", "neurocientifico_mexicano"),
            ("jacobo_grinberg", "trabajo_en", "unam"),
            ("jacobo_grinberg", "propuso", "teoria_sinteergica"),
            ("teoria_sinteergica", "postula", "campo_neuronal"),
            ("campo_neuronal", "interactua_con", "campo_preespacio"),
            ("preespacio", "es", "campo_de_informacion_fundamental"),
            ("jacobo_grinberg", "estudio", "sincronizacion_cerebral"),
            ("experimento_grinberg", "involucra", "eeg_sincronizado_entre_personas"),
            ("conciencia", "segun_grinberg", "emerge_del_campo_neuronal"),
            ("jacobo_grinberg", "desaparecio", "1994"),
            ("jacobo_grinberg", "escribio", "la_luz_del_mexico_antiguo"),
            ("jacobo_grinberg", "estudio", "chamanes_huicholes"),
            ("meditacion", "segun_grinberg", "amplifica_campo_neuronal"),
        ],
    },

    # ── Insulina (extra detalle) ───────────────────────────────────────────────
    "insulina": {
        "label": "insulina",
        "paginas": [
            "Insulin", "Beta cell", "Pancreas",
            "Insulin receptor", "Diabetes mellitus",
            "Insulin resistance",
        ],
        "relaciones_extra": [
            ("insulina", "es_un", "hormona_peptidica"),
            ("insulina", "producida_por", "celulas_beta"),
            ("celulas_beta", "ubicadas_en", "pancreas"),
            ("insulina", "reduce", "glucosa_en_sangre"),
            ("insulina", "facilita", "captacion_de_glucosa"),
            ("receptor_insulina", "es_un", "receptor_tirosina_quinasa"),
            ("resistencia_insulina", "causa", "diabetes_tipo_2"),
            ("deficiencia_insulina", "causa", "diabetes_tipo_1"),
        ],
    },

    # ── ARN ───────────────────────────────────────────────────────────────────
    "arn": {
        "label": "arn",
        "paginas": [
            "RNA", "Messenger RNA", "Transfer RNA",
            "Ribosomal RNA", "RNA splicing", "MicroRNA",
        ],
        "relaciones_extra": [
            ("arn", "diferencia_de_adn", "usa_uracilo_en_vez_de_timina"),
            ("arn", "generalmente", "cadena_simple"),
            ("arn_mensajero", "lleva", "instrucciones_del_adn_al_ribosoma"),
            ("arn_transferencia", "lleva", "aminoacidos_al_ribosoma"),
            ("arn_ribosomal", "forma_parte_de", "ribosoma"),
            ("micro_arn", "regula", "expresion_genica"),
        ],
    },
    # ════════════════════════════════════════════════════════════════════════
    # NEUROCIENCIA Y MENTE
    # ════════════════════════════════════════════════════════════════════════

    "neurociencia": {
        "label": "neurociencia",
        "paginas": [
            "Neuroscience", "Neuron", "Synapse", "Action potential",
            "Neurotransmitter", "Brain", "Cerebral cortex",
            "Hippocampus", "Amygdala", "Prefrontal cortex",
            "Neuroplasticity", "Neural oscillation",
        ],
        "relaciones_extra": [
            ("neurona", "conecta_con", "neurona_via_sinapsis"),
            ("sinapsis", "libera", "neurotransmisor"),
            ("dopamina", "es_un", "neurotransmisor"),
            ("serotonina", "es_un", "neurotransmisor"),
            ("norepinefrina", "es_un", "neurotransmisor"),
            ("gaba", "es_un", "neurotransmisor_inhibidor"),
            ("glutamato", "es_un", "neurotransmisor_excitador"),
            ("hipocampo", "rol", "formacion_de_memoria"),
            ("amigdala", "rol", "procesamiento_emocional"),
            ("corteza_prefrontal", "rol", "toma_de_decisiones"),
            ("neuroplasticidad", "permite", "aprendizaje_y_adaptacion"),
            ("potencial_de_accion", "propaga", "señal_electrica_neuronal"),
        ],
    },

    "consciencia": {
        "label": "consciencia",
        "paginas": [
            "Consciousness", "Hard problem of consciousness",
            "Global workspace theory", "Integrated information theory",
            "Qualia", "Self-awareness", "Altered state of consciousness",
            "Default mode network", "Metacognition",
        ],
        "relaciones_extra": [
            ("consciencia", "problema_filosofico", "problema_dificil_de_chalmers"),
            ("qualia", "es", "experiencia_subjetiva"),
            ("teoria_iit", "propone", "phi_como_medida_de_consciencia"),
            ("red_modo_default", "activa_durante", "estado_de_reposo"),
            ("metacognicion", "es", "pensar_sobre_el_propio_pensamiento"),
            ("estados_alterados", "incluyen", "sueno_meditacion_psicodelicos"),
        ],
    },

    "meditacion": {
        "label": "meditacion",
        "paginas": [
            "Meditation", "Mindfulness", "Transcendental Meditation",
            "Zen", "Vipassana", "Theta wave", "Default mode network",
            "Neuroimaging of meditation",
        ],
        "relaciones_extra": [
            ("meditacion", "reduce", "cortisol"),
            ("meditacion", "aumenta", "ondas_theta"),
            ("meditacion", "aumenta", "grosor_corteza_prefrontal"),
            ("mindfulness", "es_tipo_de", "meditacion"),
            ("meditacion_trascendental", "usa", "mantra"),
            ("vipassana", "es", "meditacion_de_insight"),
            ("meditacion", "activa", "insula_y_corteza_cingulada_anterior"),
            ("meditacion", "desactiva", "red_modo_default"),
        ],
    },

    "sueno": {
        "label": "sueno",
        "paginas": [
            "Sleep", "REM sleep", "Non-REM sleep", "Sleep cycle",
            "Circadian rhythm", "Melatonin", "Sleep deprivation",
            "Memory consolidation", "Slow-wave sleep",
        ],
        "relaciones_extra": [
            ("sueno", "ciclo", "90_minutos_aprox"),
            ("sueno_rem", "asociado_con", "sueños_vividos"),
            ("sueno_profundo", "pico_de", "hgh"),
            ("sueno_profundo", "consolida", "memoria_declarativa"),
            ("melatonina", "producida_por", "glandula_pineal"),
            ("ritmo_circadiano", "regulado_por", "nucleo_supraquiasmatico"),
            ("privacion_de_sueno", "reduce", "igf1_y_hgh"),
            ("privacion_de_sueno", "aumenta", "cortisol"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # BIOLOGÍA CELULAR Y MOLECULAR
    # ════════════════════════════════════════════════════════════════════════

    "celula": {
        "label": "celula",
        "paginas": [
            "Cell biology", "Cell membrane", "Mitochondria",
            "Nucleus", "Endoplasmic reticulum", "Golgi apparatus",
            "Lysosome", "Cell cycle", "Apoptosis", "Stem cell",
        ],
        "relaciones_extra": [
            ("celula", "rodeada_por", "membrana_plasmatica"),
            ("mitocondria", "produce", "atp"),
            ("nucleo", "contiene", "adn"),
            ("reticulo_endoplasmatico", "sintetiza", "proteinas_y_lipidos"),
            ("aparato_de_golgi", "modifica", "proteinas"),
            ("lisosoma", "degrada", "materiales_celulares"),
            ("apoptosis", "es", "muerte_celular_programada"),
            ("celula_madre", "puede_diferenciarse_en", "cualquier_tipo_celular"),
        ],
    },

    "epigenetica": {
        "label": "epigenetica",
        "paginas": [
            "Epigenetics", "DNA methylation", "Histone modification",
            "Gene expression", "Chromatin remodeling",
            "Epigenetic inheritance", "Telomere",
        ],
        "relaciones_extra": [
            ("epigenetica", "estudia", "cambios_en_expresion_sin_cambiar_adn"),
            ("metilacion_adn", "silencia", "genes"),
            ("histona", "organiza", "el_adn_en_cromatina"),
            ("acetilacion_histona", "activa", "transcripcion"),
            ("telomero", "protege", "extremos_de_cromosomas"),
            ("telomero_corto", "asociado_con", "envejecimiento"),
            ("estres", "puede_modificar", "patron_epigenetico"),
        ],
    },

    "sistema_inmune": {
        "label": "sistema_inmune",
        "paginas": [
            "Immune system", "T cell", "B cell", "Antibody",
            "Innate immune system", "Adaptive immune system",
            "Inflammation", "Cytokine", "Natural killer cell",
            "Autoimmune disease",
        ],
        "relaciones_extra": [
            ("celula_t", "es", "linfocito_del_sistema_adaptativo"),
            ("celula_b", "produce", "anticuerpos"),
            ("anticuerpo", "neutraliza", "antigenos"),
            ("inflamacion", "mediada_por", "citocinas"),
            ("sistema_innato", "responde", "de_forma_rapida_e_inespecifica"),
            ("sistema_adaptativo", "es", "especifico_y_tiene_memoria"),
            ("cortisol", "suprime", "sistema_inmune"),
            ("enfermedad_autoinmune", "ocurre_cuando", "inmune_ataca_tejido_propio"),
        ],
    },

    "microbioma": {
        "label": "microbioma",
        "paginas": [
            "Human microbiome", "Gut microbiota", "Gut-brain axis",
            "Probiotic", "Prebiotic", "Dysbiosis",
            "Firmicutes", "Bacteroidetes",
        ],
        "relaciones_extra": [
            ("microbioma", "compuesto_de", "billones_de_microorganismos"),
            ("eje_intestino_cerebro", "comunica", "intestino_y_sistema_nervioso"),
            ("microbioma", "produce", "serotonina_intestinal"),
            ("disbiosis", "es", "desequilibrio_del_microbioma"),
            ("probiotico", "restaura", "flora_intestinal"),
            ("prebiotico", "alimenta", "bacterias_beneficiosas"),
            ("microbioma", "influye_en", "sistema_inmune"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # FÍSICA Y COSMOLOGÍA
    # ════════════════════════════════════════════════════════════════════════

    "mecanica_cuantica": {
        "label": "mecanica_cuantica",
        "paginas": [
            "Quantum mechanics", "Wave function", "Superposition",
            "Quantum entanglement", "Uncertainty principle",
            "Double-slit experiment", "Schrödinger equation",
            "Quantum field theory", "Wave-particle duality",
        ],
        "relaciones_extra": [
            ("mecanica_cuantica", "describe", "comportamiento_a_escala_atomica"),
            ("funcion_de_onda", "colapsa_al", "medir"),
            ("superposicion", "permite", "estar_en_multiples_estados"),
            ("entrelazamiento", "correlaciona", "particulas_a_distancia"),
            ("principio_incertidumbre", "formulado_por", "heisenberg"),
            ("dualidad_onda_particula", "demostrada_en", "experimento_doble_rendija"),
            ("mecanica_cuantica", "base_de", "quimica_y_electronica"),
        ],
    },

    "relatividad": {
        "label": "relatividad",
        "paginas": [
            "Theory of relativity", "Special relativity",
            "General relativity", "Spacetime", "Time dilation",
            "Gravitational wave", "Black hole", "Einstein field equations",
        ],
        "relaciones_extra": [
            ("relatividad_especial", "postula", "velocidad_de_luz_constante"),
            ("e_mc2", "equivalencia", "masa_energia"),
            ("dilatacion_temporal", "ocurre_a", "velocidades_relativistas"),
            ("relatividad_general", "describe", "gravedad_como_curvatura_espacio"),
            ("agujero_negro", "tiene", "singularidad"),
            ("ondas_gravitacionales", "predichas_por", "einstein"),
            ("espacio_tiempo", "es", "continuo_de_4_dimensiones"),
        ],
    },

    "cosmologia": {
        "label": "cosmologia",
        "paginas": [
            "Cosmology", "Big Bang", "Dark matter", "Dark energy",
            "Cosmic inflation", "Multiverse", "Observable universe",
            "Cosmic microwave background",
        ],
        "relaciones_extra": [
            ("universo", "origen", "big_bang_hace_13800_millones_años"),
            ("materia_oscura", "constituye", "27_porciento_universo"),
            ("energia_oscura", "constituye", "68_porciento_universo"),
            ("inflacion_cosmica", "explica", "homogeneidad_del_universo"),
            ("fondo_cosmico_microondas", "evidencia_de", "big_bang"),
            ("multiverso", "hipotesis_de", "universos_paralelos"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # INTELIGENCIA ARTIFICIAL Y COMPUTACIÓN
    # ════════════════════════════════════════════════════════════════════════

    "inteligencia_artificial": {
        "label": "inteligencia_artificial",
        "paginas": [
            "Artificial intelligence", "Machine learning", "Deep learning",
            "Neural network", "Natural language processing",
            "Reinforcement learning", "Transformer model",
            "Large language model", "Computer vision",
        ],
        "relaciones_extra": [
            ("ia", "subcampo_de", "ciencias_de_la_computacion"),
            ("machine_learning", "es_subcampo_de", "ia"),
            ("deep_learning", "es_subcampo_de", "machine_learning"),
            ("red_neuronal", "inspirada_en", "cerebro_biologico"),
            ("transformer", "arquitectura_base_de", "llm"),
            ("llm", "entrenado_con", "grandes_corpus_de_texto"),
            ("aprendizaje_refuerzo", "aprende_por", "recompensas_y_penalizaciones"),
            ("vision_computacional", "procesa", "imagenes_y_video"),
        ],
    },

    "computacion_cuantica": {
        "label": "computacion_cuantica",
        "paginas": [
            "Quantum computing", "Qubit", "Quantum gate",
            "Quantum supremacy", "Shor algorithm", "Grover algorithm",
            "Quantum error correction", "Decoherence",
        ],
        "relaciones_extra": [
            ("qubit", "puede_ser", "0_y_1_simultaneamente"),
            ("computadora_cuantica", "usa", "superposicion_y_entrelazamiento"),
            ("algoritmo_shor", "factoriza", "numeros_grandes_exponencialmente_rapido"),
            ("decoherencia", "destruye", "estado_cuantico"),
            ("correccion_de_errores", "es", "desafio_principal"),
            ("supremacia_cuantica", "lograda_por", "google_en_2019"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # PSICOLOGÍA Y COMPORTAMIENTO
    # ════════════════════════════════════════════════════════════════════════

    "psicologia": {
        "label": "psicologia",
        "paginas": [
            "Psychology", "Cognitive psychology", "Behavioral psychology",
            "Unconscious mind", "Carl Jung", "Sigmund Freud",
            "Abraham Maslow", "Cognitive bias", "Emotions",
        ],
        "relaciones_extra": [
            ("psicologia_cognitiva", "estudia", "procesos_mentales"),
            ("conductismo", "estudia", "comportamiento_observable"),
            ("inconsciente", "propuesto_por", "freud"),
            ("arquetipo", "concepto_de", "jung"),
            ("piramide_maslow", "jerarquia_de", "necesidades_humanas"),
            ("sesgo_cognitivo", "es", "error_sistematico_de_pensamiento"),
            ("emocion", "tiene_componente", "fisiologico_y_subjetivo"),
        ],
    },

    "flow": {
        "label": "flow",
        "paginas": [
            "Flow (psychology)", "Mihaly Csikszentmihalyi",
            "Intrinsic motivation", "Peak experience",
            "Autotelic", "Positive psychology",
        ],
        "relaciones_extra": [
            ("flow", "definido_por", "csikszentmihalyi"),
            ("flow", "ocurre_cuando", "desafio_igual_a_habilidad"),
            ("flow", "caracterizado_por", "absorcion_total_en_la_tarea"),
            ("flow", "aumenta", "dopamina_y_norepinefrina"),
            ("experiencia_autonoma", "es", "actividad_que_vale_por_si_misma"),
            ("psicologia_positiva", "estudia", "bienestar_y_flourishing"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # FILOSOFÍA
    # ════════════════════════════════════════════════════════════════════════

    "filosofia": {
        "label": "filosofia",
        "paginas": [
            "Philosophy", "Epistemology", "Metaphysics", "Ethics",
            "Stoicism", "Existentialism", "Plato", "Aristotle",
            "Friedrich Nietzsche", "Immanuel Kant",
        ],
        "relaciones_extra": [
            ("epistemologia", "estudia", "naturaleza_del_conocimiento"),
            ("metafisica", "estudia", "naturaleza_de_la_realidad"),
            ("etica", "estudia", "moralidad_y_valores"),
            ("estoicismo", "propone", "control_de_lo_que_depende_de_uno"),
            ("existencialismo", "postula", "existencia_precede_a_esencia"),
            ("nietzsche", "propuso", "voluntad_de_poder_y_superhombre"),
            ("kant", "propuso", "imperativo_categorico"),
            ("platon", "propuso", "teoria_de_las_formas"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # NUTRICIÓN Y SALUD
    # ════════════════════════════════════════════════════════════════════════

    "nutricion": {
        "label": "nutricion",
        "paginas": [
            "Nutrition", "Macronutrient", "Protein", "Carbohydrate",
            "Fat", "Vitamin", "Mineral", "Metabolism",
            "Caloric restriction", "Intermittent fasting",
        ],
        "relaciones_extra": [
            ("macronutriente", "incluye", "proteina_carbohidrato_grasa"),
            ("proteina", "aporta", "4_kcal_por_gramo"),
            ("carbohidrato", "aporta", "4_kcal_por_gramo"),
            ("grasa", "aporta", "9_kcal_por_gramo"),
            ("ayuno_intermitente", "aumenta", "autofagia"),
            ("ayuno_intermitente", "aumenta", "hgh"),
            ("restriccion_calorica", "asociada_con", "mayor_longevidad"),
            ("vitamina_d", "regula", "absorcion_de_calcio"),
        ],
    },

    "longevidad": {
        "label": "longevidad",
        "paginas": [
            "Longevity", "Aging", "Telomere", "Senescence",
            "Autophagy", "Sirtuins", "Caloric restriction",
            "Blue Zone", "mTOR",
        ],
        "relaciones_extra": [
            ("telomero_corto", "causa", "senescencia_celular"),
            ("autofagia", "limpia", "proteinas_danadas"),
            ("sirtuinas", "regulan", "longevidad"),
            ("mtor", "inhibido_por", "rapamicina_y_ayuno"),
            ("zonas_azules", "lugares_con", "mayor_concentracion_de_centenarios"),
            ("restriccion_calorica", "activa", "sirtuinas"),
            ("ejercicio", "activa", "autofagia"),
        ],
    },

    "ejercicio": {
        "label": "ejercicio",
        "paginas": [
            "Exercise", "High-intensity interval training",
            "Resistance training", "VO2 max", "Lactate threshold",
            "Exercise physiology", "Muscle hypertrophy",
            "Endorphin", "BDNF",
        ],
        "relaciones_extra": [
            ("ejercicio_intenso", "pico_de", "hgh"),
            ("entrenamiento_resistencia", "causa", "hipertrofia_muscular"),
            ("hiit", "mejora", "vo2max_eficientemente"),
            ("bdnf", "aumenta_con", "ejercicio_aerobico"),
            ("bdnf", "promueve", "neurogenesis"),
            ("endorfina", "liberada_durante", "ejercicio_intenso"),
            ("sprint", "mayor_pico_de", "hgh_que_cardio_moderado"),
            ("ejercicio", "reduce", "cortisol_cronico"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # FÍSICA CUÁNTICA APLICADA A LA MENTE (Penrose, Grinberg)
    # ════════════════════════════════════════════════════════════════════════

    "orch_or": {
        "label": "orch_or",
        "paginas": [
            "Orchestrated objective reduction",
            "Roger Penrose", "Stuart Hameroff",
            "Microtubule", "Quantum mind",
        ],
        "busquedas_extra": [
            "Penrose Hameroff quantum consciousness microtubules",
            "Orch OR theory quantum biology mind",
        ],
        "relaciones_extra": [
            ("orch_or", "propuesta_por", "penrose_y_hameroff"),
            ("orch_or", "postula", "consciencia_emerge_de_procesos_cuanticos"),
            ("microtubulo", "estructura_de", "citoesqueleto_neuronal"),
            ("microtubulo", "podria_ser", "sustrato_de_computo_cuantico"),
            ("penrose", "propone", "reduccion_objetiva_de_funcion_de_onda"),
            ("orch_or", "relacionada_con", "teoria_sinteergica_de_grinberg"),
            ("campo_neuronal", "podria_involucrar", "efectos_cuanticos"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # MATEMÁTICAS
    # ════════════════════════════════════════════════════════════════════════

    "matematicas": {
        "label": "matematicas",
        "paginas": [
            "Mathematics", "Calculus", "Linear algebra",
            "Probability theory", "Statistics", "Number theory",
            "Topology", "Chaos theory", "Fractal",
        ],
        "relaciones_extra": [
            ("calculo", "estudia", "cambio_y_acumulacion"),
            ("algebra_lineal", "estudia", "vectores_y_matrices"),
            ("probabilidad", "cuantifica", "incertidumbre"),
            ("teoria_del_caos", "estudia", "sistemas_sensibles_a_condiciones_iniciales"),
            ("fractal", "tiene", "autosimilaridad_a_diferentes_escalas"),
            ("topologia", "estudia", "propiedades_invariantes_ante_deformacion"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # ENERGÍA Y TERMODINÁMICA
    # ════════════════════════════════════════════════════════════════════════

    "termodinamica": {
        "label": "termodinamica",
        "paginas": [
            "Thermodynamics", "Entropy", "Laws of thermodynamics",
            "Heat", "Energy", "Free energy", "Dissipative system",
        ],
        "relaciones_extra": [
            ("primera_ley", "dice", "energia_se_conserva"),
            ("segunda_ley", "dice", "entropia_siempre_aumenta"),
            ("entropia", "mide", "desorden_de_un_sistema"),
            ("energia_libre_gibbs", "determina", "espontaneidad_de_reaccion"),
            ("sistema_disipativo", "mantiene_orden", "consumiendo_energia"),
            ("vida", "es", "sistema_disipativo_de_baja_entropia"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # HISTORIA Y CIVILIZACIONES
    # ════════════════════════════════════════════════════════════════════════

    "civilizaciones_antiguas": {
        "label": "civilizaciones_antiguas",
        "paginas": [
            "Ancient Egypt", "Ancient Greece", "Mesopotamia",
            "Indus Valley Civilisation", "Maya civilization",
            "Roman Empire", "Ancient China",
        ],
        "relaciones_extra": [
            ("egipto_antiguo", "construyo", "piramides"),
            ("grecia_antigua", "origen_de", "democracia_y_filosofia"),
            ("mesopotamia", "invento", "escritura_cuneiforme"),
            ("maya", "desarrollaron", "calendario_preciso"),
            ("roma", "expandio", "derecho_romano"),
            ("china_antigua", "invento", "papel_imprenta_brujula"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # ECONOMÍA
    # ════════════════════════════════════════════════════════════════════════

    "economia": {
        "label": "economia",
        "paginas": [
            "Economics", "Macroeconomics", "Microeconomics",
            "Supply and demand", "Inflation", "Gross domestic product",
            "Behavioral economics", "Game theory",
        ],
        "relaciones_extra": [
            ("macroeconomia", "estudia", "economia_a_nivel_pais"),
            ("microeconomia", "estudia", "decisiones_individuales"),
            ("oferta_demanda", "determina", "precio_de_equilibrio"),
            ("inflacion", "reduce", "poder_adquisitivo"),
            ("pib", "mide", "produccion_total_de_un_pais"),
            ("economia_conductual", "integra", "psicologia_y_economia"),
            ("teoria_de_juegos", "estudia", "decisiones_estrategicas"),
        ],
    },

    # ════════════════════════════════════════════════════════════════════════
    # ESPIRITUALIDAD Y TRADICIONES
    # ════════════════════════════════════════════════════════════════════════

    "budismo": {
        "label": "budismo",
        "paginas": [
            "Buddhism", "Four Noble Truths", "Eightfold Path",
            "Nirvana", "Dharma", "Meditation", "Karma",
            "Theravada", "Mahayana", "Zen Buddhism",
        ],
        "relaciones_extra": [
            ("budismo", "fundado_por", "siddhartha_gautama"),
            ("cuatro_nobles_verdades", "explican", "naturaleza_del_sufrimiento"),
            ("noble_octuple_sendero", "lleva_a", "nirvana"),
            ("karma", "ley_de", "causa_y_efecto"),
            ("nirvana", "es", "cese_del_sufrimiento"),
            ("zen", "enfatiza", "meditacion_y_experiencia_directa"),
        ],
    },

    "chamanismo": {
        "label": "chamanismo",
        "paginas": [
            "Shamanism", "Altered state of consciousness",
            "Ayahuasca", "Peyote", "Spirit", "Trance",
            "Huichol people",
        ],
        "busquedas_extra": [
            "Grinberg Zylberbaum huichol shamans study",
            "shamanic states consciousness neuroscience",
        ],
        "relaciones_extra": [
            ("chaman", "accede_a", "estados_alterados_de_consciencia"),
            ("ayahuasca", "contiene", "dmt"),
            ("dmt", "es", "triptamina_endogena"),
            ("peyote", "contiene", "mescalina"),
            ("huichol", "estudiados_por", "jacobo_grinberg"),
            ("trance_chamanico", "similar_a", "ondas_theta_cerebrales"),
            ("chamanismo", "usa", "plantas_maestras"),
        ],
    },

}

# Alias para reconocer variantes en el chat
ALIAS = {
    "dna": "adn",
    "ácido desoxirribonucleico": "adn",
    "acido desoxirribonucleico": "adn",
    "proteína": "proteina",
    "proteínas": "proteina",
    "péptido": "peptido",
    "péptidos": "peptido",
    "polipéptido": "peptido",
    "polipeptido": "peptido",
    "hormonas": "hormona",
    "growth hormone": "hgh",
    "hormona de crecimiento": "hgh",
    "somatotropina": "hgh",
    "grinberg": "jacobo grinberg",
    "jacobo": "jacobo grinberg",
    "grinberg zylberbaum": "jacobo grinberg",
    "rna": "arn",
    "aminoacido": "proteina",
    "aminoácido": "proteina",
    "enzima": "proteina",
    # neurociencia
    "neurona": "neurociencia",
    "sinapsis": "neurociencia",
    "cerebro": "neurociencia",
    "neuronas": "neurociencia",
    "conciencia": "consciencia",
    "mente": "consciencia",
    "subjetividad": "consciencia",
    # meditacion
    "mindfulness": "meditacion",
    "zen": "meditacion",
    "vipassana": "meditacion",
    # sueno
    "sueño": "sueno",
    "dormir": "sueno",
    "rem": "sueno",
    "melatonina": "sueno",
    # celula
    "célula": "celula",
    "mitocondria": "celula",
    "celulas": "celula",
    # epigenetica
    "epigenética": "epigenetica",
    "metilacion": "epigenetica",
    "telomero": "epigenetica",
    # sistema inmune
    "inmunidad": "sistema_inmune",
    "anticuerpo": "sistema_inmune",
    "inflamacion": "sistema_inmune",
    # microbioma
    "intestino": "microbioma",
    "flora intestinal": "microbioma",
    "probiotico": "microbioma",
    # fisica cuantica
    "cuantica": "mecanica_cuantica",
    "quantum": "mecanica_cuantica",
    "qubit": "computacion_cuantica",
    # relatividad
    "einstein": "relatividad",
    "espacio tiempo": "relatividad",
    "agujero negro": "relatividad",
    # cosmologia
    "big bang": "cosmologia",
    "universo": "cosmologia",
    "materia oscura": "cosmologia",
    # ia
    "ia": "inteligencia_artificial",
    "machine learning": "inteligencia_artificial",
    "deep learning": "inteligencia_artificial",
    "llm": "inteligencia_artificial",
    # psicologia
    "freud": "psicologia",
    "jung": "psicologia",
    "sesgo": "psicologia",
    "emocion": "psicologia",
    "emoción": "psicologia",
    # flow
    "estado de flujo": "flow",
    "csikszentmihalyi": "flow",
    # filosofia
    "filosofía": "filosofia",
    "estoicismo": "filosofia",
    "nietzsche": "filosofia",
    "kant": "filosofia",
    # nutricion
    "nutrición": "nutricion",
    "dieta": "nutricion",
    "ayuno": "nutricion",
    "macronutriente": "nutricion",
    # longevidad
    "envejecimiento": "longevidad",
    "autofagia": "longevidad",
    "telomeros": "longevidad",
    # ejercicio
    "entrenamiento": "ejercicio",
    "deporte": "ejercicio",
    "hiit": "ejercicio",
    "sprint": "ejercicio",
    # orch_or
    "penrose": "orch_or",
    "hameroff": "orch_or",
    "microtubulo": "orch_or",
    "mente cuantica": "orch_or",
    # matematicas
    "matemáticas": "matematicas",
    "calculo": "matematicas",
    "estadistica": "matematicas",
    # termodinamica
    "termodinámica": "termodinamica",
    "entropia": "termodinamica",
    "energía": "termodinamica",
    # historia
    "egipto": "civilizaciones_antiguas",
    "grecia": "civilizaciones_antiguas",
    "roma": "civilizaciones_antiguas",
    "mayas": "civilizaciones_antiguas",
    # economia
    "economía": "economia",
    "inflacion": "economia",
    "mercado": "economia",
    # budismo
    "buda": "budismo",
    "dharma": "budismo",
    "nirvana": "budismo",
    # chamanismo
    "chamán": "chamanismo",
    "ayahuasca": "chamanismo",
    "dmt": "chamanismo",
    "huichol": "chamanismo",
}


# ── Wikipedia reader ──────────────────────────────────────────────────────────

def _wiki_resumen(titulo: str, oraciones: int = 8, lang: str = "es") -> Optional[str]:
    """Obtiene el resumen de una página de Wikipedia (primero en español, luego inglés)."""
    for idioma in [lang, "en"]:
        try:
            q = urllib.parse.quote(titulo.replace(" ", "_"))
            url = f"https://{idioma}.wikipedia.org/api/rest_v1/page/summary/{q}"
            req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            extract = data.get("extract", "").strip()
            if not extract or len(extract) < 50:
                continue
            # Limitar a N oraciones
            frases = re.split(r'(?<=[.!?])\s+', extract)
            return " ".join(frases[:oraciones])
        except Exception:
            continue
    return None


def _wiki_secciones(titulo: str, max_chars: int = 3000, lang: str = "es") -> list[str]:
    """Obtiene párrafos de las primeras secciones de un artículo de Wikipedia."""
    parrafos = []
    for idioma in [lang, "en"]:
        try:
            q = urllib.parse.quote(titulo.replace(" ", "_"))
            url = f"https://{idioma}.wikipedia.org/w/api.php?action=query&titles={q}&prop=extracts&exintro=1&explaintext=1&format=json"
            req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                texto = page.get("extract", "")
                if texto and len(texto) > 100:
                    # Dividir en párrafos no vacíos
                    for p in texto.split("\n"):
                        p = p.strip()
                        if len(p) > 80:
                            parrafos.append(p[:600])
                        if sum(len(x) for x in parrafos) >= max_chars:
                            break
                    break
            if parrafos:
                break
        except Exception:
            continue
    return parrafos


def _extraer_conceptos_del_texto(texto: str) -> list[str]:
    """Extrae sustantivos/conceptos clave del texto usando heurísticas simples."""
    # Palabras en mayúscula (nombres propios, términos técnicos)
    candidatos = re.findall(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\b', texto)
    # También palabras técnicas en minúscula de más de 6 letras
    tecnicos = re.findall(r'\b[a-záéíóúñ]{7,}\b', texto)
    stopwords = {"también", "aunque", "durante", "cuando", "porque", "siendo",
                 "tienen", "pueden", "través", "proceso", "función", "estructura",
                 "ejemplo", "primera", "segunda", "tercera", "importante"}
    conceptos = []
    vistos = set()
    for c in candidatos + tecnicos:
        c_lower = c.lower()
        if c_lower not in stopwords and c_lower not in vistos and len(c_lower) > 4:
            conceptos.append(c_lower)
            vistos.add(c_lower)
    return conceptos[:20]


# ── Motor de aprendizaje profundo ─────────────────────────────────────────────

def aprender_tema(ai, clave: str) -> dict:
    """
    Aprende un tema completo desde Wikipedia y lo guarda en toda la memoria de Cognia.
    Retorna un dict con estadísticas del aprendizaje.
    """
    clave_norm = clave.lower().strip()
    # Resolver alias
    clave_norm = ALIAS.get(clave_norm, clave_norm)

    if clave_norm not in TEMAS_PREDEFINIDOS:
        return {
            "ok": False,
            "error": f"No tengo un plan de aprendizaje para '{clave}'. "
                     f"Temas disponibles: {', '.join(sorted(TEMAS_PREDEFINIDOS.keys()))}"
        }

    tema = TEMAS_PREDEFINIDOS[clave_norm]
    label = tema["label"]
    stats = {
        "paginas_leidas": 0,
        "episodios_guardados": 0,
        "triples_kg": 0,
        "conceptos_semanticos": 0,
        "errores": [],
    }

    try:
        from cognia_v3 import text_to_vector, analyze_emotion
    except ImportError:
        return {"ok": False, "error": "No se pudo importar cognia_v3"}

    # ── FASE 1: Leer páginas de Wikipedia y guardar en memoria ───────────────
    for titulo_wiki in tema["paginas"]:
        try:
            # Intentar primero en español, luego en inglés como fallback
            resumen = _wiki_resumen(titulo_wiki, oraciones=6, lang="es")
            if not resumen:
                resumen = _wiki_resumen(titulo_wiki, oraciones=6, lang="en")
            if not resumen:
                stats["errores"].append(f"Sin contenido: {titulo_wiki}")
                continue

            # Guardar resumen como episodio
            vec = text_to_vector(resumen)
            emotion = analyze_emotion(resumen)
            ai.episodic.store(
                observation=resumen,
                label=label,
                vector=vec,
                confidence=0.75,
                importance=0.80,
                emotion=emotion,
                surprise=0.1,
                context_tags=["wikipedia", "aprendizaje_profundo", label],
            )
            stats["episodios_guardados"] += 1

            # Actualizar memoria semántica con el concepto
            ai.semantic.update_concept(label, vec,
                                       description=resumen[:200],
                                       confidence_delta=0.15)
            stats["conceptos_semanticos"] += 1

            # Extraer sub-conceptos del texto y asociarlos
            sub_conceptos = _extraer_conceptos_del_texto(resumen)
            for sub in sub_conceptos[:8]:
                sub_vec = text_to_vector(sub)
                ai.semantic.update_concept(sub, sub_vec,
                                           description=f"Concepto relacionado con {label}",
                                           confidence_delta=0.05)
                ai.semantic.add_association(label, sub, 0.6)
                ai.semantic.add_association(sub, label, 0.5)
                stats["conceptos_semanticos"] += 1

            # Guardar párrafos adicionales de las secciones
            parrafos = _wiki_secciones(titulo_wiki, max_chars=2000, lang="es")
            if not parrafos:
                parrafos = _wiki_secciones(titulo_wiki, max_chars=2000, lang="en")
            for i, parrafo in enumerate(parrafos[:4]):
                if len(parrafo) < 80:
                    continue
                vec_p = text_to_vector(parrafo)
                ai.episodic.store(
                    observation=parrafo,
                    label=label,
                    vector=vec_p,
                    confidence=0.65,
                    importance=0.65,
                    emotion=analyze_emotion(parrafo),
                    surprise=0.05,
                    context_tags=["wikipedia", label, titulo_wiki.lower()],
                )
                stats["episodios_guardados"] += 1

                # Extraer triples del texto con el motor existente de Cognia
                triples = ai.kg.extract_triples_from_text(parrafo, label)
                for subj, pred, obj in triples:
                    is_new = ai.kg.add_triple(subj, pred, obj, weight=0.7, source="wikipedia")
                    if is_new:
                        stats["triples_kg"] += 1

            stats["paginas_leidas"] += 1
            time.sleep(0.3)  # respetar rate limit de Wikipedia

        except Exception as ex:
            stats["errores"].append(f"{titulo_wiki}: {ex}")
            continue

    # ── FASE 2: Inyectar relaciones curadas manualmente ──────────────────────
    for subj, pred, obj in tema.get("relaciones_extra", []):
        try:
            is_new = ai.kg.add_triple(subj, pred, obj, weight=1.0, source="curado")
            if is_new:
                stats["triples_kg"] += 1
            # También crear asociación semántica bidireccional
            v_subj = text_to_vector(subj.replace("_", " "))
            v_obj  = text_to_vector(obj.replace("_", " "))
            ai.semantic.update_concept(subj, v_subj, confidence_delta=0.10)
            ai.semantic.update_concept(obj,  v_obj,  confidence_delta=0.10)
            ai.semantic.add_association(subj, obj, 0.75)
            stats["conceptos_semanticos"] += 1
        except Exception as ex:
            stats["errores"].append(f"Relación {subj}->{obj}: {ex}")

    # ── FASE 3: Búsquedas extra (solo para Grinberg y temas con poco en Wiki) ──
    for busqueda in tema.get("busquedas_extra", []):
        try:
            texto = _wiki_resumen(busqueda, oraciones=5, lang="en")
            if texto:
                vec = text_to_vector(texto)
                ai.episodic.store(
                    observation=texto,
                    label=label,
                    vector=vec,
                    confidence=0.60,
                    importance=0.70,
                    emotion=analyze_emotion(texto),
                    surprise=0.15,
                    context_tags=["wikipedia", label, "investigacion"],
                )
                stats["episodios_guardados"] += 1
        except Exception as ex:
            stats["errores"].append(f"Búsqueda extra '{busqueda}': {ex}")

    # ── FASE 4: Conectar con conceptos que Cognia ya conoce ──────────────────
    try:
        vec_label = text_to_vector(label.replace("_", " "))
        ya_conoce = ai.semantic.find_related(vec_label, top_k=5)
        for concepto_conocido in ya_conoce:
            c = concepto_conocido.get("concept", "")
            sim = concepto_conocido.get("similarity", 0)
            if c and c != label and sim > 0.35:
                ai.semantic.add_association(label, c, sim * 0.8)
                ai.semantic.add_association(c, label, sim * 0.7)
                stats["conceptos_semanticos"] += 1
    except Exception:
        pass

    stats["ok"] = True
    return stats


def formatear_resultado(clave: str, stats: dict) -> str:
    """Formatea el resultado del aprendizaje para mostrar en el chat."""
    if not stats.get("ok"):
        return f"❌ {stats.get('error', 'Error desconocido')}"

    lineas = [
        f"🧠 Aprendizaje completado: **{clave.upper()}**\n",
        f"  📖  Páginas Wikipedia leídas : {stats['paginas_leidas']}",
        f"  💾  Episodios guardados       : {stats['episodios_guardados']}",
        f"  🕸️  Triples en Knowledge Graph: {stats['triples_kg']}",
        f"  🔗  Conceptos semánticos      : {stats['conceptos_semanticos']}",
    ]
    if stats["errores"]:
        lineas.append(f"\n  ⚠️  Advertencias ({len(stats['errores'])}): "
                      + " | ".join(stats["errores"][:3]))
    lineas.append("\n✅ Ahora puedes preguntarme sobre este tema y usaré esta memoria.")
    return "\n".join(lineas)


# ── Integración con Flask / web_app.py ────────────────────────────────────────

def register_routes_aprendizaje(app, ai_getter):
    from flask import request, jsonify

    @app.route("/api/aprender", methods=["POST"])
    def api_aprender():
        data = request.get_json()
        tema = data.get("tema", "").strip().lower()
        if not tema:
            return jsonify({"error": "Falta el campo 'tema'"})
        ai = ai_getter()
        stats = aprender_tema(ai, tema)
        return jsonify({
            "ok": stats.get("ok", False),
            "response": formatear_resultado(tema, stats),
            "stats": stats,
        })

    @app.route("/api/temas_disponibles")
    def api_temas():
        return jsonify({
            "temas": sorted(TEMAS_PREDEFINIDOS.keys()),
            "alias": ALIAS,
        })

    print("[OK] Aprendizaje profundo activo — comandos: 'aprender adn', 'aprender hgh', etc.")
