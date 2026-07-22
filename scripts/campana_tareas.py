# -*- coding: utf-8 -*-
"""
Campana de 80 tareas DURAS (goal 2026-07-21): 20 diseno web + 40 codigo duro
+ 20 agentes/calibracion de herramientas. Cada tarea es multi-componente
(escala grande a proposito) y cierra con POSTCONDICION automatica. Los
resultados van a ~/.cognia/campana/resultados.jsonl para el analisis entre
lotes (revisar fallos -> mejorar a Cognia -> siguiente lote).

    python scripts/campana_tareas.py --lote web   [--desde 0 --hasta 20]
    python scripts/campana_tareas.py --lote code  [--desde 0 --hasta 40]
    python scripts/campana_tareas.py --lote agent [--desde 0 --hasta 20]

Honestidad de la escala: el arnes MIDE chars generados por ronda y estima
tokens (chars/4, el mismo estimador del backend); el objetivo >30k tokens se
reporta por tarea, no se maquilla.
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

SALIDA = Path.home() / ".cognia" / "campana"
SALIDA.mkdir(parents=True, exist_ok=True)
RESULTADOS = SALIDA / "resultados.jsonl"

# ═══════════════════ LOTE WEB: 20 disenos duros ═══════════════════
# check = regexes que el HTML final DEBE contener (features pedidas).
WEB = [
    ("panel_trading", "pagina web de un panel de trading profesional: 6 tarjetas de activos con precio animado, grafico de velas en canvas, libro de ordenes lateral, ticker superior en marquesina, modo oscuro, y colores verde/rojo segun sube o baja",
     [r"<canvas|<svg", r"setInterval|requestAnimationFrame", r"(verde|green|#\s*[0-9a-f]*4caf|#16c784|rgb)", r"dark|oscuro|#0|#1"]),
    ("kanban", "pagina web de un tablero kanban con 4 columnas, tarjetas arrastrables con drag and drop nativo, contador por columna, boton para agregar tarjeta con formulario modal, y persistencia en localStorage",
     [r"draggable|dragstart", r"localStorage", r"modal|dialog", r"appendChild|insertBefore"]),
    ("editor_md", "pagina web de un editor markdown a dos paneles: textarea a la izquierda, vista previa renderizada en vivo a la derecha (negrita, titulos, listas, codigo), contador de palabras, boton copiar HTML y tema claro/oscuro",
     [r"textarea", r"innerHTML|createElement", r"\*\*|##|replace", r"(claro|oscuro|dark|light)"]),
    ("juego_memoria", "pagina web de un juego de memoria de 16 cartas con volteo animado 3D en CSS, contador de intentos, cronometro, deteccion de pares, y pantalla de victoria con confeti animado",
     [r"transform|rotateY", r"setInterval|Date\.now", r"flip|volte", r"victoria|ganaste|win"]),
    ("dashboard_iot", "pagina web de un dashboard IoT de una casa inteligente: 8 sensores con gauges circulares SVG animados, historial en grafico de linea canvas, alertas parpadeantes cuando un valor cruza umbral, y panel lateral colapsable",
     [r"<svg|<circle|stroke-dasharray", r"<canvas|<svg", r"alerta|alert|umbral|threshold", r"setInterval"]),
    ("spotify_clon", "pagina web tipo reproductor de musica: barra de reproduccion inferior con progreso animado, grilla de 12 albumes con hover, cola de reproduccion lateral, visualizador de barras animadas, y controles play/pausa/siguiente funcionales",
     [r"play|pausa|pause", r"progress|progreso", r"hover|:hover", r"animation|transition|keyframes"]),
    ("banco_app", "pagina web de una app bancaria: resumen de 3 cuentas con saldos, grafico de gastos por categoria en dona SVG, lista de 15 transacciones con iconos y colores por tipo, transferencia con formulario validado y modal de confirmacion",
     [r"<svg|stroke-dasharray|conic-gradient", r"transaccion|transaction", r"required|validat|pattern", r"modal|dialog"]),
    ("clima_pro", "pagina web del clima: tarjeta principal con animacion del icono segun clima (sol rotando, lluvia cayendo en CSS), pronostico de 7 dias, grafico de temperatura en canvas o svg, fondo con gradiente que cambia segun la hora simulada",
     [r"keyframes|animation", r"<canvas|<svg|polyline", r"gradient", r"pronostico|forecast|7"]),
    ("terminal_web", "pagina web que simula una terminal retro: fondo negro, texto verde fosforescente con efecto scanlines CSS, prompt que acepta comandos (help, ls, clear, date, echo), historial con flechas, y cursor parpadeante",
     [r"scanline|repeating-linear|opacity", r"keydown|addEventListener", r"help", r"blink|parpade|cursor"]),
    ("portfolio_3d", "pagina web de portafolio con tarjetas que rotan en 3D al mover el mouse (perspective y transform), seccion de habilidades con barras animadas al hacer scroll, navegacion con scroll suave y menu hamburguesa responsive",
     [r"perspective|rotate3d|rotateX", r"mousemove|IntersectionObserver|scroll", r"hamburg|menu", r"@media"]),
    ("tienda", "pagina web de tienda: grilla de 9 productos con precio y descuento tachado, carrito lateral deslizante con contador en el icono, sumar/quitar unidades, calculo de total con envio gratis sobre umbral, y toast de confirmacion",
     [r"carrito|cart", r"total", r"toast|notificac", r"translateX|slide|transition"]),
    ("mapa_metro", "pagina web con un mapa de metro ficticio dibujado en SVG: 4 lineas de colores, 20 estaciones clicables que muestran ficha emergente, animacion de un tren circulando por una linea, y buscador de estaciones que resalta la coincidencia",
     [r"<svg", r"circle|station|estacion", r"animateMotion|animation|setInterval", r"input|buscador|search"]),
    ("cocina_recetas", "pagina web de recetas: 6 tarjetas con imagen en gradiente CSS, filtros por categoria con chips activos, vista detalle con pasos numerados y checkboxes de progreso, escalador de porciones que recalcula cantidades, y barra de progreso de la receta",
     [r"chip|filtro|filter", r"checkbox", r"porcion|serving|escala", r"progress|progreso"]),
    ("crypto_ticker", "pagina web de mercado cripto: tabla de 10 monedas con precio actualizandose cada segundo con flash verde/rojo, sparklines en canvas por fila, ordenar por columna al clicar el encabezado, y buscador con filtrado en vivo",
     [r"setInterval", r"<canvas|<svg", r"sort|ordenar", r"filter|filtrado|includes"]),
    ("presentacion", "pagina web de presentacion por diapositivas: 6 slides a pantalla completa con transiciones CSS distintas, navegacion con flechas del teclado y puntos laterales, barra de progreso superior, y modo autoplay con pausa",
     [r"keydown|ArrowRight", r"transition|transform", r"autoplay|setInterval", r"progress|progreso"]),
    ("chat_ui", "pagina web de interfaz de chat: burbujas propias y ajenas con colas CSS, indicador de escribiendo con tres puntos animados, respuestas automaticas simuladas con retardo, emojis rapidos, scroll automatico y hora en cada mensaje",
     [r"burbuja|bubble|msg", r"escribiendo|typing", r"setTimeout", r"scrollTop|scrollIntoView"]),
    ("panel_admin", "pagina web de panel de administracion: sidebar colapsable con iconos SVG inline, 4 KPIs con contadores que suben animados al cargar, tabla de 20 usuarios con paginacion y busqueda, grafico de barras en CSS puro, y breadcrumbs",
     [r"<svg", r"sidebar", r"pagina|pagination|page", r"contador|counter|animad"]),
    ("pomodoro", "pagina web de un temporizador pomodoro: circulo de progreso SVG que se vacia con el tiempo, fases trabajo/descanso con colores distintos, registro de sesiones completadas con racha, sonido simulado con vibracion visual, y ajustes de duracion",
     [r"stroke-dashoffset|dasharray", r"trabajo|focus|descanso|break", r"racha|streak|sesion", r"setInterval"]),
    ("galeria_fotos", "pagina web de galeria masonry con 12 tarjetas de alturas variables en gradientes CSS, lightbox al clic con navegacion y cierre con Escape, filtros por etiqueta animados con FLIP o transiciones, y contador de vistas por foto",
     [r"masonry|column|grid", r"lightbox|modal", r"Escape|keydown", r"transition|animation"]),
    ("flujo_pago", "pagina web de un checkout de 3 pasos con stepper visual: datos, tarjeta con vista previa que se voltea al escribir el CVV, y confirmacion con resumen; validacion en vivo con mensajes, formateo del numero de tarjeta en bloques de 4, y animacion de exito",
     [r"stepper|paso|step", r"rotateY|flip|volte", r"replace\(|match\(|formato", r"exito|success|confirmac"]),
]

# ═══════════════════ LOTE CODE: 40 tareas duras ═══════════════════
# check = funcion sobre el stdout del programa (o regex) que DEBE cumplirse.
CODE = [
    ("dijkstra", "programa que construye un grafo dirigido de 100 nodos con pesos deterministas (semilla 42), corre Dijkstra desde el nodo 0, e imprime la distancia al nodo 99 y el camino completo", [r"\b\d+\b", r"camino|path|->"]),
    ("interprete_calc", "interprete de expresiones aritmeticas con parser recursivo descendente: soporta + - * / ^ parentesis y variables con asignacion; evalua un programa de 8 lineas de ejemplo e imprime cada resultado", [r"=|resultado", r"\d"]),
    ("btree", "arbol B de orden 4 implementado desde cero: insertar 50 claves, borrar 10, busqueda de rango [20,60], e imprimir el arbol por niveles y el resultado del rango", [r"nivel|level|\[", r"\d+"]),
    ("regex_engine", "motor de expresiones regulares basico desde cero (sin re): soporta literales, ., *, +, ?, clases [a-z] y anclas ^$; corre 12 casos de prueba e imprime PASS/FAIL por caso y el total", [r"PASS", r"12|total"]),
    ("json_parser", "parser de JSON completo desde cero (sin json): objetos, arrays, strings con escapes, numeros, bool y null; parsea un documento de prueba anidado de 4 niveles e imprime su estructura y la suma de todos los numeros encontrados", [r"suma|sum", r"\d"]),
    ("huffman", "compresor Huffman completo: construye el arbol para un texto de 500+ chars, genera codigos, comprime y descomprime verificando identidad, e imprime la tabla de codigos y el ratio de compresion", [r"ratio", r"OK|identic|igual"]),
    ("sudoku", "resolvedor de sudoku con backtracking y propagacion de restricciones: resuelve un tablero dificil dado, imprime el tablero resuelto y la cantidad de backtracks", [r"backtrack", r"[1-9]{9}|\d \d \d"]),
    ("astar_lab", "generador de laberinto 40x40 con DFS y resolvedor A* con heuristica manhattan: imprime el laberinto con el camino marcado y la longitud del camino", [r"#|█", r"camino|longitud|path"]),
    ("vm_stack", "maquina virtual de pila con 12 opcodes (push, add, mul, jmp, jz, call, ret, print...): ensambla y ejecuta un programa que calcula factorial de 10 e imprime 3628800", [r"3628800"]),
    ("markdown_html", "conversor markdown a HTML desde cero: titulos, negrita, cursiva, listas anidadas, codigo inline y bloques, enlaces; convierte un documento de prueba e imprime el HTML y un conteo de elementos convertidos", [r"<h[1-3]>", r"<li>", r"<code>|<pre>"]),
    ("lru_ttl", "cache LRU con TTL y estadisticas: capacidad 10, expiracion simulada con reloj logico, 40 operaciones de prueba; imprime hits, misses, evicciones por LRU y por TTL", [r"hit", r"miss", r"evic"]),
    ("csv_sql", "mini motor SQL sobre CSV en memoria: SELECT con WHERE, ORDER BY, GROUP BY con COUNT/SUM; genera 50 filas deterministas y ejecuta 5 consultas imprimiendo resultados tabulados", [r"SELECT|consulta", r"\d"]),
    ("bloom", "filtro de Bloom con 3 hashes: inserta 1000 elementos, verifica 100 presentes y 100 ausentes, mide falsos positivos reales vs teoricos e imprime ambos", [r"falso", r"%|0\."]),
    ("diff_lcs", "algoritmo diff basado en LCS: compara dos textos de 15 lineas con cambios, imprime el diff unificado con + y - y las estadisticas de lineas agregadas/borradas", [r"^\+|agregad", r"^-|borrad"]),
    ("trie_auto", "autocompletado con trie: inserta 100 palabras, consulta 5 prefijos imprimiendo hasta 5 sugerencias por prefijo ordenadas por frecuencia, y muestra el conteo de nodos del trie", [r"sugerencia|sugeren", r"nodos|\d+"]),
    ("skiplist", "skip list desde cero con niveles aleatorios (semilla fija): insertar 100, buscar 20, borrar 10; imprime la estructura por niveles y el resultado de las busquedas", [r"nivel|level", r"encontrad|True|OK"]),
    ("scheduler", "planificador round-robin con prioridades y quantum: simula 8 procesos con llegadas y rafagas distintas, imprime el diagrama de Gantt en ASCII y los tiempos de espera y retorno promedio", [r"Gantt|\|", r"promedio|avg"]),
    ("banco_txn", "sistema de transacciones bancarias con bloqueo de dos fases simulado y deteccion de deadlock por grafo de espera: corre un escenario con deadlock, lo detecta, aborta una transaccion e imprime el estado final consistente", [r"deadlock", r"abort", r"consistente|final"]),
    ("mini_git", "mini control de versiones en memoria: commit con hash del contenido, log, diff entre commits, y branch+merge sin conflictos; corre un flujo de 8 operaciones e imprime el log final con hashes", [r"commit", r"[0-9a-f]{6,}", r"merge"]),
    ("wavefront", "expansion wavefront para robots: en una grilla 30x30 con obstaculos, calcula el campo de distancias desde la meta y traza el camino desde 3 origenes distintos, imprimiendo la grilla con los caminos", [r"meta|goal|G", r"camino|path"]),
    ("kmeans", "k-means desde cero: 200 puntos 2D deterministas en 4 clusters reales, corre con k=4 hasta convergencia, imprime centroides finales, inercia y cuantos puntos por cluster", [r"centroide|centroid", r"inercia|inertia", r"\d+"]),
    ("nqueens", "N-reinas para N=10 con backtracking y conteo de soluciones: imprime la primera solucion como tablero y el total de soluciones (724)", [r"724"]),
    ("rpn_compiler", "compilador de expresiones infijas a RPN (shunting yard) + evaluador: procesa 8 expresiones con precedencias y parentesis, imprime la RPN y el valor de cada una", [r"RPN|postfij", r"\d"]),
    ("game_of_life", "juego de la vida: tablero 25x25 con un glider y un blinker, simula 20 generaciones, imprime la generacion 0, 10 y 20 y el conteo de celulas vivas por generacion mostrada", [r"generacion|gen", r"vivas|alive|\d+"]),
    ("hash_map", "hash map desde cero con encadenamiento y rehash al factor de carga 0.75: 200 inserciones, imprime colisiones totales, rehashes hechos, y verifica 20 lecturas", [r"colision", r"rehash", r"OK|True"]),
    ("dns_resolver", "simulador de resolucion DNS con cache y TTL: arbol de zonas raiz->tld->dominio, resuelve 10 consultas (5 repetidas), imprime la traza de cada resolucion y hits de cache", [r"cache", r"hit", r"\."]),
    ("matrix_expr", "algebra matricial desde cero: multiplicacion, transpuesta, determinante por LU y resolucion de sistema 5x5 determinista; imprime el determinante y la solucion verificando Ax=b", [r"determinante|det", r"solucion|x =|verificad"]),
    ("tokenizer_bpe", "tokenizador BPE desde cero: entrena 50 merges sobre un corpus de 300+ palabras, tokeniza 3 frases nuevas imprimiendo los tokens y el tamano del vocabulario", [r"vocab", r"merge", r"token"]),
    ("elevador", "simulador de 2 ascensores con planificacion SCAN: 15 llamadas con tiempos de llegada, imprime la traza temporal de cada ascensor y el tiempo de espera promedio", [r"ascensor|elevator", r"promedio|avg"]),
    ("mercado", "simulador de mercado con libro de ordenes: 30 ordenes limit/market deterministas, matching por precio-tiempo, imprime cada trade ejecutado y el libro final con spreads", [r"trade", r"spread|libro", r"\d"]),
    ("chess_moves", "generador de movimientos legales de ajedrez para una posicion dada (sin enroque ni al paso): valida jaques, imprime todos los movimientos legales de las blancas y el conteo (perft 1)", [r"perft|conteo|total", r"[a-h][1-8]"]),
    ("raytracer", "mini raytracer por consola: 3 esferas con luz puntual y sombras, renderiza 60x30 en ASCII por niveles de brillo e imprime la imagen", [r"[.:*#@]{10,}"]),
    ("crdt_counter", "CRDT de contador G-Counter y PN-Counter para 3 nodos con merges: simula incrementos concurrentes y particiones, imprime el estado por nodo antes y despues del merge y el valor convergido", [r"merge", r"converg", r"\d+"]),
    ("paginacion", "simulador de memoria virtual con paginacion: 3 algoritmos de reemplazo (FIFO, LRU, Clock) sobre la misma traza de 30 referencias, imprime fallos de pagina por algoritmo y la tabla final", [r"FIFO", r"LRU", r"fallos|faults"]),
    ("fsm_regex", "conversor de regex a AFN (Thompson) y AFN a AFD (subconjuntos): para (a|b)*abb imprime las tablas de transicion de ambos y valida 6 cadenas", [r"AFN|NFA", r"AFD|DFA", r"acepta|True|PASS"]),
    ("rope", "estructura rope para texto: concatenar, insertar, borrar y indexar sobre un texto de 1000 chars con 20 operaciones, imprime la profundidad del arbol y verifica contra un string plano", [r"profundidad|depth", r"OK|igual|True"]),
    ("interval_tree", "arbol de intervalos: inserta 30 intervalos, consulta 10 puntos y 5 rangos imprimiendo los solapamientos de cada consulta, y valida contra fuerza bruta", [r"solap|overlap", r"OK|coincide|True"]),
    ("tsp_heur", "TSP con 15 ciudades deterministas: compara vecino mas cercano vs 2-opt partiendo de esa solucion, imprime ambas rutas con sus longitudes y el porcentaje de mejora", [r"mejora|%", r"ruta|tour"]),
    ("log_parser", "analizador de logs: genera 200 lineas de log determin...istas con niveles y timestamps, detecta rafagas de errores (ventana deslizante), top 5 mensajes frecuentes, e imprime un reporte estructurado", [r"ERROR", r"top|frecuent", r"rafaga|burst|ventana"]),
    ("units_calc", "calculadora con unidades fisicas: suma/multiplica cantidades con dimensiones (m, s, kg y derivadas), detecta incompatibilidades como error, corre 10 casos e imprime cada resultado con su unidad", [r"m/s|kg|N|J", r"error|incompatible", r"\d"]),
]

# ═══════════════════ LOTE AGENT: 20 tareas de herramientas ═══════════════════
# Cada tarea corre en un workspace limpio; check = postcondiciones sobre disco
# y/o la respuesta. Fuerzan CADENAS de tools (escribir+leer+ejecutar+buscar).
AGENT = [
    ("pipeline_csv", "crea un archivo datos.csv con 20 filas de ventas (producto,unidades,precio) valores deterministas, luego un script analiza.py que lo lea y escriba resumen.txt con el total por producto ordenado, ejecutalo y verifica leyendo resumen.txt",
     ["datos.csv", "analiza.py", "resumen.txt"], [r"total|producto"]),
    ("config_migra", "crea config_v1.json con 6 claves anidadas, luego un script migra.py que lo transforme al formato v2 (claves renombradas y version=2) guardando config_v2.json, ejecutalo y muestra el resultado",
     ["config_v1.json", "migra.py", "config_v2.json"], [r"version.*2|v2"]),
    ("toolchain_notas", "crea 3 archivos de notas (nota1.txt nota2.txt nota3.txt) con contenido distinto sobre planetas, busca la palabra 'marte' en ellos, crea indice.md con una tabla de que archivo la contiene, y leelo para confirmar",
     ["nota1.txt", "indice.md"], [r"marte|Marte"]),
    ("gen_y_test", "escribe modulo mates.py con funciones primo(n) y fibonacci(n) iterativa, escribe test_mates.py con 6 asserts, ejecuta los tests con pytest y reporta el resultado",
     ["mates.py", "test_mates.py"], [r"6 passed|passed"]),
    ("scraper_local", "crea pagina.html con una tabla de 5 paises y capitales, escribe extrae.py que la parsee sin librerias externas y escriba capitales.json, ejecutalo y lee el json para verificar las 5 capitales",
     ["pagina.html", "extrae.py", "capitales.json"], [r"capital|Paris|Lima"]),
    ("refactor_seguro", "crea legacy.py con una funcion de 30 lineas que mezcla calculo de impuestos y formato de reporte, refactorizala en dos funciones puras + main, crea test_legacy.py que verifique que el output es identico al original, y corre los tests",
     ["legacy.py", "test_legacy.py"], [r"passed"]),
    ("inventario", "crea inventario.json con 10 items (nombre,stock,minimo), escribe reponer.py que genere orden_compra.txt solo con los items bajo minimo y cantidades a pedir, ejecutalo y verifica el contenido",
     ["inventario.json", "reponer.py", "orden_compra.txt"], [r"pedir|cantidad|item"]),
    ("bitacora_rotada", "escribe rotador.py que genere bitacora.log con 50 lineas timestamped, la rote cuando pase de 30 lineas creando bitacora.1.log y dejando las ultimas 20 en el activo, ejecutalo dos veces y lista los archivos resultantes",
     ["rotador.py", "bitacora.log"], [r"bitacora\.1\.log|rotad"]),
    ("csv_a_sqlite", "crea empleados.csv con 12 filas, escribe carga.py que lo importe a empleados.db (sqlite3), consulte el salario promedio por departamento y escriba reporte.txt, ejecutalo y lee el reporte",
     ["empleados.csv", "carga.py", "reporte.txt"], [r"promedio|departamento"]),
    ("guardian_config", "crea app_config.yaml con 8 claves (formato yaml simple), escribe validador.py que verifique tipos y rangos esperados imprimiendo VALIDO o los errores, rompe una clave a proposito en config_rota.yaml, corre el validador sobre ambos y muestra la diferencia",
     ["app_config.yaml", "validador.py", "config_rota.yaml"], [r"VALIDO", r"error|invalid"]),
    ("empaquetador", "crea la estructura de un paquete python minipkg/ con __init__.py, core.py (2 funciones) y README.md, escribe un smoke.py fuera del paquete que lo importe y use ambas funciones, ejecutalo y reporta",
     ["minipkg/__init__.py", "minipkg/core.py", "smoke.py"], [r"OK|funciona|resultado"]),
    ("detective_bug", "crea buggy.py con una funcion de estadisticas que tiene 2 bugs sutiles (division por cero con lista vacia y mediana mal calculada en pares), escribe test_buggy.py que los exponga, corre los tests viendo fallar, arregla buggy.py y corre de nuevo hasta verde",
     ["buggy.py", "test_buggy.py"], [r"passed"]),
    ("markdown_reporte", "lee los archivos python del directorio actual, cuenta lineas y funciones de cada uno, y genera reporte_codigo.md con una tabla resumen y el total general",
     ["reporte_codigo.md"], [r"\|.*\|", r"total|Total"]),
    ("secuencia_ordenes", "crea ordenes.txt con 15 ordenes (una por linea: fecha,cliente,monto), escribe proceso.py que las agrupe por cliente, calcule el total y genere por_cliente/<cliente>.txt para cada uno, ejecutalo y lista el directorio",
     ["ordenes.txt", "proceso.py"], [r"por_cliente|cliente"]),
    ("api_mock", "escribe servidor_mock.py con http.server que responda /salud con JSON ok y /doble/<n> con el doble, arrancalo en background en el puerto 8123, haz una peticion de prueba con urllib a ambas rutas, muestra las respuestas y para el servidor",
     ["servidor_mock.py"], [r"ok", r"doble|8123"]),
    ("limpieza_datos", "crea sucio.csv con 15 filas que incluyan duplicados, espacios extra y fechas en 2 formatos, escribe limpia.py que normalice todo a limpio.csv reportando cuantas correcciones hizo de cada tipo, ejecutalo y muestra el reporte",
     ["sucio.csv", "limpia.py", "limpio.csv"], [r"duplicad|correc|normaliz"]),
    ("arbol_proyecto", "crea una estructura app/{models,views,utils}/ con 2 archivos python triviales en cada una, genera ARBOL.md con el arbol del proyecto y un conteo de archivos por carpeta usando la herramienta arbol, y verifica leyendolo",
     ["ARBOL.md"], [r"models", r"views", r"\d"]),
    ("diario_agente", "crea un diario horario.json con tu plan de 5 tareas ficticias con horas, escribe chequea.py que diga cual tarea tocaria ahora mismo segun la hora actual del sistema, ejecutalo, y anota el resultado en memoria de trabajo con la tool anotar",
     ["horario.json", "chequea.py"], [r"tarea|ahora"]),
    ("versionado_manual", "crea codigo.py con una funcion, copialo a versiones/v1_codigo.py, mejoralo agregando docstring y manejo de errores, copialo a versiones/v2_codigo.py, y genera CHANGELOG.md con las diferencias entre v1 y v2",
     ["versiones/v1_codigo.py", "versiones/v2_codigo.py", "CHANGELOG.md"], [r"v1|v2", r"docstring|error"]),
    ("orquesta_final", "crea un mini proyecto: datos.json con 8 registros, transforma.py que los procese a salida.json, verifica.py que valide la salida imprimiendo VERIFICADO, un README.md documentando el flujo, ejecuta ambos scripts en orden y muestra la validacion",
     ["datos.json", "transforma.py", "verifica.py", "README.md"], [r"VERIFICADO"]),
]


def _estimar_tokens(*textos) -> int:
    return sum(len(t or "") for t in textos) // 4


def _registrar(reg: dict) -> None:
    with RESULTADOS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")


def _ai_con_backend():
    """Cognia con su orquestador MATERIALIZADO (sin esto, program_creator no
    ve backend y cae a Ollama — cazado en el humo del lote web)."""
    # patron EXACTO de scripts/e2e_happy_path.py (probado 5/5): apply_config +
    # orquestador local + shim _AI. NO usar Cognia() completo: su estado global
    # dejaba el infer en la ruta de shards y se colgaba (medido en el humo).
    from cognia.first_run import apply_config
    apply_config()
    from shattering.orchestrator import ShatteringOrchestrator
    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()
    r = orch.infer("di ok", max_tokens=4)
    assert r is not None and getattr(r, "mode", "") != "simulation",         f"backend no vivo: {getattr(r, 'mode', None)}"

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch
    return ai


def _artefacto(res, storage: Path, patron: str) -> tuple[str, str]:
    """(contenido, ruta) del artefacto guardado: via res.programs si hay,
    si no el mas reciente que case el patron en el storage aislado."""
    try:
        for meta in reversed(getattr(res, "programs", []) or []):
            d = Path(meta.directory)
            for f in sorted(d.glob(patron)):
                return f.read_text(encoding="utf-8", errors="replace"), str(f)
    except Exception:
        pass
    cand = sorted(storage.rglob(patron), key=lambda p: p.stat().st_mtime)
    if cand:
        p = cand[-1]
        return p.read_text(encoding="utf-8", errors="replace"), str(p)
    return "", ""


def correr_web(desde: int, hasta: int) -> None:
    from cognia.program_creator.program_creator import crear_hasta_lograr
    ai = _ai_con_backend()
    for i, (nombre, idea, checks) in enumerate(WEB[desde:hasta], start=desde):
        t0 = time.time()
        reg = {"lote": "web", "i": i, "nombre": nombre,
               "ts": datetime.now().isoformat(timespec="seconds")}
        storage = SALIDA / "prog_web" / nombre
        try:
            res = crear_hasta_lograr(idea, max_rondas=3, verbose=False,
                                     storage_dir=storage,
                                     cognia_instance=ai)
            html, ruta = _artefacto(res, storage, "*.html")
            faltan = [c for c in checks
                      if not re.search(c, html, re.I | re.S)]
            reg.update(ok=bool(html) and not faltan, ruta=ruta,
                       html_chars=len(html), faltan=faltan,
                       intentos=getattr(res, "attempted", None),
                       guardados=getattr(res, "stored", None),
                       tokens_est=_estimar_tokens(html) * max(
                           1, getattr(res, "attempted", 1) or 1))
        except Exception as e:
            reg.update(ok=False, error=repr(e)[:300])
        reg["seg"] = round(time.time() - t0)
        _registrar(reg)
        print(f"[{'OK ' if reg.get('ok') else 'FAIL'}] web/{nombre} "
              f"{reg['seg']}s ~{reg.get('tokens_est', 0)} toks "
              f"{('faltan: ' + ','.join(reg.get('faltan', []))[:60]) if reg.get('faltan') else ''}",
              flush=True)


def correr_code(desde: int, hasta: int) -> None:
    from cognia.program_creator.program_creator import crear_hasta_lograr
    ai = _ai_con_backend()
    for i, (nombre, idea, checks) in enumerate(CODE[desde:hasta], start=desde):
        t0 = time.time()
        reg = {"lote": "code", "i": i, "nombre": nombre,
               "ts": datetime.now().isoformat(timespec="seconds")}
        storage = SALIDA / "prog_code" / nombre
        try:
            res = crear_hasta_lograr("programa python: " + idea,
                                     max_rondas=3, verbose=False,
                                     storage_dir=storage,
                                     cognia_instance=ai)
            codigo, ruta = _artefacto(res, storage, "program.py")
            salida = ""
            if ruta:
                # ejecutar el programa guardado para el check REAL del stdout
                import subprocess as _sp
                import sys as _sys
                try:
                    r = _sp.run([_sys.executable, ruta], capture_output=True,
                                text=True, timeout=60, encoding="utf-8",
                                errors="replace")
                    salida = (r.stdout or "") + (r.stderr or "")
                except Exception as e:
                    salida = f"(ejecucion fallo: {e})"
            faltan = [c for c in checks
                      if not re.search(c, salida, re.I | re.M)]
            reg.update(ok=bool(codigo) and not faltan, ruta=ruta,
                       code_chars=len(codigo), out_chars=len(salida),
                       faltan=faltan,
                       tokens_est=_estimar_tokens(codigo, salida) * max(
                           1, getattr(res, "attempted", 1) or 1))
        except Exception as e:
            reg.update(ok=False, error=repr(e)[:300])
        reg["seg"] = round(time.time() - t0)
        _registrar(reg)
        print(f"[{'OK ' if reg.get('ok') else 'FAIL'}] code/{nombre} "
              f"{reg['seg']}s ~{reg.get('tokens_est', 0)} toks "
              f"{('faltan: ' + ','.join(reg.get('faltan', []))[:60]) if reg.get('faltan') else ''}",
              flush=True)


def correr_agent(desde: int, hasta: int) -> None:
    import os
    import shutil
    from cognia.cli import _run_agent_task
    ai = _ai_con_backend()
    base_ws = SALIDA / "ws_agent"
    for i, (nombre, tarea, archivos, checks) in enumerate(
            AGENT[desde:hasta], start=desde):
        t0 = time.time()
        reg = {"lote": "agent", "i": i, "nombre": nombre,
               "ts": datetime.now().isoformat(timespec="seconds")}
        ws = base_ws / nombre
        shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True, exist_ok=True)
        cwd = os.getcwd()
        lineas: list = []
        try:
            os.chdir(ws)
            os.environ["COGNIA_AGENT_WORKSPACE"] = str(ws)
            resp = _run_agent_task(ai, tarea, lambda s: lineas.append(str(s)))
            falt_arch = [a for a in archivos if not (ws / a).exists()]
            contenido = ""
            for p in ws.rglob("*"):
                if p.is_file() and p.stat().st_size < 200_000:
                    try:
                        contenido += p.read_text(encoding="utf-8",
                                                 errors="replace")
                    except Exception:
                        pass
            todo = contenido + "\n" + (resp or "") + "\n" + "\n".join(lineas)
            falt_chk = [c for c in checks if not re.search(c, todo, re.I)]
            reg.update(ok=not falt_arch and not falt_chk,
                       faltan_archivos=falt_arch, faltan_checks=falt_chk,
                       pasos=sum(1 for l in lineas if "ACCION" in l
                                 or "paso" in l.lower()),
                       tokens_est=_estimar_tokens(todo, *lineas))
        except Exception as e:
            reg.update(ok=False, error=repr(e)[:300])
        finally:
            os.chdir(cwd)
        reg["seg"] = round(time.time() - t0)
        _registrar(reg)
        print(f"[{'OK ' if reg.get('ok') else 'FAIL'}] agent/{nombre} "
              f"{reg['seg']}s ~{reg.get('tokens_est', 0)} toks "
              f"faltan={reg.get('faltan_archivos', [])}{reg.get('faltan_checks', [])}",
              flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", required=True, choices=["web", "code", "agent"])
    ap.add_argument("--desde", type=int, default=0)
    ap.add_argument("--hasta", type=int, default=999)
    args = ap.parse_args()
    n = {"web": len(WEB), "code": len(CODE), "agent": len(AGENT)}[args.lote]
    hasta = min(args.hasta, n)
    print(f"== campana lote={args.lote} [{args.desde}:{hasta}] de {n} ==",
          flush=True)
    {"web": correr_web, "code": correr_code,
     "agent": correr_agent}[args.lote](args.desde, hasta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
