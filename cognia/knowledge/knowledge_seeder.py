"""
cognia/knowledge/knowledge_seeder.py
======================================
Static seed injection + dynamic background fetch.

- seed_static(memory)          — called once at startup; inserts ~150 compressed
                                  facts into episodic memory via a background thread.
- fetch_and_cache(topic, cache) — async/thread: DuckDuckGo Instant Answer API,
                                  stores result in KnowledgeCache. Never blocks main thread.
- prefetch_sleep_topics(cache, memory) — called from /dormir; fetches top_topics
                                         not already in cache.

DuckDuckGo endpoint:
  https://api.duckduckgo.com/?q={topic}&format=json&no_html=1&skip_disambig=1
Timeout: 3 s. Extracts AbstractText + RelatedTopics[:3]. Falls back to Answer.
Silently swallows all network errors.
"""

import threading
import time
import json
import urllib.request
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognia.knowledge.knowledge_cache import KnowledgeCache

_DDGO_URL = "https://api.duckduckgo.com/?q={topic}&format=json&no_html=1&skip_disambig=1"
_DDGO_TIMEOUT = 3  # seconds

# ── Static seed data ──────────────────────────────────────────────────────────
# ~150 concise facts organized by domain. Each entry: (topic, fact, domain)
_STATIC_SEEDS = [
    # Python
    ("Python GIL", "El Global Interpreter Lock (GIL) de CPython permite que solo un thread ejecute bytecode Python a la vez, lo que limita el paralelismo en threads pero protege el estado interno del interprete.", "python"),
    ("Python generadores", "Un generador en Python es una funcion que usa 'yield' para producir valores de forma lazy, uno a la vez. Ahorra memoria porque no construye la lista completa en RAM.", "python"),
    ("Python list comprehensions", "Las list comprehensions '[expr for x in iterable if cond]' son la forma idiomatica de crear listas filtradas o transformadas en Python. Son mas rapidas que un bucle for equivalente.", "python"),
    ("Python decoradores", "Un decorador en Python es una funcion de orden superior que envuelve otra funcion para modificar su comportamiento sin cambiar su codigo. Se aplica con la sintaxis @nombre_decorador.", "python"),
    ("Python context managers", "Los context managers en Python (bloques 'with') garantizan que los recursos se liberen correctamente incluso si ocurre una excepcion. Se implementan con __enter__ y __exit__.", "python"),
    ("Python iteradores", "Un iterador implementa __iter__ y __next__. Los generadores son iteradores automaticos. El bucle 'for' llama __next__ hasta StopIteration.", "python"),
    ("Python dataclasses", "Las dataclasses (Python 3.7+) generan automaticamente __init__, __repr__ y __eq__ a partir de anotaciones de tipo. Reducen codigo boilerplate en clases de datos.", "python"),
    ("Python typing", "El modulo typing de Python provee anotaciones de tipo: List, Dict, Optional, Union, Callable. No son obligatorias en runtime pero mejoran IDE support y deteccion de bugs.", "python"),
    ("Python asyncio", "asyncio es el framework de I/O asincrono de Python. 'async def' define corutinas; 'await' suspende la ejecucion hasta que una operacion I/O termine sin bloquear el event loop.", "python"),
    ("Python slots", "__slots__ en una clase Python reemplaza el __dict__ de instancia por un arreglo de punteros fijo, reduciendo uso de memoria ~30-50% en objetos con muchas instancias.", "python"),

    # Web
    ("HTTP metodos", "HTTP define metodos: GET (leer), POST (crear), PUT (reemplazar), PATCH (modificar), DELETE (eliminar). GET y HEAD deben ser idempotentes y no tener efectos secundarios.", "web"),
    ("REST API", "REST (Representational State Transfer) es un estilo arquitectonico que usa HTTP. Los recursos se identifican por URLs, el estado se transfiere en JSON/XML, y es stateless por definicion.", "web"),
    ("WebSockets", "WebSockets proveen comunicacion bidireccional full-duplex sobre una sola conexion TCP. Son ideales para tiempo real: chat, juegos, dashboards. Se inician con un HTTP Upgrade.", "web"),
    ("JSON", "JSON (JavaScript Object Notation) es un formato de intercambio de datos legible por humanos. Soporta: objetos {}, arrays [], strings, numbers, booleans y null.", "web"),
    ("CORS", "CORS (Cross-Origin Resource Sharing) permite que navegadores hagan peticiones a dominios distintos al origen. Requiere headers Access-Control-Allow-Origin en el servidor.", "web"),
    ("HTTP/2", "HTTP/2 introdujo multiplexing (multiples streams en una conexion TCP), compresion de headers HPACK, y server push. Reduce la latencia de carga de paginas web.", "web"),
    ("cookies y sessions", "Las cookies son pares clave-valor almacenados en el navegador y enviados en cada request. Las sesiones del servidor almacenan estado identificado por un session ID en una cookie.", "web"),
    ("TLS SSL", "TLS (Transport Layer Security) cifra las comunicaciones HTTP (HTTPS). Usa certificados X.509 para autenticar el servidor y establece claves de sesion via Diffie-Hellman o ECDHE.", "web"),

    # Matematicas
    ("algebra lineal vectores", "Un vector es un elemento de un espacio vectorial con magnitud y direccion. Las operaciones basicas son suma de vectores y multiplicacion por escalar.", "matematicas"),
    ("algebra lineal matrices", "Una matriz es un arreglo rectangular de numeros. La multiplicacion de matrices AB tiene dimension (m×k) si A es (m×n) y B es (n×k). No es conmutativa en general.", "matematicas"),
    ("algebra lineal autovalores", "Los autovalores (eigenvalues) lambda y autovectores v de una matriz A satisfacen Av = lambda*v. Se usan en PCA, PageRank, y analisis de vibraciones.", "matematicas"),
    ("probabilidad basica", "La probabilidad P(A) de un evento A es un numero en [0,1]. P(A union B) = P(A) + P(B) - P(A interseccion B). Los eventos independientes satisfacen P(A y B) = P(A)*P(B).", "matematicas"),
    ("distribucion normal", "La distribucion normal (gaussiana) tiene media mu y desviacion estandar sigma. La regla 68-95-99.7 dice que el 68% de datos cae en mu +/- sigma.", "matematicas"),
    ("derivada", "La derivada f'(x) es la tasa de cambio instantanea de f en x. Es la pendiente de la tangente. Regla: d/dx(x^n) = n*x^(n-1). Base del gradiente en ML.", "matematicas"),
    ("integral", "La integral de f de a a b es el area bajo la curva. El Teorema Fundamental del Calculo: integral(f', a, b) = f(b) - f(a). Inversa de la derivada.", "matematicas"),
    ("transformada de Fourier", "La Transformada de Fourier descompone una senal en sus frecuencias componentes. La FFT lo hace en O(n log n). Fundamental en procesamiento de senales y audio.", "matematicas"),

    # Fisica basica
    ("leyes de Newton", "1a ley: un objeto en reposo permanece en reposo si no hay fuerza neta. 2a ley: F = m*a. 3a ley: toda accion tiene una reaccion igual y opuesta.", "ciencia"),
    ("termodinamica", "La 1a ley de la termodinamica conserva la energia: dU = Q - W. La 2a ley: la entropia de un sistema aislado nunca disminuye. La temperatura absoluta se mide en Kelvin.", "ciencia"),
    ("electromagnetismo", "La fuerza electrica entre cargas sigue la ley de Coulomb: F = k*q1*q2/r^2. Las ecuaciones de Maxwell unifican electricidad y magnetismo y predicen las ondas electromagneticas.", "ciencia"),
    ("velocidad de la luz", "La velocidad de la luz en el vacio es c = 299,792,458 m/s (exactamente, por definicion del metro). Segun la relatividad especial, ninguna masa puede alcanzarla.", "ciencia"),
    ("mecanica cuantica", "La mecanica cuantica describe el comportamiento de particulas a escala atomica. Principio de incertidumbre de Heisenberg: delta_x * delta_p >= hbar/2. Los estados son superposiciones.", "ciencia"),

    # Quimica basica
    ("tabla periodica", "La tabla periodica organiza los 118 elementos por numero atomico creciente. Los grupos (columnas) comparten propiedades quimicas similares. Los metales alcalinos estan en el grupo 1.", "ciencia"),
    ("enlace quimico", "Enlace covalente: comparticion de electrones entre no-metales. Enlace ionico: transferencia de electrones entre metal y no-metal formando iones. El enlace H es una atraccion dipolo-dipolo.", "ciencia"),
    ("pH", "El pH mide la concentracion de iones H+ en solucion. pH = -log10([H+]). Neutro = 7, acido < 7, basico > 7. El agua pura tiene pH 7 a 25 grados Celsius.", "ciencia"),
    ("reacciones quimicas", "Una reaccion quimica transforma reactivos en productos. La ley de conservacion de la masa: la masa total se conserva. La cinetica quimica estudia las tasas de reaccion.", "ciencia"),

    # Historia tech
    ("origen Linux", "Linux fue creado por Linus Torvalds en 1991, inicialmente como un kernel libre para PC. Esta licenciado bajo GPL v2. El ecosistema GNU/Linux combina el kernel Linux con herramientas GNU.", "historia_tech"),
    ("origen Git", "Git fue creado por Linus Torvalds en 2005 para versionar el kernel Linux tras la ruptura con BitKeeper. Es un sistema de control de versiones distribuido. GitHub fue fundado en 2008.", "historia_tech"),
    ("origen Python", "Python fue creado por Guido van Rossum y publicado en 1991. El nombre viene de Monty Python. Python 2 vs Python 3 fue una ruptura de compatibilidad importante. Python 3.0 salio en 2008.", "historia_tech"),
    ("origen JavaScript", "JavaScript fue creado por Brendan Eich en Netscape en 10 dias en 1995. Estandarizado como ECMAScript. Node.js (2009) llevo JS al servidor. No tiene relacion con Java.", "historia_tech"),
    ("origen internet", "Internet evolucion de ARPANET (1969), financiado por el DoD de EEUU. TCP/IP fue estandarizado en 1983. La World Wide Web fue inventada por Tim Berners-Lee en 1989 en el CERN.", "historia_tech"),
    ("origen Unix", "Unix fue desarrollado en los Laboratorios Bell de AT&T a partir de 1969 por Ken Thompson y Dennis Ritchie. El lenguaje C fue creado para reimplementar Unix. Influencio todos los POSIX.", "historia_tech"),
    ("origen C", "El lenguaje C fue creado por Dennis Ritchie entre 1969 y 1973 en Bell Labs. Evolucion de B y BCPL. Es la base de C++, Java, C# y muchos otros lenguajes modernos.", "historia_tech"),
    ("origen Docker", "Docker fue lanzado en 2013 por dotCloud (luego Docker Inc). Popularizo los contenedores Linux usando cgroups y namespaces del kernel. Kubernetes (2014) gestiona clusters de contenedores.", "historia_tech"),

    # IA / ML
    ("red neuronal artificial", "Una red neuronal artificial es un modelo computacional inspirado en el cerebro. Capas de neuronas (nodos) con pesos ajustables. El entrenamiento minimiza una funcion de perdida via backpropagation.", "ia_ml"),
    ("transformer arquitectura", "El Transformer (Vaswani et al. 2017) usa mecanismos de self-attention para procesar secuencias en paralelo. Reemplazo a las RNN en NLP. Base de BERT, GPT y modelos modernos.", "ia_ml"),
    ("embeddings", "Los embeddings son representaciones vectoriales densas de alta dimension. Word2Vec aprende embeddings de palabras de co-ocurrencia. En LLMs, cada token tiene un embedding en ~1024-4096 dimensiones.", "ia_ml"),
    ("LLM large language model", "Un Large Language Model (LLM) es una red neuronal transformer entrenada en grandes corpus de texto para predecir el siguiente token. GPT-4, Claude y Llama son ejemplos. Emergencia a escala.", "ia_ml"),
    ("fine-tuning", "El fine-tuning ajusta un modelo pre-entrenado a una tarea especifica con datos curados. RLHF (Reinforcement Learning from Human Feedback) alinea LLMs a preferencias humanas.", "ia_ml"),
    ("backpropagation", "Backpropagation calcula gradientes de la funcion de perdida respecto a cada peso usando la regla de la cadena. Permite actualizar pesos eficientemente en redes profundas.", "ia_ml"),
    ("gradient descent", "El descenso de gradiente actualiza parametros w := w - lr * grad(L) iterativamente. SGD usa mini-batches. Adam combina momentum y adaptacion de tasa de aprendizaje por parametro.", "ia_ml"),
    ("overfitting", "El sobreajuste (overfitting) ocurre cuando un modelo memoriza los datos de entrenamiento pero no generaliza. Se mitiga con regularizacion (L1/L2), dropout y mas datos.", "ia_ml"),
    ("convolutional neural network", "Las CNN usan filtros convolucionales que comparten pesos para detectar patrones locales en imagenes. Capas pooling reducen la dimension espacial. AlexNet (2012) inicio el Deep Learning moderno.", "ia_ml"),
    ("attention mechanism", "El mecanismo de atencion calcula Q*K^T/sqrt(d_k) para ponderar valores V segun relevancia. Multi-head attention aplica esto en paralelo con distintas proyecciones.", "ia_ml"),
    ("RAG retrieval augmented generation", "RAG combina busqueda vectorial de documentos relevantes con generacion de texto. El LLM recibe el contexto recuperado en el prompt, reduciendo alucinaciones y permitiendo conocimiento actualizado.", "ia_ml"),
    ("LoRA fine tuning", "LoRA (Low-Rank Adaptation) fine-tunea LLMs insertando matrices de bajo rango en capas de atencion, reduciendo parametros entrenables en 10000x sin perder calidad comparable al full fine-tuning.", "ia_ml"),

    # Base de datos
    ("SQL vs NoSQL", "SQL (relacional) usa tablas con esquema fijo, transacciones ACID y es bueno para datos estructurados. NoSQL (MongoDB, Redis, Cassandra) es flexible, escala horizontalmente, sacrifica consistencia.", "bases_de_datos"),
    ("indices base de datos", "Un indice de base de datos es una estructura auxiliar (B-tree, hash) que acelera las consultas a costa de espacio y escrituras mas lentas. Sin indice, una consulta hace full table scan.", "bases_de_datos"),
    ("ACID propiedades", "ACID: Atomicidad (la transaccion entera se completa o no), Consistencia (pasa de un estado valido a otro), Aislamiento (transacciones concurrentes no interfieren), Durabilidad (persiste tras commit).", "bases_de_datos"),
    ("SQL JOIN tipos", "INNER JOIN retorna filas con coincidencia en ambas tablas. LEFT JOIN incluye todas las filas de la izquierda. FULL OUTER JOIN incluye todas las filas de ambas. CROSS JOIN es el producto cartesiano.", "bases_de_datos"),
    ("normalizacion bases de datos", "La normalizacion organiza tablas para reducir redundancia. 1NF: valores atomicos. 2NF: sin dependencias parciales. 3NF: sin dependencias transitivas. Evita anomalias de insercion/borrado.", "bases_de_datos"),
    ("Redis", "Redis es una base de datos in-memory de clave-valor que soporta strings, hashes, listas, sets y sorted sets. Se usa para cache, colas de mensajes, rate limiting y sesiones.", "bases_de_datos"),
    ("PostgreSQL", "PostgreSQL es un sistema relacional open-source con soporte para JSON, arrays, extensiones (PostGIS, pgvector), MVCC para concurrencia, y cumplimiento completo de ACID.", "bases_de_datos"),
    ("SQLite", "SQLite es una base de datos embebida, sin servidor, almacenada en un solo archivo. Ideal para apps desktop, mobile y prototipado. Es la base de datos mas desplegada del mundo.", "bases_de_datos"),

    # Algoritmos y estructuras de datos
    ("complejidad temporal", "La notacion Big O describe como crece el tiempo de un algoritmo con el tamano de entrada n. O(1) constante, O(log n) logaritmico, O(n) lineal, O(n log n) quasi-lineal, O(n^2) cuadratico.", "algoritmos"),
    ("busqueda binaria", "La busqueda binaria en un arreglo ordenado encuentra un elemento en O(log n) comparaciones. En cada paso descarta la mitad del espacio de busqueda. Requiere arreglo ordenado.", "algoritmos"),
    ("quicksort", "Quicksort elige un pivot, particiona el arreglo, y recursivamente ordena las mitades. Caso promedio O(n log n). Caso peor O(n^2) si el pivot es siempre el mayor o menor.", "algoritmos"),
    ("merge sort", "Mergesort divide el arreglo a la mitad recursivamente y fusiona las mitades ordenadas. Siempre O(n log n), estable, pero requiere O(n) memoria adicional.", "algoritmos"),
    ("hash table", "Una tabla hash mapea claves a valores usando una funcion hash. Las colisiones se manejan con encadenamiento o sondeo abierto. Busqueda e insercion O(1) promedio.", "algoritmos"),
    ("grafo BFS DFS", "BFS (Breadth-First Search) explora capa a capa usando una cola, encuentra caminos mas cortos en grafos no ponderados. DFS usa una pila (o recursion) y es base de deteccion de ciclos.", "algoritmos"),
    ("arboles binarios", "Un arbol binario de busqueda tiene la propiedad: nodo izquierdo < padre < nodo derecho. Busqueda, insercion y eliminacion O(log n) si esta balanceado. O(n) en el peor caso.", "algoritmos"),
    ("programacion dinamica", "La programacion dinamica resuelve subproblemas solapados una sola vez y guarda resultados (memoizacion o tabulacion). Fibonacci DP: O(n) vs O(2^n) recursivo.", "algoritmos"),

    # Sistemas operativos
    ("proceso vs hilo", "Un proceso es una instancia de programa con su propio espacio de memoria. Un hilo (thread) comparte el espacio de memoria del proceso. Los hilos son mas ligeros pero requieren sincronizacion.", "sistemas"),
    ("sistema de archivos", "Un sistema de archivos organiza datos en discos. FAT32 tiene limite de 4GB por archivo. NTFS soporta permisos y journaling. ext4 es el estandar en Linux. ZFS tiene checksums de datos.", "sistemas"),
    ("memoria virtual", "La memoria virtual da a cada proceso la ilusion de memoria continua. El SO usa paginacion: mapea paginas virtuales a frames fisicos. El TLB cachea estas traducciones.", "sistemas"),
    ("semaforos y mutex", "Un mutex (mutual exclusion) permite que solo un hilo acceda a un recurso critico. Un semaforo es un contador que puede ser N>1. Ambos evitan condiciones de carrera.", "sistemas"),
    ("scheduling CPU", "El scheduler del SO decide que proceso corre en la CPU. Round Robin da rodajas de tiempo iguales. CFS (Linux) usa un arbol rojo-negro para distribucion justa de CPU.", "sistemas"),

    # Redes y seguridad
    ("modelo OSI", "El modelo OSI tiene 7 capas: Fisica, Enlace de datos, Red (IP), Transporte (TCP/UDP), Sesion, Presentacion, Aplicacion (HTTP). TCP/IP en practica colapsa a 4 capas.", "redes"),
    ("TCP vs UDP", "TCP garantiza entrega ordenada y sin perdidas via ACKs y retransmision. UDP es mas rapido, sin garantias, ideal para video streaming, juegos y DNS donde la latencia importa mas que la fiabilidad.", "redes"),
    ("DNS", "DNS (Domain Name System) traduce nombres de dominio a IPs. Es jerarquico: root servers -> TLD servers -> authoritative servers. El resolver local cachea respuestas segun TTL.", "redes"),
    ("cifrado asimetrico", "La criptografia asimetrica usa par de claves publica/privada. RSA y ECDSA se usan para firmas digitales y handshakes TLS. AES es cifrado simetrico rapido para datos en bulk.", "redes"),
    ("firewall", "Un firewall filtra trafico de red por reglas (IP, puerto, protocolo). Stateful firewalls rastrean conexiones TCP. WAF (Web Application Firewall) inspecciona trafico HTTP.", "redes"),

    # Arquitectura de software
    ("microservicios", "La arquitectura de microservicios divide una aplicacion en servicios independientes que se comunican via HTTP/gRPC. Cada servicio tiene su propia BD. Escalado independiente pero mayor complejidad operacional.", "arquitectura"),
    ("event driven architecture", "En arquitectura orientada a eventos los componentes se comunican publicando y suscribiendose a eventos (Kafka, RabbitMQ). Desacople temporal: el publicador no sabe quienes consumen.", "arquitectura"),
    ("SOLID principios", "SOLID: Single responsibility, Open/closed, Liskov substitution, Interface segregation, Dependency inversion. Principios de diseno orientado a objetos para codigo mantenible.", "arquitectura"),
    ("CQRS", "CQRS (Command Query Responsibility Segregation) separa las operaciones de lectura (queries) de las de escritura (commands) en modelos distintos. Permite optimizar cada uno por separado.", "arquitectura"),
    ("cache estrategias", "Cache-aside: la app lee del cache; si falla, lee de BD y llena el cache. Write-through: escribe en BD y cache juntos. Write-back: escribe en cache y sincroniza con BD async.", "arquitectura"),

    # DevOps y cloud
    ("Docker contenedores", "Docker usa cgroups y namespaces de Linux para aislar procesos. Una imagen Docker es inmutable y contiene todo lo necesario para correr la app. Los contenedores son instancias de imagenes.", "devops"),
    ("Kubernetes", "Kubernetes (K8s) orquesta contenedores en un cluster. Un Pod es la unidad minima (uno o mas contenedores). Deployments, Services e Ingress controlan el ciclo de vida y red.", "devops"),
    ("CI CD", "CI (Continuous Integration) ejecuta tests automaticamente en cada commit. CD (Continuous Delivery/Deployment) despliega automaticamente a produccion. GitHub Actions, GitLab CI y Jenkins son herramientas comunes.", "devops"),
    ("Infrastructure as Code", "IaC define infraestructura en archivos de configuracion (Terraform, Pulumi). Permite versionar la infraestructura, hacer rollback y replicar entornos de forma reproducible.", "devops"),

    # Matematica para ML
    ("funcion de perdida", "La funcion de perdida (loss) mide el error del modelo. Cross-entropy para clasificacion: L = -sum(y_i * log(p_i)). MSE para regresion: L = mean((y - y_hat)^2).", "ia_ml"),
    ("regularizacion L1 L2", "L1 (Lasso) suma el valor absoluto de pesos: penaliza y produce sparsity. L2 (Ridge) suma los cuadrados de pesos: reduce magnitudes sin anularlos. Ambas previenen sobreajuste.", "ia_ml"),
    ("batch normalization", "Batch Normalization normaliza las activaciones de una capa a media 0 y varianza 1 por mini-batch, luego reescala con parametros gamma y beta. Acelera entrenamiento y reduce sensibilidad al LR.", "ia_ml"),
    ("softmax", "Softmax convierte logits en probabilidades: softmax(z_i) = exp(z_i) / sum(exp(z_j)). Siempre positivos y suman 1. Usada en la capa de salida de clasificacion multi-clase.", "ia_ml"),
    ("tokenizacion", "Los LLMs procesan texto como tokens (subpalabras). BPE (Byte Pair Encoding) y WordPiece son los algoritmos mas comunes. GPT-4 tiene vocab de ~100k tokens; Qwen2.5 de 151936.", "ia_ml"),

    # Ciencias de la computacion misc
    ("compilador vs interprete", "Un compilador traduce codigo fuente a codigo maquina antes de ejecutar (C, Rust). Un interprete ejecuta el codigo linea a linea (Python, Ruby). JIT (Java, V8) compila en tiempo de ejecucion.", "cs"),
    ("recursion", "La recursion es una funcion que se llama a si misma con un subproblema mas pequeno. Requiere un caso base que detenga la recursion. El stack puede desbordarse con recursion profunda.", "cs"),
    ("concurrencia vs paralelismo", "Concurrencia: multiples tareas progresando al mismo tiempo (pueden turnarse en un solo nucleo). Paralelismo: multiples tareas ejecutandose simultaneamente en multiples nucleos.", "cs"),
    ("garbage collection", "El garbage collector (GC) libera automaticamente memoria que ya no es accesible. GC de marca y barrido, conteo de referencias (Python), generacional (JVM, V8). Trade-off: pausas del GC.", "cs"),
    ("expresiones regulares", "Las expresiones regulares (regex) son patrones para buscar y manipular texto. \\d+ digitos, \\w+ alfanumericos, .* cualquier cosa, ^ inicio, $ fin. Implementadas con automatas finitos.", "cs"),

    # Estadistica para datos
    ("media mediana moda", "Media: suma/n. Mediana: valor central (robusta a outliers). Moda: valor mas frecuente. La media es sensible a valores extremos; la mediana no.", "estadistica"),
    ("correlacion", "La correlacion de Pearson r mide relacion lineal entre dos variables, rango [-1, 1]. r=1 correlacion positiva perfecta. r=0 no hay correlacion lineal. Correlacion no implica causalidad.", "estadistica"),
    ("p-valor", "El p-valor es la probabilidad de observar los datos (o algo mas extremo) bajo la hipotesis nula. p < 0.05 se considera estadisticamente significativo por convencion, pero es una threshold arbitraria.", "estadistica"),
    ("varianza desviacion estandar", "La varianza mide la dispersion: var = mean((x - mean(x))^2). La desviacion estandar (std) es su raiz cuadrada, en las mismas unidades que los datos.", "estadistica"),
]


