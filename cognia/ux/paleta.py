"""
cognia/ux/paleta.py -- LA fuente de verdad del color de Cognia.

QUE: datos planos (dicts de strings) con la identidad visual del producto: la
rampa del VERDE, los colores semanticos en hex, las superficies, el menu de
autocompletado del prompt y las tres variantes del tema del CLI. Sin imports,
sin rich, sin textual: este modulo se puede importar desde cualquier capa sin
arrastrar dependencias ni ciclos.

POR QUE: hasta 2026-08-17 el color de Cognia vivia en tres sitios que no se
hablaban -- los tres rich.Theme hardcodeados de cli.py, los hex a mano del
marco del prompt y del gradiente del banner (tambien en cli.py) y el COLORS
violeta de cognia/tui/theme.py. Al abrir la TUI parecia OTRA aplicacion. La
decision del dueno es que manda el VERDE del REPL y que la TUI lo hereda; para
que eso sea verificable y no se vuelva a desincronizar, el verde tiene que
estar escrito UNA sola vez.

DOS VOCABULARIOS, A PROPOSITO (no es inconsistencia):

  1. HEX (VERDE, SEMANTICO, SUPERFICIE, MENU_PROMPT). Para donde el tono exacto
     importa y el canal lo soporta: el marco del prompt (prompt_toolkit sobre
     terminal truecolor/256), el gradiente del banner y la TUI de Textual, que
     solo entiende hex. Es lo que hace que rich y Textual puedan compartir la
     MISMA paleta.

  2. NOMBRES DE COLOR DE TERMINAL ('white', 'bright_cyan'...) en las tres
     variantes del tema del CLI (VARIANTES). Un nombre de los 16 basicos lo
     resuelve el emulador con la paleta del usuario, y eso es lo que hace que
     el tema respete la configuracion de accesibilidad de quien mira. Clavar
     hex ahi seria una regresion silenciosa en toda terminal que no sea la del
     dueno.
     EXCEPCION MEDIDA (2026-08-17): el VERDE de las TRES variantes va en hex.
     Los nombres 'green'/'bright_green' son verde PASTO y la identidad de
     Cognia es LIMA; conviviendo en la misma pantalla que el marco (hex) se
     veian como dos productos. Ver el comentario largo sobre RAMPA.

Convencion: nombres y comentarios en ASCII; los valores son hex o nombres de
color de rich.
"""

# ---------------------------------------------------------------------------
# 0. Contra que FONDO se lee cada variante
# ---------------------------------------------------------------------------
# El CLI no pinta el fondo (lo hereda de la terminal), pero cada variante se
# DISENA contra uno: 'oscuro' y 'alto_contraste' contra el fondo de la TUI
# (#0d1117, el mismo de SUPERFICIE), 'claro' contra el blanco roto de una
# terminal clara. Vivia duplicado en scripts/contraste_tema.py; sin esto no hay
# forma de que un test compruebe el piso de contraste POR VARIANTE.
FONDO_VARIANTE = {
    "oscuro":         "#0d1117",
    "claro":          "#fbfbfa",
    "alto_contraste": "#0d1117",
}