class KnowledgeSeeder:
    """
    Inyecta conocimiento bruto en Cognia de dos formas:
    1. seed_static: escribe ~150 hechos compilados directamente en memoria episodica.
    2. fetch_and_cache: obtiene hechos frescos de DuckDuckGo y los guarda en KnowledgeCache.
    3. prefetch_sleep_topics: llama fetch_and_cache para los topics mas populares durante /dormir.

    Todos los metodos que tocan la red corren en hilos daemon para nunca bloquear el caller.
    """

    # Cuantos hechos estaticos inyectar por llamada a seed_static
    SEED_BATCH_SLEEP = 0.001  # s entre stores para no saturar WAL

    @staticmethod
    def seed_static(memory) -> None:
        """
        Inyecta los hechos estaticos en memoria episodica.
        Llamado en un background thread desde Cognia.__init__.
        'memory' debe tener un metodo store(observation, label, vector, ...).
        """
        try:
            from cognia.vectors import text_to_vector
        except ImportError:
            try:
                from vectors import text_to_vector
            except ImportError:
                text_to_vector = None

        seeded = 0
        for topic, fact, domain in _STATIC_SEEDS:
            try:
                observation = f"{topic}: {fact}"
                label = f"conocimiento_{domain}"
                vec = []
                if text_to_vector is not None:
                    try:
                        vec = text_to_vector(observation) or []
                    except Exception:
                        vec = []
                memory.store(
                    observation=observation,
                    label=label,
                    vector=vec,
                    confidence=0.85,
                    importance=0.6,
                )
                seeded += 1
                if KnowledgeSeeder.SEED_BATCH_SLEEP > 0:
                    time.sleep(KnowledgeSeeder.SEED_BATCH_SLEEP)
            except Exception:
                pass  # nunca crashear

    @staticmethod
    def fetch_and_cache(topic: str, cache: "KnowledgeCache") -> None:
        """
        Llama la DuckDuckGo Instant Answer API en un hilo daemon y guarda el resultado.
        Nunca bloquea el hilo principal. Silencia todos los errores de red.
        """
        def _fetch():
            try:
                url = _DDGO_URL.format(topic=urllib.parse.quote_plus(topic))
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "CogniaKnowledgeSeeder/1.0"},
                )
                with urllib.request.urlopen(req, timeout=_DDGO_TIMEOUT) as resp:
                    raw = resp.read(65536)
                data = json.loads(raw)

                abstract = data.get("AbstractText", "").strip()
                if not abstract:
                    abstract = data.get("Answer", "").strip()

                related = []
                for t in data.get("RelatedTopics", [])[:3]:
                    if isinstance(t, dict):
                        txt = t.get("Text", "").strip()
                        if txt:
                            related.append(txt)

                parts = [p for p in [abstract] + related if p]
                if not parts:
                    return

                facts = " | ".join(parts[:4])
                cache.store(topic, facts)
            except Exception:
                pass  # timeout, sin red, JSON invalido — silencio total

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

    @staticmethod
    def prefetch_sleep_topics(cache: "KnowledgeCache", memory) -> None:
        """
        Llamado desde /dormir. Obtiene top_topics del cache y fetcha los que no esten
        ya frescos. Se ejecuta en hilos daemon — no bloquea el ciclo de sueno.
        """
        if cache is None:
            return
        try:
            tops = cache.top_topics(10)
        except Exception:
            return

        for topic in tops:
            try:
                existing = cache.get(topic)
                if not existing:
                    KnowledgeSeeder.fetch_and_cache(topic, cache)
                    time.sleep(0.05)  # pequeño gap para no saturar DDG
            except Exception:
                pass