# ---------------------------------------------------------------------------
# 1. La rampa del VERDE -- la identidad, POR VARIANTE
# ---------------------------------------------------------------------------
# Siete escalones que van del extremo mas TENUE (el arranque del degradado del
# banner) al mas PRESENTE (lo que el dueno esta escribiendo). Todo lo que en
# Cognia se ve verde sale de aca.
#
# POR QUE HAY UNA RAMPA POR VARIANTE (2026-08-17, bloqueante del juicio visual).
# Hasta hoy la rampa era UNA sola, en hex fijos, y las piezas de identidad que
# la consumen -- el marco del prompt, el 'cognia>', el texto que se escribe, la
# barra de estado y el gradiente del banner -- no pasan por el tema de rich: son
# hex que prompt_toolkit y el banner escriben directo. Resultado medido sobre
# #fbfbfa con '/tema claro' puesto:
#
#     lo que el dueno ESCRIBE  #a6ff4d   1,19:1   (invisible)
#     'cognia>'                #7ee62a   1,53:1
#     marco del prompt         #4fd010   1,96:1
#     barra de estado          #8fbf5f   2,07:1
#     logotipo COGNIA          #00ff41   1,32:1   (la marca, lo menos visible)
#
# O sea: '/tema claro' no era un tema alternativo, era la misma pantalla con el
# prompt borrado. Y la decision 18 lo habia EMPEORADO sin querer: mover el
# arranque del degradado de #003300 a #00701c gano 1,33 -> 3,00 sobre negro
# pero perdio 13,76 -> 6,08 sobre blanco, que era el unico extremo de la rampa
# que en claro se veia.
#
# La rampa CLARA no es la lima oscurecida a ojo: es el mismo recorrido con los
# pesos ESPEJADOS. En fondo oscuro "mas presente" = mas claro; en fondo claro
# "mas presente" = mas oscuro. Se conserva la FAMILIA de tono (lima 100 grados
# para las piezas de escritura, verde 120-138 para el exito y los extremos del
# banner) y se sube la saturacion al maximo, que es lo que impide que un verde
# oscuro se lea como gris (o como mostaza: ver el comentario de 'claro').
RAMPA = {
    # -- oscuro: la rampa historica, sin tocar (es la que ve el dueno) --------
    # 'profundo' es el ARRANQUE del degradado del banner. Hasta 2026-08-17 era
    # #003300: 1,33:1 sobre #0d1117, o sea INVISIBLE -- las primeras filas del
    # gato Braille no se veian y el degradado empezaba en la nada. Decision 18
    # del dueno: que arranque en un verde oscuro QUE SE VEA (~3:1) sin perder
    # la rampa. #00701c es el propio 'matrix' bajado de luminancia (112/255 y
    # 28/65: el mismo tono, el 44% de la luz) y mide 3,00:1 exacto.
    "oscuro": {
        "profundo": "#00701c",   # arranque del gradiente del banner (3,00:1)
        "solido":   "#3fb950",   # verde de exito (semantico 'ok')   (7,45:1)
        "marco":    "#4fd010",   # reglas que encuadran la escritura (9,34:1)
        "prompt":   "#7ee62a",   # 'cognia' del prompt / acento TUI (11,93:1)
        "texto":    "#a6ff4d",   # lo que el dueno esta escribiendo (15,35:1)
        "estado":   "#8fbf5f",   # barra de estado bajo el marco     (8,82:1)
        "matrix":   "#00ff41",   # cierre del gradiente del banner  (13,86:1)
    },
    # -- claro: el ESPEJO sobre #fbfbfa --------------------------------------
    # Contrastes medidos con scripts/contraste_tema.py. 'marco' es la unica
    # pieza por debajo de 4,5 a proposito: es una REGLA, no texto, y WCAG pide
    # 3:1 para elementos graficos (1.4.11). Todo lo que se LEE -- prompt, texto
    # escrito, barra de estado -- pasa AA con margen.
    # OJO con los dos extremos del banner: en claro el degradado va de CLARO a
    # OSCURO, asi que 'profundo' (el arranque) es aca el tono mas TENUE (3,02,
    # el espejo exacto del 3,00 de la decision 18) y 'matrix' (el cierre) el
    # mas oscuro. La palabra 'profundo' conserva el ROL (arranque), no el brillo.
    # Los cuatro escalones de ESCRITURA (marco, estado, prompt, texto) son el
    # MISMO tono -- el 100 de la lima, el de oscuro['marco'] -- a cuatro
    # luminancias. Se probo con la familia repartida entre 92 y 100 como en la
    # rampa oscura y sobre blanco no funciona: mirada la captura, la barra de
    # estado en el tono 92 se lee MOSTAZA, no verde. Cuanto mas oscuro el
    # verde, mas cuenta el rojo residual, asi que en claro los cuatro van a
    # saturacion 1,00 (canal azul en cero) y a un solo tono.
    "claro": {
        "profundo": "#19a844",   # arranque del banner: el extremo CLARO (3,02:1)
        "marco":    "#2c8400",   # reglas del marco (grafico, piso 3:1)  (4,60:1)
        "estado":   "#267300",   # barra de estado bajo el marco         (5,74:1)
        "solido":   "#006a00",   # verde de exito                        (6,62:1)
        "prompt":   "#1e5900",   # 'cognia' del prompt                   (8,16:1)
        "texto":    "#174400",   # lo que el dueno esta escribiendo     (10,88:1)
        "matrix":   "#003711",   # cierre del banner: el extremo OSCURO (13,05:1)
    },
    # -- alto_contraste: la rampa oscura corrida UN ESCALON hacia arriba -----
    # Los cuatro escalones que ya existian se REUSAN tal cual (estado toma el
    # 'marco' de oscuro, marco toma el 'prompt', prompt toma el 'texto'): un
    # hex nuevo que se diferencie del vecino en dos unidades es exactamente el
    # bug del punto 10 (dos limas que difieren en un byte). Solo hay tres tonos
    # NUEVOS, y estan lejos de todos los demas.
    "alto_contraste": {
        "profundo": "#009024",   # arranque del banner, mas alto que en oscuro (4,52:1)
        "estado":   "#4fd010",   # = oscuro['marco']                     (9,34:1)
        "solido":   "#39e24f",   # verde de exito, subido               (10,96:1)
        "marco":    "#7ee62a",   # = oscuro['prompt']                   (11,93:1)
        "matrix":   "#00ff41",   # = oscuro['matrix']                   (13,86:1)
        "prompt":   "#a6ff4d",   # = oscuro['texto']                    (15,35:1)
        "texto":    "#beff73",   # lo que se escribe, el tope de la rampa (15,99:1)
    },
}

# La rampa POR DEFECTO (la del tema oscuro). Se conserva el nombre VERDE porque
# es lo que importan la TUI y media docena de modulos; quien necesite el verde
# de OTRA variante pide rampa(variante).
VERDE = RAMPA["oscuro"]

# Gradiente del banner: (desde, hasta). Se interpola por linea no vacia.
# El de la variante activa sale de gradiente_banner(pasos, variante).
BANNER_GRADIENTE = (VERDE["profundo"], VERDE["matrix"])

# El acento de identidad en hex, para quien necesite UN verde y no la rampa
# (la TUI, un widget nuevo, un export a SVG/PNG).
#
# PUNTO 10 del juicio visual (dos limas, #7de62a y #7ee62a): la paleta declara
# UN solo lima -- este. El segundo lo FABRICA Textual: sus variables de tema
# salen de color.lighten(0), que es un viaje de ida y vuelta por Lab y termina
# en `Color(int(r * 255), ...)`, o sea TRUNCANDO. #7ee62a vuelve como #7de62a
# (y #f85149 como #f75149: no es cosa del verde). Medido en textual 8.2.8.
# Se deja como esta a proposito y con el numero puesto: el punto fijo mas
# cercano de ese truncamiento esta a deltaE 8,3 / 30 unidades RGB de la lima de
# Cognia (hue 93 -> 104), o sea que "arreglarlo" cambiaria la marca de verdad
# para tapar una diferencia de 1/255 que nadie ve. Lo que NO se hace es comparar
# renders con '==': para eso esta mismo_color() aca abajo.
ACENTO_HEX = VERDE["prompt"]

# Tolerancia (unidades por canal) del viaje de ida y vuelta de Textual.
DERIVA_TEXTUAL = 1


def mismo_color(uno: str, otro: str, tolerancia: int = DERIVA_TEXTUAL) -> bool:
    """True si dos hex son el MISMO color salvo el redondeo del renderer.

    Un assert `render == "#7ee62a"` mide el truncamiento de Textual, no la
    paleta de Cognia (ver el comentario de ACENTO_HEX). Esta es la comparacion
    que hay que usar contra cualquier color leido de un render."""
    a = [int(uno.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(otro.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return all(abs(x - y) <= tolerancia for x, y in zip(a, b))

# ---------------------------------------------------------------------------
# 2. Semanticos en hex (compartidos rich <-> Textual)
# ---------------------------------------------------------------------------
SEMANTICO = {
    "ok":      VERDE["solido"],   # exito / saludable
    "info":    "#58a6ff",         # informativo
    "aviso":   "#d29922",         # advertencia
    "error":   "#f85149",         # error / critico
    "texto":   "#e6edf3",         # texto primario
    "detalle": "#8b949e",         # texto secundario / placeholder
}

# Superficies (fondos y bordes). Hoy solo las consume la TUI; el CLI hereda el
# fondo de la terminal a proposito.
SUPERFICIE = {
    "fondo":     "#0d1117",
    "panel":     "#161b22",
    "panel_alt": "#1c2330",
    "borde":     "#30363d",
}

# ---------------------------------------------------------------------------
# 3. Menu de autocompletado y scrollbar del prompt (prompt_toolkit)
# ---------------------------------------------------------------------------
# Azul oscuro, NO verde: el menu flota sobre el marco verde y con el mismo tono
# se perderia el borde entre "lo que escribo" y "lo que me ofrece".
MENU_PROMPT = {
    "fondo":            "#1c1c2e",
    "texto":            "#c8c8d8",
    "fondo_activo":     "#004466",
    "texto_activo":     "#ffffff",
    "meta":             "#667788",
    "meta_activo":      "#aaccdd",
    "scrollbar_fondo":  "#1c1c2e",
    "scrollbar_boton":  "#334455",
}

# ---------------------------------------------------------------------------
# 3 bis. Las BANDAS del diff, por variante
# ---------------------------------------------------------------------------
# Punto 3 del juicio visual: el diff con fondo no obedecia a /tema. Los dos
# fondos vivian calculados dentro de cognia/console/diff_render.py como una
# mezcla alfa sobre SUPERFICIE['fondo'], asi que en una terminal blanca el
# bloque quedaba negro -- una isla, 13,23:1 y 14,92:1 contra #fbfbfa, el
# elemento de mas peso de la pantalla, con lineas de contexto en negro sobre
# blanco justo encima. Aca estan por variante; diff_render las lee del tema.
#
# CRITERIO (medido, no elegido a ojo). Para las dos bandas de LINEA:
#   * el texto de encima >= 4,5:1 sobre la banda, y
#   * la banda a MENOS de 2:1 del fondo del tema -- una banda que se despega
#     mas que eso deja de ser un realce y vuelve a ser una isla.
# Las dos bandas '_intra' son el realce del span cambiado DENTRO de la linea:
# ahi el 2:1 no aplica a proposito (tienen que despegarse de su propia linea),
# lo que se sostiene es el 4,5:1 del texto.
#
# AVISO AL CONSUMIDOR: el texto que va ENCIMA de la banda tiene que ser el de
# la variante, no SEMANTICO['texto']. Hoy diff_render pinta el contenido en
# SEMANTICO['texto'] (#e6edf3) porque solo existia la banda oscura; sobre la
# banda clara ese mismo gris da 1,05:1 -- ilegible. El texto correcto es el que
# resuelve el token 'respuesta' del tema: #cccccc en oscuro (8,53 y 9,62 sobre
# sus bandas), #22221f en claro (12,84 y 12,61) y #f2f2f2 en alto_contraste
# (11,78 y 13,80). Los numeros de abajo estan medidos con SEMANTICO['texto'] en
# los dos temas oscuros y con el foreground de una terminal clara en 'claro'.
DIFF_FONDO = {
    "oscuro": {
        # Los cuatro que diff_render ya calcula (ok al 20%/45%, error al
        # 18%/45% sobre #0d1117): mismos hex, ahora en el tema.
        "mas":         "#173322",  # banda/fondo 1,38  texto 11,59  marca 5,39
        "menos":       "#371d20",  # banda/fondo 1,22  texto 13,08  marca 4,61
        "mas_intra":   "#245d31",  # texto  6,62
        "menos_intra": "#772e2e",  # texto  8,03
    },
    "claro": {
        # Mezcla del verde/rojo de la variante sobre #fbfbfa al 12% (linea) y
        # al 30% (intra). Al 12% la marca '+' verde todavia mide 5,50 sobre su
        # propia banda y la '-' 4,83; al 16% la '+' ya cae a 4,34.
        "mas":         "#ddeadc",  # banda/fondo 1,20  texto 12,82  marca 5,51
        "menos":       "#f4e0e1",  # banda/fondo 1,22  texto 12,61  marca 4,83
        "mas_intra":   "#b0d0af",  # texto  9,48
        "menos_intra": "#e9b8bb",  # texto  9,14
    },
    "alto_contraste": {
        # La banda '+' sube (ok al 22%: 1,43 contra el fondo). La '-' NO:
        # medido, con el rojo al 20% la marca '-' (#f85149) cae a 4,48 y con
        # 0,18 queda en 4,61 -- el mismo tope que ya documenta diff_render. En
        # alto_contraste lo que sube es el TEXTO de encima (13,80 y 11,78,
        # contra 13,08 y 11,59 en oscuro), que es de lo que trata la variante.
        "mas":         "#183624",  # banda/fondo 1,43  texto 11,78  marca 8,32
        "menos":       "#371d20",  # banda/fondo 1,22  texto 13,80  marca 4,61
        "mas_intra":   "#266534",  # texto  6,27
        "menos_intra": "#772e2e",  # texto  8,47
    },
}

# ---------------------------------------------------------------------------
# 4. El tema del CLI: roles semanticos -> tokens de rich
# ---------------------------------------------------------------------------
# Los tokens son los que el codigo escribe como markup ([ok_cl]...[/ok_cl]) y
# los que el renderer pasa como style=. El MAPA token->rol se declara UNA vez y
# vale para las tres variantes; cada variante solo dice de que color es cada
# ROL. Asi dos tokens que comparten rol no pueden divergir por descuido: que
# 'spinner' y 'pensar' sean el mismo verde (fix 2026-08-10) queda garantizado
# por construccion, no por acordarse de tocar tres diccionarios.
TOKENS_CLI = {
    "ok":         "exito_fuerte",   # confirmaciones destacadas
    "ok_cl":      "exito",          # confirmaciones al hilo del texto
    "mod":        "acento_fuerte",  # nombre del modelo / titulo
    "detail":     "detalle",        # prosa secundaria
    "info_dim":   "tenue",          # metadatos, razonamiento tenue
    "footer":     "pie",            # la linea final del turno
    "spinner":    "actividad",      # el spinner de las tools
    "pensar":     "actividad",      # 'pensando...' (mismo verde que el spinner)
    "tool_verbo": "acento",         # 'Leyendo', 'Escribiendo'
    "tool_obj":   "objeto",         # el archivo / argumento de la tool
    "escrito":    "actividad",      # las lineas '+' del preview
    "borrado":    "error",          # las lineas '-' del preview
    "intencion":  "intencion",      # 'Voy a leer el archivo' (italica)
    "warn_cl":    "aviso",
    "err_cl":     "error",
    # 2026-08-17. Los tres tokens que cierran el juicio visual:
    "marca":       "identidad",         # banner: borde y atajos del arranque
    "marca_fuerte": "identidad_fuerte", # banner: titulo COGNIA, encabezados
    "marca_dim":   "identidad_tenue",   # banner: version y subtitulo
    "respuesta":  "respuesta",        # LO QUE CONTESTA EL MODELO (decision 17)
    # 2026-08-17, SEGUNDA PASADA. cli.py tenia 104 colores escritos a mano que
    # esta tabla no veia -- 87 'cyan', 7 'magenta', 7 'yellow', 2 'bright_cyan',
    # 1 'dim cyan' y varios '[dim]' pelados. Medido: el cuerpo de ~30 comandos
    # slash iba a 2,96:1 con '/tema claro' (860 caracteres seguidos) y el tema
    # por DEFECTO tenia dos cosas peores que el rojo 3,12 que origino todo el
    # trabajo (magenta 2,36 y 'dim cyan' 2,75).
    #
    # No eran todos la misma cosa: clasificados por SIGNIFICADO salen CUATRO
    # roles distintos, y tres necesitaban token propio.
    #   * el CUERPO de la salida de un comando   -> 'listado'  (nuevo)
    #   * el encabezado de un panel/seccion      -> 'titulo'   (nuevo)
    #   * el borde de un panel de chrome         -> 'borde'    (nuevo)
    #   * lo que CONTESTA el modelo (/narrativa, /explicar...) -> el acento
    #     que ya existia; ahi no hacia falta token nuevo, hacia falta dejar de
    #     escribir "magenta" y usar el que el dueno configura con /color.
    "listado":    "cuerpo",           # el CUERPO de la salida de un comando
    "titulo":     "identidad_fuerte", # encabezado de panel / de seccion
    "borde":      "identidad",        # el borde de un panel de chrome
}

# Cada variante: rol -> estilo de rich (color de terminal + modificadores).
# Los tres perfiles son DISTINGUIBLES a proposito:
#   oscuro          -- colores vivos sobre fondo oscuro (default)
#   claro           -- paleta sobria para terminal con fondo claro
#   alto_contraste  -- blanco brillante, maxima legibilidad
#
# UN SOLO IDIOMA DE VERDE (2026-08-17). El juicio visual encontro SIETE verdes
# en pantalla y dos que no salian de esta paleta: el 'green' de rich (#13a10e)
# y el 'bright_green' (#16c60c) de Campbell son verde PASTO (117-118 grados) y
# la rampa de Cognia es LIMA (90-100 grados). El 'cognia>' de respaldo quedaba
# DOS LINEAS encima del 'cognia➤' del marco y se veian distintos. Un nombre
# ANSI no se puede alinear con un hex, asi que el verde de las TRES variantes
# es la rampa (hex) y el pasto desaparece del CLI.
#
# SEGUNDA PASADA (bloqueante del juicio visual): 'claro' tampoco es la
# excepcion. Antes usaba 'dark_green', un nombre del cubo de 256 que NO lo
# resuelve el emulador -- es el hex fijo #005f00 -- asi que la "adaptabilidad"
# que justificaba la excepcion no existia, y ese verde no era ninguno de los
# que el marco del prompt pintaba dos lineas mas abajo. Ahora los seis roles
# verdes de cada variante salen de RAMPA[variante]: el marco, el prompt, la
# barra de estado, el spinner y el banner son EL MISMO verde, en las tres.
_OSC = RAMPA["oscuro"]
_CLA = RAMPA["claro"]
_ALT = RAMPA["alto_contraste"]

VARIANTES = {
    "oscuro": {
        # Verdes: la rampa, no el pasto de la terminal (ver el bloque de
        # arriba). Contrastes sobre #0d1117: 11,93 / 7,45 / 9,34.
        "exito_fuerte":  "bold " + _OSC["prompt"],
        "exito":         _OSC["solido"],
        "actividad":     _OSC["marco"],
        "identidad":       _OSC["marco"],
        "identidad_fuerte": "bold " + _OSC["prompt"],
        "identidad_tenue":  _OSC["estado"],
        "acento":        "cyan",
        "acento_fuerte": "bold cyan",
        "objeto":        "bold bright_white",
        "detalle":       "dim white",
        # Punto 8: 'dim grey62' daba 3,15:1 e 'dim grey50' 2,38:1 -- las dos
        # ultimas cosas del tema por defecto por debajo del rojo que motivo
        # todo el trabajo, y encima el 'dim' de rich las hunde otro 40% contra
        # el fondo. Ahora son hex, con la MISMA jerarquia (el pie por debajo de
        # los metadatos) y las dos sobre AA: 6,15 y 4,86. Siguen siendo lo mas
        # apagado de la pantalla -- el texto primario mide 13 y las tools 16,9.
        "tenue":         SEMANTICO["detalle"],   # #8b949e  6,15:1
        "pie":           "#79828d",              #          4,86:1
        "intencion":     "italic dim white",
        "aviso":         "yellow",
        # 'red' es #c50f1f en Campbell: 3,12:1, LO MAS APAGADO de la pantalla
        # -- las lineas '-' de un diff y el 'fallo:' de una tool quedaban mas
        # tenues que todo lo verde (5,5 a 15,4). 'bright_red' (#e74856) mide
        # 4,92:1, pasa AA, sigue leyendose rojo y no se confunde con el ambar
        # del aviso (#c19c00, hue 48 contra hue 355).
        "error":         "bright_red",
        # Decision 17: la respuesta del modelo va en el color de texto NORMAL
        # de la terminal. 'default' es literalmente eso -- y ademas es lo unico
        # que se lee igual de bien en una terminal de fondo raro.
        "respuesta":     "default",
        # 'cuerpo' = el CUERPO de un listado (/sesiones, /stats, /kg *...).
        # Era 'cyan' (5,94 aca, 2,96 en claro): el bloque de texto MAS GRANDE
        # del producto pintado con el color menos legible de la pantalla. Un
        # listado se LEE, asi que va en texto normal como la respuesta. Es un
        # ROL aparte y no el mismo 'respuesta' a proposito: /color (COGNIA_
        # ACCENT) tine lo que CONTESTA EL MODELO, y el dueno que elige un
        # acento para las respuestas no esta eligiendo tenir /stats.
        "cuerpo":        "default",              # 11,78:1
    },
    "claro": {
        # La MISMA estructura que 'oscuro', con la rampa clara: exito_fuerte y
        # identidad_fuerte en 'prompt', exito en 'solido', actividad e
        # identidad en 'marco', identidad_tenue en 'estado'. Contrastes sobre
        # #fbfbfa: 8,20 / 6,62 / 4,60 / 5,67 (antes: dark_green 7,69 para los
        # seis, un verde que no era ninguno de los del marco).
        "exito_fuerte":  "bold " + _CLA["prompt"],
        "exito":         _CLA["solido"],
        "actividad":     _CLA["marco"],
        "identidad":       _CLA["marco"],
        "identidad_fuerte": "bold " + _CLA["prompt"],
        "identidad_tenue":  _CLA["estado"],
        "acento":        "blue",
        "acento_fuerte": "bold blue",
        "objeto":        "bold black",
        "detalle":       "grey30",
        # Punto 8, lado claro: 'grey50' daba 3,81:1 en los dos. Mismo criterio
        # que en oscuro -- jerarquia detalle (8,04) > tenue (6,43) > pie (4,67)
        # y las dos ultimas sobre AA.
        "tenue":         "#565d66",   # 6,43:1
        "pie":           "#6b7280",   # 4,67:1
        "intencion":     "italic grey30",
        "aviso":         "orange4",  # 'dark_orange' 2,33:1 / 'dark_orange3' 3,67:1
        "error":         "red",
        "respuesta":     "default",
        "cuerpo":        "default",              # 15,40:1  (era 'cyan': 2,96)
    },
    "alto_contraste": {
        # Misma estructura, con la rampa corrida un escalon: 15,35 / 10,96 /
        # 11,93 / 9,34.
        "exito_fuerte":  "bold " + _ALT["prompt"],
        "exito":         _ALT["solido"],
        "actividad":     _ALT["marco"],
        "identidad":       _ALT["marco"],
        "identidad_fuerte": "bold " + _ALT["prompt"],
        "identidad_tenue":  _ALT["estado"],
        "acento":        "bright_cyan",
        "acento_fuerte": "bold bright_white",
        "objeto":        "bold bright_white",
        "detalle":       "white",
        "tenue":         "grey74",
        "pie":           "grey74",
        "intencion":     "italic grey74",
        "aviso":         "bright_yellow",
        "error":         "bright_red",
        # Punto C del juicio visual: 'alto_contraste' subia TODO menos el
        # bloque de texto mas grande de la pantalla (la respuesta), porque el
        # acento vivia fuera del tema. Ahora es un rol mas y tambien sube.
        "respuesta":     "bold bright_white",
        # El cuerpo de un listado tambien sube, pero SIN bold: una tabla de
        # /stats entera en negrita deja de tener jerarquia interna (la
        # respuesta del modelo sigue siendo lo unico en bold de la pantalla).
        "cuerpo":        "bright_white",         # 16,90:1
    },
}

# Orden de ciclado de /tema y descripciones del selector.
ORDEN_VARIANTES = list(VARIANTES)
DESCRIPCION_VARIANTES = {
    "oscuro":         "colores vivos sobre fondo oscuro (default)",
    "claro":          "paleta sobria para terminal con fondo claro",
    "alto_contraste": "blanco brillante, maxima legibilidad",
}

# ---------------------------------------------------------------------------
# 5. El acento configurable (COGNIA_ACCENT)
# ---------------------------------------------------------------------------
# Colorea las RESPUESTAS del modelo y lo fija el dueno con /color; persiste en
# ~/.cognia/config.env.
#
# DECISION 17 (dueno, 2026-08-17): el defecto deja de ser 'cyan' y pasa a ser
# el COLOR DE TEXTO NORMAL. Ni verde ni cyan: el color queda para la INTERFAZ
# (marco, actividad, estados) y el bloque mas grande de la pantalla -- lo que
# el modelo contesta -- se lee como texto, no como un elemento decorado.
# Dos razones medidas ademas del gusto:
#   * el cyan de Campbell (#3a96dd) da 5,94:1, por debajo de casi todo el
#     chrome verde que lo rodea: lo importante era lo mas apagado;
#   * 'alto_contraste' no cambiaba la respuesta NI UN HEX (punto C del juicio
#     visual) porque el acento vivia fuera del tema.
# El defecto es el TOKEN 'respuesta', no un color: asi cada variante decide
# (oscuro/claro -> 'default' de la terminal; alto_contraste -> bold blanco).
# COGNIA_ACCENT sigue mandando: quien ya tenga 'cyan' guardado conserva cyan,
# porque el env var se lee ANTES que este defecto. /color normal vuelve aca.
ACENTO_DEFECTO = "respuesta"


def tema_cli(variante: str) -> dict:
    """Tokens de rich -> estilo, para una variante ('oscuro'/'claro'/...).

    Devuelve un dict plano listo para `rich.theme.Theme(...)`; no importa rich
    a proposito, para que la paleta siga siendo importable sin dependencias."""
    roles = VARIANTES[variante]
    return {token: roles[rol] for token, rol in TOKENS_CLI.items()}


def rampa(variante: str = "oscuro") -> dict:
    """Los siete escalones del verde de identidad de una variante.

    Es lo que tienen que pedir las piezas que NO pasan por el tema de rich (el
    marco del prompt de prompt_toolkit, el 'cognia>' crudo, el gradiente del
    banner): antes clavaban VERDE y por eso '/tema claro' no las tocaba."""
    return RAMPA[variante]


def diff_fondos(variante: str = "oscuro") -> dict:
    """Las cuatro bandas del diff de una variante ('mas'/'menos' + '_intra')."""
    return DIFF_FONDO[variante]


def gradiente_banner(pasos: int, variante: str = "oscuro") -> list:
    """`pasos` hex interpolados del 'profundo' al 'matrix' de la variante.

    Es el degradado del gato + el logotipo del arranque. Con pasos<=1 devuelve
    el color de ARRANQUE (una sola linea no tiene degradado que recorrer; es lo
    que hacia el calculo a mano de cli.py, que partia de t=0).

    OJO con el sentido: en 'oscuro' y 'alto_contraste' va de oscuro a brillante
    (decision 18: el gato visible desde la primera fila); en 'claro' va de
    CLARO a OSCURO, que es el mismo efecto -- arrancar visible y ganar peso --
    leido sobre blanco. La direccion no esta cableada aca: sale de que en la
    rampa clara 'profundo' sea el extremo mas tenue sobre #fbfbfa."""
    extremos = (RAMPA[variante]["profundo"], RAMPA[variante]["matrix"])
    desde, hasta = (int(c.lstrip("#"), 16) for c in extremos)
    d_r, d_g, d_b = (desde >> 16) & 0xFF, (desde >> 8) & 0xFF, desde & 0xFF
    h_r, h_g, h_b = (hasta >> 16) & 0xFF, (hasta >> 8) & 0xFF, hasta & 0xFF
    if pasos <= 1:
        return [f"#{d_r:02x}{d_g:02x}{d_b:02x}"] * max(0, pasos)
    salida = []
    for i in range(pasos):
        t = i / (pasos - 1)
        r = int(d_r + t * (h_r - d_r))
        g = int(d_g + t * (h_g - d_g))
        b = int(d_b + t * (h_b - d_b))
        salida.append(f"#{r:02x}{g:02x}{b:02x}")
    return salida
