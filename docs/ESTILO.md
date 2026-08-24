# Cognia — Estilos por elemento (`/estilo`)

Documentacion de usuario del sistema de estilos por elemento del REPL.
Fecha: 2026-08-24 (revisada 16:20). Estado: **P0-P11 en `main`** (`/estilo`,
editor, prompt/barra/menus, glifos y textos, banner, spinner, pulso del prompt
y hot reload); cada afirmacion de este fichero se verifico con grep contra el
codigo. La seccion "Estado de la entrega", al final, dice exactamente que hay
y que falta (agentes.*, migracion E11, barra.* animada, `global.*`, `/estilo banner`,
P12).

---

## 1. Que es

Cada elemento visual del REPL — el banner, el prompt, la barra de estado, los
menus, el spinner, las marcas de tools, la respuesta, el razonamiento, los
avisos, el footer, los paneles, el diff, la regla, los textos de sistema y la
vista F2 de agentes — tiene un **id** (`prompt.etiqueta`, `banner.arte`,
`spinner.pensar`...) y un conjunto de **propiedades** que acepta: texto,
color, fondo, negrita/italica/subrayado, glow (color + intensidad),
animacion (barrido o pulso), glifo, posicion, alineacion, visible, gradiente
y separador. Hay **50 elementos en 15 grupos**.

Las tres reglas que lo gobiernan:

1. **Sin fichero, nada cambia ni un byte.** El aspecto por defecto es el de
   siempre y esta protegido por 26 snapshots ANSI (`tests/golden/aspecto/`).
2. **Todo es un override parcial** apilado sobre ese default:
   `default del registro <- ~/.cognia/estilo.json <- cambios en memoria del editor`.
   El fichero solo guarda lo que difiere del default.
3. **Un valor invalido se rechaza con nombre y motivo**, nunca en silencio;
   un valor dudoso (contraste bajo, glifo que la consola no codifica,
   animacion en un elemento que no se redibuja) se acepta y se avisa.

`/tema` (oscuro / claro / alto_contraste) sigue mandando: los colores por
defecto son referencias `@rampa.*` / `@token.*` a la paleta de la variante, asi
que un estilo que no fija colores en hex obedece a `/tema`.

Modulos: `cognia/ux/aspecto.py` (registro, fichero, presets, validacion),
`cognia/ux/glow.py` (motor de glow/barrido y deteccion de capacidades),
`cognia/ux/editor_aspecto.py` + `cognia/ux/editor_app.py` (editor interactivo),
`cognia/ux/spinner_vivo.py` (spinner), `cognia/ux/presets/*.json` y
`cognia/ux/estilo.schema.json`.

---

## 2. En 5 minutos

Los subcomandos `/estilo ...` estan en `main` (`cli._slash_estilo`). El REPL
carga `~/.cognia/estilo.json` **al arrancar** (`cli._aplicar_config_estilo`:
`aspecto.conectar_glow(_load_config)` + `aspecto.cargar()`; un fichero roto
avisa por el degradado `estilo` y se arranca con el aspecto por defecto, nunca
sin prompt) y reconstruye la Console antes del banner si hay overrides. La
forma equivalente en el fichero es la que documenta este fichero; tambien se
prueba con los scripts de puerta (seccion 9) o desde Python:

```bash
PYTHONUTF8=1 ./venv312/Scripts/python.exe -c "from cognia.ux import aspecto as A; A.cargar(); print(A.texto('prompt.etiqueta'))"
```

### Ejemplo 1 — renombrar el prompt a `jarvis`

```
/estilo prompt.etiqueta texto jarvis
```

Equivalente en el fichero:

```json
{
  "version": 1,
  "elementos": {
    "prompt.etiqueta": { "texto": "jarvis" }
  }
}
```

Es lo mismo que hace el editor con la secuencia `↓ x7, Enter, Enter,
Backspace x6, jarvis, Enter, Ctrl-S, Esc` (es la puerta medida de P11). El
`jarvis➤` se ve en el prompt real al guardar (P5: `cli._mensaje_prompt` lee
`aspecto.texto('prompt.etiqueta')` y el glifo de `prompt.flecha`).

### Ejemplo 2 — glow y barrido en el banner

```
/estilo banner.arte glow.intensidad 2
/estilo banner.arte animacion.activa on
/estilo banner.arte animacion.solo_al_llegar on
/estilo banner                                reimprime el banner con el estilo actual
```

O de golpe con un style string: `/estilo banner.arte "glow:/2 anim:barrido>3,8"`
(glow derivado del color base a intensidad 2; barrido hacia la derecha,
velocidad 3, ventana de 8 celdas). En el fichero:

```json
{
  "version": 1,
  "elementos": {
    "banner.arte": {
      "glow": { "intensidad": 2 },
      "animacion": { "activa": true, "tipo": "barrido", "direccion": "derecha",
                     "velocidad": 3, "ancho": 8, "solo_al_llegar": true }
    }
  }
}
```

El banner **si esta enganchado en `main`** (P7): con ese fichero cargado el
gato hace UN barrido al arrancar y se queda quieto con el halo. Por un pipe
(`echo /salir | python -m cognia`) sale estatico, sin un solo cursor-up.

### Ejemplo 3 — cargar el preset `neon` y volver

```
/estilo presets                               lista los del paquete y los tuyos
/estilo cargar neon                           copia el preset a estilo.json (antes hace el .bak)
/estilo deshacer                              restaura estilo.json.bak (un segundo deshacer vuelve a neon)
/estilo cargar clasico                        o: el preset vacio = los defaults
```

Cargar un preset no deja un "preset activo" como puntero: el fichero
`estilo.json` es la unica fuente de verdad y el nombre del preset queda en su
clave `nombre` solo como etiqueta.

---

## 3. Grupos y elementos

Tabla generada desde el registro (`aspecto.GRUPOS` y `REGISTRO[id].caps`,
2026-08-24). **vivo** = el elemento se redibuja y puede animarse (los demas
son lineas impresas y no declaran `animacion`).
**estados** = sub-estilos que aceptan `estados.<nombre>.<prop>`.

Enganchados hoy en `main` (el REPL los lee de verdad; `aspecto.ENGANCHADOS`,
48 de 50): banner (P7), spinner (P8), prompt/barra/menu (P5, animacion del
prompt por P9), tool/aviso/footer/pensando/diff/separador/enlace/respuesta.
markdown/respuesta.codigo (P6), y el color por token del Theme de rich de
sistema.*, aviso.*, tool.verbo/objeto y panel.* (P4). Lo que NO se ve
todavia lo dice `/estilo` al guardar (`aspecto.paso_pendiente`): `agentes.*`
(vista F2) no esta enganchado y el glow de `respuesta.texto` tampoco; en `panel.cuerpo`,
`sistema.*`, `aviso.info/error`, `tool.verbo/objeto` solo cambia el color; la
animacion de `prompt.texto/continuacion/busqueda/seleccion`, `barra.*` y
`menu.*` (y el glow de `barra.estado`/`barra.modo`) no se anima.

### banner
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `banner.arte` | Gato Braille + logotipo | color, glow, animacion, alineacion, visible, gradiente | si |  |
| `banner.marco` | Panel del banner (borde, titulo, subtitulo) | texto, color, negrita, glifo, visible |  | titulo, version, subtitulo |
| `banner.guia` | Columna 'Para empezar' | texto, color, visible |  | cabecera, regla, descripcion, atajo, atajo_accion |
| `banner.linea_modelo` | 'modelo X (:puerto)   modo Y   tema Z' | texto, color, visible |  | sin_backend |

### prompt
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `prompt.marco` | Reglas superior e inferior del marco | color, fondo, glow, animacion, glifo, posicion, visible | si |  |
| `prompt.etiqueta` | La etiqueta del prompt ('cognia') | texto, color, negrita, italica, subrayado, glow, animacion, posicion, visible | si |  |
| `prompt.flecha` | La flecha del prompt | color, negrita, glow, animacion, glifo, visible | si |  |
| `prompt.texto` | Lo que escribe el dueno | color, fondo, negrita, italica, subrayado |  |  |
| `prompt.continuacion` | Sangria de la linea continuada con '\' | texto, color |  |  |
| `prompt.espera` | Prompt del carril de fondo ('corrida 5s  F2 agentes...') | texto, color, glow, animacion | si | aviso |
| `prompt.busqueda` | Busqueda inversa Ctrl-R | color, fondo, negrita, italica |  |  |
| `prompt.seleccion` | Texto seleccionado en el prompt | color, fondo |  |  |

### barra
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `barra.estado` | Linea de estado bajo el marco | color, fondo, negrita, italica, glow, animacion, posicion, alineacion, visible, separador | si |  |
| `barra.estado.secciones` | Colores por seccion de la barra | color | si | modelo, dir, rama, sucio, ctx, ctx_alto, ctx_critico, tokens |
| `barra.atajos` | 'tab completa · ↑↓ historial · ...' | texto, color, visible, separador | si | tecla, accion |
| `barra.modo` | Insignia PLAN / auto / manual | texto, color, negrita, glow, animacion | si | plan, auto, manual |

### menu
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `menu.completado` | Menu flotante de '/' y '@' | color, fondo, negrita |  | activo, meta, meta_activo, coincidencia, scrollbar, scrollbar_boton |
| `menu.selector` | Selector con flechas (/tema, F3, permisos) | color, fondo, negrita, glifo |  | activo, descripcion |

### spinner
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `spinner.tool` | '· Leyendo motor.py… (12s · ~340 tok · ctrl+c corta)' | texto, color, negrita, italica, glow, animacion, glifo, separador | si |  |
| `spinner.pensar` | '· <verbo gato>… (Ns · ...)' | texto, color, negrita, italica, glow, animacion, glifo, separador | si |  |
| `spinner.comando` | 'Procesando...' / 'Mejorando el prompt...' | texto, color, glifo | si |  |

### tool
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `tool.ok` | Marca de tool terminada | color, negrita, glifo |  |  |
| `tool.error` | Marca de tool fallida | color, glifo |  |  |
| `tool.curso` | Marca de tool en curso | color, glifo |  |  |
| `tool.verbo` | 'Leyendo' | color, negrita, italica |  |  |
| `tool.objeto` | 'motor.py' | color, negrita, italica, subrayado |  |  |
| `tool.resultado` | '  ⎿ 46 lineas' / '… +197 lineas (/expandir 3)' | texto, color, glifo |  |  |
| `tool.intencion` | '  Voy a leer...' | color, negrita, italica, visible |  |  |

### respuesta
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `respuesta.texto` | Lo que contesta el modelo | color, fondo, negrita, italica, glow | si |  |
| `respuesta.markdown` | Titulos, codigo inline, enlaces, negritas del markdown | color, negrita, italica |  | h1, h2, h3, code, link, strong, em, hr, item |
| `respuesta.codigo` | Bloques de codigo (tema pygments) | texto |  |  |

### pensando
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `pensando.prosa` | Razonamiento en vivo ('∴ ...') | color, negrita, italica, glifo, visible |  |  |
| `pensando.plegado` | '∴ pensó 4s (ctrl+o ...)' | texto, color, glifo |  |  |

### aviso
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `aviso.degradado` | '  ⚠ degradado — x: motivo' + '  → accion' | texto, color, negrita, glifo |  |  |
| `aviso.info` | Avisos tenues | color, italica |  |  |
| `aviso.error` | Errores de comandos y logs ERROR | color, negrita |  |  |

### footer
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `footer.turno` | '  ✓ 12.3s · 840 tokens · 3 pasos' | texto, color, glifo, visible, separador |  | ok, error |

### panel
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `panel.borde` | Bordes de los paneles de chrome | color, glifo |  |  |
| `panel.titulo` | Titulos de paneles y secciones | texto, color, negrita |  |  |
| `panel.cuerpo` | Cuerpo de listados (/ayuda, /config, /sesiones) | color, italica |  |  |

### diff
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `diff.mas` | Lineas '+' del preview | color, fondo, negrita, glifo |  | marca, intra |
| `diff.menos` | Lineas '-' del preview | color, fondo, negrita, glifo |  | marca, intra |

### separador
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `separador.regla` | Regla fina de /ayuda y console.rule | color, glifo |  |  |

### sistema
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `sistema.ok` | Confirmaciones [ok_cl] | color, negrita |  |  |
| `sistema.detalle` | Prosa secundaria [detail] | color, italica |  |  |
| `enlace` | Rutas con hyperlink OSC-8 (ctrl+click) | color, subrayado, visible |  |  |

### agentes
| id | que es | propiedades | vivo | estados |
|---|---|---|---|---|
| `agentes.acento` | Vista F2: acento (identidad) | color, fondo |  |  |
| `agentes.panel` | Vista F2: paneles | color, fondo |  |  |
| `agentes.borde` | Vista F2: bordes | color, fondo |  |  |
| `agentes.texto` | Vista F2: texto y fondo de la app | color, fondo |  |  |

Notas del registro:

- **Contrato del remoto.** Bajo `COGNIA_REMOTO=1`, `tool.ok`, `tool.error`,
  `tool.curso`, `tool.resultado`, `pensando.prosa`, `pensando.plegado`,
  `aviso.degradado` y `footer.turno` devuelven el **texto y el glifo por
  defecto** aunque el fichero diga otra cosa: son las marcas que el
  clasificador del movil reconoce. El color si se respeta.
- **Textos multiples.** Cuando un elemento tiene varios textos (`banner.marco`
  tiene `titulo` y `subtitulo`; `banner.guia` tiene 12; `spinner.tool` tiene
  `hint`, `tok`, `spinner_rich`) se escriben como `texto.<clave>`; un
  `texto` a secas se rechaza nombrando las claves validas.
- **Identidad.** `banner.arte visible off` se guarda pero avisa
  ("identidad: el banner va por defecto"), y al arrancar sale una linea
  `arte del banner oculto por /estilo (identidad: /estilo banner.arte visible on lo devuelve)`.
- Un id desconocido da un `KeyError` con los ids parecidos
  (`elemento desconocido 'prompt.etiquet'; ids parecidos: prompt.etiqueta, ...`).

---

## 4. Propiedades y valores validos

Un valor se valida **en las tres variantes** (`oscuro`, `claro`,
`alto_contraste`) antes de aceptarse. Tecleado en `/estilo` o en el editor,
los booleanos admiten `on/off`, `true/false`, `si/no`, `1/0`; los enteros se
convierten; el gradiente se escribe `desde,hasta`.

### Colores (`color`, `fondo`, `glow.color`, `gradiente[i]`)

| Forma | Ejemplo | Que es |
|---|---|---|
| hex | `#7ee62a` | color fijo (no obedece a `/tema`) |
| `@rampa.<escalon>` | `@rampa.prompt`, `@rampa.marco`, `@rampa.estado`, `@rampa.texto`, `@rampa.profundo`, `@rampa.matrix`, `@rampa.solido` | la rampa verde de la variante activa |
| `@token.<token>` | `@token.marca`, `@token.ok_cl`, `@token.pensar`, `@token.markdown.h1` | un estilo del Theme de rich del CLI (`paleta.tema_cli`); trae su bold/italic/dim |
| `@semantico.<k>`, `@superficie.<k>`, `@menu.<k>`, `@diff.<k>` | `@semantico.ok`, `@superficie.panel`, `@menu.fondo_activo`, `@diff.mas` | las otras tablas de `paleta.py` |
| `@mi.<nombre>` | `@mi.lima_alta` | la **paleta local** del fichero (clave `paleta`) |
| `terminal` | | heredar el color de la terminal (`''` en prompt_toolkit, `default` en rich) |
| `rich` | | no declarar: deja el default de rich (solo `respuesta.markdown` y `menu.completado.coincidencia`) |
| `ansi<nombre>` | `ansigreen`, `ansibrightblack` | los 16 basicos de prompt_toolkit (el preset `ansi16` solo usa estos) |
| nombre de rich | `bold cyan`, `grey74` | un estilo de rich; se traduce a hex/ansi |
| por variante | `{"oscuro": "#...", "claro": "#...", "alto_contraste": "#..."}` | un valor por variante; faltar una es error |

**Contraste.** Cada `color` se mide contra el fondo de cada variante (o contra
el `fondo` propio del elemento si lo declara) con la formula WCAG 2.1: piso
**4,5:1** para texto y **3,0:1** para elementos graficos (bordes, reglas,
bandas, el arte del banner). Bajar del piso no se rechaza: se avisa
(`contraste bajo el piso 4,5 (2,4:1 en oscuro; 2,4:1 en alto_contraste)`), y el editor marca el
elemento con `!`.

### glow

`glow` es un objeto `{color, intensidad}`. `intensidad` va de **0 a 3**:
0 nada; 1 mezcla al 25 %; 2 mezcla al 50 % + negrita; 3 mezcla al 75 % +
negrita + halo. `color` es opcional: sin el, el glow se **deriva** del color
base aclarado un 60 % hacia blanco (en `oscuro` y `alto_contraste`) o hacia
**negro** en `claro` (un glow mas claro sobre fondo claro haria invisible el
elemento).

### animacion

Objeto con estas claves (todas opcionales; lo que no se escribe conserva el
default):

| clave | valores | default | nota |
|---|---|---|---|
| `activa` | bool | `false` | |
| `tipo` | `barrido` \| `pulso` | `barrido` | barrido = ventana que recorre el texto; pulso = el elemento entero respira |
| `direccion` | `derecha` \| `izquierda` \| `ida_vuelta` | `derecha` | `ida_vuelta` dura el doble por ciclo |
| `velocidad` | 1..5 | 2 | periodo de un barrido: 1 = 3,0 s, 2 = 2,0 s, 3 = 1,5 s, 4 = 1,0 s, 5 = 0,6 s |
| `ancho` | 1..20 | 5 | semiancho de la ventana en celdas |
| `repetir` | entero >= 0 | 0 | 0 = infinito mientras el elemento este vivo; N = N barridos y para |
| `cada_s` | numero >= 0 | 0 | pausa entre barridos (0 = continuo) |
| `solo_al_llegar` | bool | `false` | UN barrido al aparecer y quieto (= `repetir: 1`) |

Solo los elementos **vivos** aceptan `animacion` (en el registro de hoy, todos
los que la declaran son vivos; en los demas se rechaza con la lista de
propiedades que si tienen). El motor cuantiza
la mezcla a 32 niveles y cachea los estilos: un frame cuesta ~0,17 ms. Toda
animacion **termina en el frame estatico** (nunca queda la ventana a mitad de
recorrido) y en los drivers finitos (banner al arrancar, pulso del prompt)
esta acotada a **3 s** (`glow.PULSO_MAX_S`), asi que `repetir: 0` en el banner
significa "3 s y quieto", no "para siempre".

### glifo y glifo_ascii

`glifo` es el caracter que sale por pantalla y `glifo_ascii` el que se usa si
`sys.stdout.encoding` no lo codifica (o con `COGNIA_ASCII=1`). Si el glifo no
se codifica se avisa (`'✔' no se codifica en cp1252; se usara '+'`). En
`banner.marco` y `panel.borde` el glifo es la **caja** y solo admite
`rounded | square | heavy | double | none`. En `spinner.comando` el glifo es
el nombre del spinner de rich (`dots`...).

### posicion y alineacion

Solo los elementos que las declaran:

| elemento | posicion | alineacion |
|---|---|---|
| `prompt.marco` | `ambos` \| `arriba` \| `abajo` \| `ninguno` | |
| `prompt.etiqueta` | `linea` \| `arriba` | |
| `barra.estado` | `abajo` \| `arriba` | `izquierda` \| `derecha` |
| `banner.arte` | | `izquierda` \| `centro` \| `derecha` |

### visible, negrita, italica, subrayado, separador, gradiente, texto

- `visible`: bool. En `enlace`, `false` apaga el hyperlink OSC-8. En
  `banner.arte` y `banner.marco`, `false` esconde el banner (con el aviso de
  identidad).
- `negrita`, `italica`, `subrayado`: bool. Sin declarar, los aporta el token
  del tema (un `@token.x` con `bold` sale en negrita).
- `separador`: el ` · ` de barra, spinner y footer (` | ` en ASCII).
- `gradiente`: `[desde, hasta]`, solo `banner.arte` (default
  `["@rampa.profundo", "@rampa.matrix"]`).
- `texto`: un string, o `texto.<clave>` en los elementos con varios.

### Style string (forma compacta)

Para `/estilo <id> "<string>"` y para la fila **estilo rapido** del editor:

```
bold|nobold  italic|noitalic  underline|nounderline  visible|hidden
fg:<color>  bg:<color>  glow:<color>/<0-3>  (glow:/2 = color derivado)
anim:<barrido|pulso><</>/<>>[velocidad][,ancho][,cada_s]   noanim
glifo:"<s>"  ascii:"<s>"  texto:"<s>"  texto.<clave>:"<s>"
pos:<enum>  align:<enum>  sep:"<s>"
```

`>` = derecha, `<` = izquierda, `<>` = ida y vuelta. Ejemplo:
`bold fg:@rampa.prompt glow:@mi.lima/1 anim:barrido>2` se lee como negrita,
color de la rampa, glow a intensidad 1 con la paleta local y barrido a la
derecha a velocidad 2. Lo que no cabe en la gramatica (`repetir`,
`solo_al_llegar`, `estados.*`, `gradiente`, colores por variante) va por
`/estilo <id> <prop> <valor>` o por el fichero. Un token desconocido es un
error con la lista de tokens validos.

---

## 5. El fichero y los presets

### Rutas

```
~/.cognia/estilo.json            el estilo activo (override parcial)
~/.cognia/estilo.json.bak        copia previa al ultimo guardado (deshacer)
~/.cognia/estilos/<nombre>.json  presets del dueno (mismo formato)
cognia/ux/presets/*.json         presets del paquete (5)
cognia/ux/estilo.schema.json     JSON Schema (draft-07) para editar a mano con ayuda del editor de texto
~/.cognia_config.json            clave "estilo_animacion": "on" | "off" (interruptor global; en cli._CONFIG_DEFAULTS, lo escribe /estilo animacion y la tecla `a` del editor)
```

### Forma del fichero (version 1)

```json
{
  "$schema": "<ruta a cognia/ux/estilo.schema.json>",
  "version": 1,
  "nombre": "etiqueta libre",
  "nota": "texto libre",
  "paleta": { "lima_alta": "#c8ff7a" },
  "global": { "fps": 12, "respuesta_sangria": 2, "glifos": "auto" },
  "elementos": {
    "<id>": { "<prop>": ..., "estados": { "<estado>": { "<prop>": ... } } }
  }
}
```

- `paleta`: colores propios, referenciables como `@mi.<nombre>`; cada entrada
  es un color valido (hex, `@ref`, por variante) y no puede apuntar a `@mi.*`.
- `global.fps` (1..30), `global.respuesta_sangria` (0..8) y `global.glifos`
  (`auto | unicode | ascii`) se **validan**; hoy el motor corre a `glow.FPS = 12`
  y los glifos los decide `COGNIA_ASCII` y el encoding. Aplicar `global.*`
  esta **pendiente** (`aspecto.fps()` existe y `glow` no lo consume).
- Un fichero sin `version` se trata como 1; una version **mayor** que la que
  entiende Cognia se rechaza con "actualiza cognia". Las claves que Cognia no
  conoce se avisan y se **conservan** al guardar.
- `guardar()` escribe solo lo que difiere del default (una propiedad puesta al
  mismo valor que el default no se escribe), hace el `.bak` si el fichero ya
  existia y pone `$schema`.
- `exportar(<ruta>)` escribe un fichero **autocontenido**: los 50 elementos
  con su estilo completo (con las `@refs` tal cual, para que siga obedeciendo a
  `/tema`), la paleta local y lo global; sin `$schema` ni nada de la maquina.
- Un fichero con errores de validacion **no se instala**: `cargar()` lanza
  `EstiloInvalido` con la lista de avisos (los errores primero) y se sigue con
  los defaults. Nunca sin prompt.
- Las rutas explicitas de preset (`/estilo cargar C:\...\x.json`) solo se
  aceptan **bajo `$HOME`**.

### Hot reload

`recargar_si_cambio()` hace un `stat` del fichero y **solo marca** la recarga
como pendiente; `aplicar_recarga()` recarga de verdad fuera del render de
prompt_toolkit (reconstruir la consola dentro del render es la misma carrera
que el repo ya documenta). Si el fichero editado a mano esta mal, se avisa y
se sigue con lo cargado antes, sin reintentar en cada redibujado. Cableado
(P9): el `_toolbar` de `cli._pie_prompt` llama `recargar_si_cambio()` en cada
redibujado y `cli._aplicar_recarga_estilo` aplica en el bucle del REPL con el
prompt ya devuelto (test `test_cli_estilo`, hot reload por mtime).

### Presets del paquete

| nombre | que hace |
|---|---|
| `clasico` | vacio (`"elementos": {}`): los defaults. Cargarlo = `/estilo reset todo`. |
| `barra-color` | la barra de estado con los colores logicos de `harness/barra_estado.py` (rama con acento, ctx alto en ambar, ctx critico en rojo, insignias PLAN/auto/manual con su color). |
| `neon` | glow 2 y barrido: el gato hace UN barrido al arrancar y queda con halo; la etiqueta del prompt barre al aparecer y cada 6 s; el spinner barre mientras piensa. |
| `sobrio` | sin glow y sin animacion en TODOS los vivos, dicho explicitamente (tapa cualquier estilo previo); flecha y reglas en ASCII; barra de atajos apagada. |
| `ansi16` | accesibilidad: SOLO nombres de los 16 colores ANSI, para que la paleta de la terminal decida cada tono; sin glow ni animacion; no se garantiza piso de contraste. |

Un preset del dueno con el mismo nombre **tapa** al del paquete.

`cognia/ux/presets/neon.json`, tal cual esta en el paquete:

```json
{
  "version": 1,
  "nombre": "neon",
  "nota": "Glow 2 y barrido: el gato hace UN barrido al arrancar y queda con halo; la etiqueta del prompt barre al aparecer y cada 6 s; el spinner barre mientras piensa. Los colores son los de la variante activa (/tema sigue mandando).",
  "paleta": {
    "lima_alta": "#c8ff7a"
  },
  "global": {
    "fps": 12
  },
  "elementos": {
    "banner.arte": {
      "glow": { "color": "@mi.lima_alta", "intensidad": 2 },
      "animacion": { "activa": true, "tipo": "barrido", "direccion": "derecha", "velocidad": 3, "ancho": 8, "solo_al_llegar": true }
    },
    "banner.marco": {
      "negrita": true
    },
    "prompt.marco": {
      "glow": { "intensidad": 1 },
      "animacion": { "activa": true, "tipo": "barrido", "direccion": "derecha", "velocidad": 3, "ancho": 12, "solo_al_llegar": true }
    },
    "prompt.etiqueta": {
      "glow": { "color": "@mi.lima_alta", "intensidad": 2 },
      "animacion": { "activa": true, "tipo": "barrido", "direccion": "derecha", "velocidad": 2, "ancho": 3, "cada_s": 6 }
    },
    "prompt.flecha": {
      "glow": { "color": "@mi.lima_alta", "intensidad": 1 }
    },
    "barra.modo": {
      "glow": { "intensidad": 1 }
    },
    "spinner.pensar": {
      "glow": { "intensidad": 1 },
      "animacion": { "activa": true, "tipo": "barrido", "direccion": "derecha", "velocidad": 2, "ancho": 5 }
    },
    "spinner.tool": {
      "glow": { "intensidad": 1 },
      "animacion": { "activa": true, "tipo": "barrido", "direccion": "derecha", "velocidad": 2, "ancho": 5 }
    }
  }
}
```

---

## 6. El comando `/estilo`

En `main` (`cli._slash_estilo`, `_estilo_*`). Cada escritura valida, guarda (con
`.bak`), aplica en caliente e imprime una linea
`prompt.etiqueta.texto = jarvis (guardado)`; los errores salen por el aviso de
degradacion con nombre y motivo.

```
/estilo                              abre el editor (cli._estilo_editor); si no se puede abrir, avisa y degrada a la ayuda textual
/estilo lista [grupo]                tabla: id · nombre · props soportadas · marcas * (anim) / mod (difiere) / ! (contraste)
/estilo ver [<id>]                   valores resueltos + origen por clave; sin id: global + cambios contra el default
/estilo <id> <prop> <valor>          /estilo prompt.etiqueta texto jarvis · /estilo banner.arte glow.intensidad 2
                                     /estilo prompt.marco animacion.activa on · /estilo barra.estado posicion arriba
/estilo <id> "<style string>"        /estilo prompt.etiqueta "bold fg:@rampa.prompt glow:@mi.lima/1 anim:barrido>2"
/estilo reset [<id>|todo]            vuelve al default ('todo' pide confirmar si hay tty)
/estilo animacion on|off             escribe la config 'estilo_animacion'; COGNIA_ANIMACION=0 gana y se avisa
/estilo guardar <nombre>             ~/.cognia/estilos/<nombre>.json (estado completo)
/estilo cargar [<nombre>|<ruta>]     sin arg: selector con flechas (preview al mover, Esc revierte)
/estilo presets                      lista los del dueno y los del paquete
/estilo exportar <ruta>              fichero autocontenido
/estilo deshacer                     restaura estilo.json.bak
/estilo banner                       PENDIENTE: hoy solo avisa; cli._reimprimir_banner existe y no esta cableado a este subcomando
/estilo ayuda                        = /ayuda /estilo
```

`/tema` convive: cambia la variante; `/estilo` cambia elementos sobre la
variante. `/estilo_info` (estilo de aprendizaje) es otro comando y no colisiona.

---

## 7. El editor interactivo

Se abre con `/estilo` a secas (`cli._estilo_editor`, solo desde el bucle del
REPL con el prompt ya devuelto; para el status del renderer antes) o desde
Python (es la puerta medida de P11):

```bash
PYTHONUTF8=1 ./venv312/Scripts/python.exe -c "from cognia.ux.editor_aspecto import abrir_editor; print(abrir_editor())"
```

Es una `Application(full_screen=True)` de prompt_toolkit en la **pantalla
alterna**: el scrollback del REPL queda intacto y al salir la terminal vuelve
como estaba. Devuelve `('guardado' | 'descartado' | 'cerrado', resumen)` o
`('no_abrible', motivo)`.

**Guardas** (en este orden; si una falla devuelve `no_abrible`, el REPL
avisa por el degradado `estilo.editor` e imprime la ayuda textual): no hay
otra Application de prompt_toolkit corriendo (el editor nunca se anida: se
cuelga); `COGNIA_REMOTO != 1`; no hay corrida en el carril de fondo; el
renderer no tiene un status vivo; hay tty real (stdin y stdout tty y consola
Win32). Por stdin (pipe) `/estilo` a secas imprime la ayuda.

### Pantalla

```
+- ELEMENTOS (28 col) -------+- PROPIEDADES: prompt.etiqueta (' cognia') -----------------------+
| banner                     |  texto        cognia                                            |
|   arte            *        |  color        @rampa.prompt   #7ee62a  7,9:1 oscuro  4,9:1 claro |
|   marco                    |  negrita      [x]   italica [ ]   subrayado [ ]                  |
| prompt                     |  glow         color -   intensidad 0                            |
| > etiqueta        mod      |  animacion    [ ] barrido  ->  velocidad 2  ancho 5  (vivo)     |
|   marco                    |  posicion     linea                                             |
|   ...                      |  estilo rapido  bold fg:@rampa.prompt                           |
+- VISTA PREVIA (v: variante oscuro) --------------------------------------------------------------+
|  <el elemento EN SU CONTEXTO, pintado con las mismas funciones del motor>                       |
+------------------------------------------------------------------------------------------------+
| Tab panel  Enter editar  Space alternar  +/- ajustar  / filtrar  ^Z/^Y deshacer/rehacer  ^S guardar ...
| guardado 12:03 · 3 elementos con cambios · variante oscuro · animacion global on
| <ultimo aviso / error / exito>
```

Marcas en la lista: `*` animacion activa, `mod` difiere del default, `!`
contraste bajo el piso en alguna variante. La vista previa se calcula con
las mismas funciones del motor (`glow.estilizar`, `frame_estatico`,
`gradiente_lineas`) y un reloj fijo: el frame es determinista y solo **anima**
(a `1/fps`) si el elemento seleccionado es vivo, tiene `animacion.activa` y el
interruptor global esta en on; si no, no repinta. Un fallo al calcular la
preview no tumba el editor: la fila muestra `preview: <Tipo>: <detalle>` y se
avisa.

Nada toca el disco hasta **Ctrl-S**. Esc con cambios sin guardar pregunta
`Hay cambios sin guardar: [g]uardar / [d]escartar / [v]olver`; descartar
restaura la instantanea tomada al abrir. Los avisos de validacion se muestran
siempre en la linea de mensaje: un error no se escribe y el motivo queda a la
vista; un aviso se acepta y se muestra.

### Teclas

| Tecla | Accion |
|---|---|
| `↑`/`↓`, `j`/`k` | mover en el panel activo (o en la lista flotante) |
| `PgUp`/`PgDn` | saltar 10 filas |
| `Home`/`End`, `g`/`G` | primera / ultima fila |
| `←`/`→` | cambiar de panel; en una propiedad numerica o enumerada, ajustar / ciclar |
| `Tab` / `Shift-Tab` | cambiar de panel (elementos <-> propiedades) |
| `Enter` | lista: plegar/desplegar grupo o ir a propiedades; propiedad: editar segun tipo (bool alterna, numero abre entrada, enum cicla, texto/glifo abre buffer, color abre el sub-selector, "estilo rapido" abre buffer con el style string) |
| `Space` | alternar bool; en enum, ciclar |
| `+` / `-` | ajustar numero (intensidad 0-3, velocidad 1-5, ancho 1-20, repetir 0-99, cada_s 0-60 de 0,5 en 0,5) |
| `/` | filtrar la lista por texto (Enter fija, Esc limpia) |
| `a` / `A` | interruptor GLOBAL de animacion (config `estilo_animacion`) / animacion del elemento actual |
| `v` | ciclar la variante de la vista previa (oscuro / claro / alto_contraste) sin tocar `/tema` |
| `r` / `R` | reset del elemento / de TODO (`R` pide confirmacion `s`/`n`) |
| `Ctrl-Z` / `Ctrl-Y` | deshacer / rehacer (pila de instantaneas, max 100, solo cambios confirmados) |
| `Ctrl-S` | guardar (validar + `.bak` + escribir + aplicar en caliente); el pie muestra `guardado HH:MM` |
| `Ctrl-P` | presets: listar y aplicar en memoria (Enter) |
| `Ctrl-L` | presets con preview de TODA la pantalla al mover; Esc revierte, Enter se queda |
| `Ctrl-N` | guardar el estado como preset (pide nombre) |
| `Ctrl-E` | exportar a una ruta (pide ruta) |
| `Backspace` / `Delete`, `Ctrl-U` | en un buffer de texto/glifo/numero/ruta: borrar el ultimo caracter / vaciar el buffer |
| `Ctrl-G` | en un glifo: lista de los glifos que Cognia ya usa (`➤ ─ ═ ● ⏺ ✗ ⚠ → ⎿ ∴ ❯ · … ✓ ░`) con aviso si la consola no los codifica |
| `?` / `F1` | ayuda de teclas |
| `Esc` / `q` | salir (con cambios: Guardar / Descartar / Volver); en un sub-modo: cancelar |

Sub-selector de color: pestanas (`Tab`) con las `@refs` de la paleta, la
paleta local `@mi.*` y hex libre (validado `#rrggbb`); `t` = `terminal`;
cada movimiento repinta la preview con el ratio de contraste por variante;
`Enter` fija, `Esc` vuelve al valor anterior.

---

## 8. Animacion: cuando se apaga sola y por que

`glow.capacidades()` decide el **nivel de color** y si se **anima**, en este
orden (el primero que aplica manda; `motivo` es el texto que sale en el aviso):

| # | condicion | efecto | motivo |
|---|---|---|---|
| 1 | `COGNIA_ANIMACION=0` | sin animacion | `COGNIA_ANIMACION=0` |
| 2 | config `estilo_animacion=off` (`/estilo animacion off`) | sin animacion | `config estilo_animacion=off (/estilo animacion on)` |
| 3 | `NO_COLOR` definido | sin color, sin animacion; el glow queda en negrita | `NO_COLOR` |
| 4 | rich no detecta color (`color_system None`) | sin color, sin animacion | `sin color (rich color_system None)` |
| 5 | `COGNIA_ANIMACION=1` | **fuerza** la animacion sobre lo que sigue (capturas y demos); no sobre 3 y 4: sin color no hay nada que barrer | |
| 6 | stdout no es una terminal (pipe, redireccion) | sin animacion | `sin tty (stdout no es una terminal)` |
| 7 | `COGNIA_REMOTO=1` | sin animacion | `COGNIA_REMOTO=1` |
| 8 | `SSH_TTY` / `SSH_CONNECTION` | sin animacion | `sesion SSH` |
| 9 | consola Windows legacy (sin VT) | sin animacion | `consola Windows legacy (sin VT)` |

Niveles de color: **truecolor** (`COLORTERM=truecolor|24bit`, `WT_SESSION`,
VS Code / iTerm / WezTerm, o la consola del CLI en truecolor) mezcla los hex;
**256** deja la degradacion a rich/prompt_toolkit; **16** va a tres escalones
(dim / normal / bold sobre el nombre ANSI); **none** = sin color, glow =
negrita, sin animar. El nivel es el de la consola que pinta (`cli._console`),
no el de `sys.stdout`.

Siempre queda un **frame estatico** con el glow fijo: por un pipe, el banner
sale con su gradiente y sin un solo cursor-up. La deteccion se cachea por
(variables de entorno relevantes, tty, deteccion de rich a 1 s): cambiar el
interruptor se ve en el siguiente frame.

Dos casos mas del banner (`glow.BannerVivo.mostrar`): si la terminal tiene
**menos filas** que el banner entero + 2, no se abre la Live (rich no puede
repintar lo que ya scrolleo) y se avisa `banner: terminal de N filas para M
del banner; sin barrido`; y si no se puede medir la altura, frame estatico
con aviso. El barrido del banner corre en la **unica Live libre del
arranque**, antes de crear la PromptSession, y dura como mucho 3 s.

Cero hilos permanentes: el spinner se anima dentro del `console.status` que
el renderer ya tiene (el ticker de 1 s existente y la Live del status recogen
el cuadro del reloj compartido `glow.RELOJ`); el prompt se animara por un
**pulso finito** de `app.invalidate()` acotado a 3 s (P9: `cli._arrancar_pulso_prompt`
antes de `session.prompt` y en la espera; `cli._rearmar_pulso_prompt` desde el
redibujado para `cada_s`), nunca
con `refresh_interval` fijo (medido: 17 % de CPU sostenido).

---

## 9. Garantia "default byte-identico" y como se verifica

La regla numero uno se protege con un **contrafactual**, no con confianza:

- `scripts/aspecto_snapshots.py` genera los 26 snapshots ANSI de
  `tests/golden/aspecto/*.ansi` (banner a 80 y 120 columnas, marco del prompt
  a 80 y 100, `prompt_espera`, barra, tools ok/error clasico y colapsado,
  intencion, footer, avisos, diff, spinner, respuesta prosa y markdown,
  paneles y regla, glifos, pensando, el `PTStyle` del prompt y los tokens del
  tema en las tres variantes). Todo lo que mueve la salida se fija dentro de
  `entorno_fijo()` (version, modelo, puerto, tamano de terminal, env
  `COGNIA_*`/`NO_COLOR`/`COLUMNS` sin definir, `COGNIA_ASCII=0`,
  `COGNIA_ENLACES=0`, reloj fijo).
- `tests/test_ux_aspecto.py::test_default_es_byte_identico_al_aspecto_actual`
  regenera cada snapshot con las MISMAS funciones y compara byte a byte; el
  mensaje dice en que byte difiere y si cambio el texto o solo el color.
  `test_no_hay_golden_huerfano_ni_faltante` cierra la lista.
- Ademas: `clases_pt(variante)` == el dict literal de `cli._estilo_prompt`
  (+ las 4 claves de prompt_toolkit con sus defaults) y
  `tema_rich(variante)` == `paleta.tema_cli(variante)` cuando no hay override.
  El motor devuelve el token del Theme **tal cual** cuando el elemento no tiene
  glow ni animacion ni override de color.

Comandos:

```bash
PYTHONUTF8=1 ./venv312/Scripts/python.exe scripts/aspecto_snapshots.py --comparar     # como el test
PYTHONUTF8=1 ./venv312/Scripts/python.exe scripts/aspecto_snapshots.py --ver banner_80
PYTHONUTF8=1 ./venv312/Scripts/python.exe scripts/aspecto_snapshots.py                # regenera TODOS (solo a proposito)
```

Un golden solo se regenera cuando el cambio de bytes es **deliberado** (un
pulido visual), y entonces se regenera **solo ese** y el diff se revisa linea
a linea.

### Puertas reales (ConPTY, el REPL de verdad contra el backend)

- `scripts/aspecto_demo.py [--segundos 2] [--fps 12] [--variante oscuro]`:
  las tres zonas vivas con el motor solo (banner en Live, LineaViva en
  status, prompt por pulso) e imprime frames y CPU; por un pipe todo sale
  estatico.
- `scripts/banner_gate_conpty.py [anim] [pipe] [cotidiano]`: estilo.json
  temporal con barrido + glow en el banner y titulo `JARVIS`; guarda y
  restaura el estilo.json del dueno byte a byte. Medido 2026-08-24 (ConPTY
  120x40, Qwen3.8-27B): **18 cuadros de barrido distintos**, frame final
  quieto con `JARVIS`; por pipe **0 cursor-up, 0 Live**; con el fichero del
  dueno restaurado, banner intacto (`COGNIA`, 0 barridos).
- `scripts/spinner_gate_conpty.py [on] [off]`: misma pregunta en dos brazos.
  Medido: on = **7 cuadros de barrido distintos** (hasta 10 colores en un
  cuadro); `COGNIA_ANIMACION=0` = **0 cuadros de barrido**, un color plano
  por cuadro.
- Editor (P11): en consola Win32 real por ConPTY, `abrir_editor()` con la
  secuencia `↓ x7, Enter, Enter, Backspace x6, jarvis, Enter, Ctrl-S, Esc`
  **entra y sale de la pantalla alterna** (`ESC[?1049h` ... `ESC[?1049l`) y
  deja `{"version": 1, "elementos": {"prompt.etiqueta": {"texto": "jarvis"}}}`
  en el fichero; el mismo recorrido corre en `tests/test_ux_editor_app.py`
  sobre `create_pipe_input` + `Vt100_Output`.

---

## 10. Degradacion: que avisos salen y de donde

Nada del sistema de estilos lanza hacia el turno; todo fallo de datos o de
terminal sale como aviso **visible**, una vez por turno y por motivo:

| via del aviso | quien lo emite | cuando |
|---|---|---|
| `estilo` | `cli._aspecto_del_banner` / `_print_banner_completo` | el registro no se puede leer (el banner sale como siempre); la terminal es mas baja que el banner (sin barrido); no se pudo medir la altura; el texto `sin_backend` no se pudo formatear |
| `glow` | `glow._avisar` | un id sin resolver (se pinta sin estilo), config `estilo_animacion` ilegible, la Live del banner falla (frame estatico) |
| `spinner` | `spinner_vivo._avisar` | el registro no se puede leer (defaults), un nombre de spinner de rich desconocido (`dots`), `spinner.comando` ilegible |
| `estilo.editor` | `editor_app._avisar` | la preview de un elemento no se puede calcular (la fila lo dice; el editor sigue) |

Con el CLI cargado van por `cli._aviso_degradado(via, detalle)` (la linea
ambar `⚠ degradado — via: motivo` del REPL, deduplicada por turno y con toast
opt-in). Sin CLI (tests, scripts) salen **una vez por motivo a stderr**:
`  degradado — glow: <motivo>`, `  degradado — spinner: <motivo>`,
`[degradado] estilo.editor: <motivo>`.

Los errores de **datos** del dueno no son degradacion sino rechazo con nombre:
`validar()` devuelve `Aviso(nivel='error'|'aviso', texto, id)`; `poner()` no
escribe si hay un error; `cargar()`/`cargar_preset()` lanzan `EstiloInvalido`
con los avisos y no instalan nada. Ejemplos de texto:

```
error: prompt.etiqueta: 'prompt.etiqueta' no tiene 'gradiente'; tiene: animacion, color, glow, ...
error: banner.arte: animacion.velocidad: 9 fuera de 1..5
error: prompt.etiquet: elemento desconocido 'prompt.etiquet' (parecidos: prompt.etiqueta, prompt.texto, prompt.busqueda)
aviso: sistema.ok: color: contraste bajo el piso 4,5 (2,4:1 en oscuro; 2,4:1 en alto_contraste)
error: tool.ok: 'tool.ok' no tiene 'animacion'; tiene: color, glifo, negrita
aviso: banner.arte: identidad: el banner va por defecto (se guarda, pero es la marca de Cognia)
```

---

## 11. Estado de la entrega (2026-08-24, 16:20)

**En `main`** (verificado con grep en este repo):

| paso | que | donde |
|---|---|---|
| P0 | 26 snapshots del aspecto actual + test golden byte a byte | `scripts/aspecto_snapshots.py`, `tests/golden/aspecto/`, `tests/test_ux_aspecto.py` |
| P1 | registro de 50 elementos en 15 grupos, resolucion por variante, validacion ruidosa, `clases_pt` y `tema_rich` | `cognia/ux/aspecto.py` |
| P2 | fichero `~/.cognia/estilo.json`, `.bak`/deshacer, presets (5 del paquete + los del dueno), exportar, schema, style string, deteccion de hot reload | `cognia/ux/aspecto.py`, `cognia/ux/presets/`, `cognia/ux/estilo.schema.json` |
| P3 | motor de glow/barrido con reloj inyectable, capacidades y orden de degradacion, frame estatico siempre, `LineaViva`, `BannerVivo`, pulso del prompt | `cognia/ux/glow.py`, `scripts/aspecto_demo.py` |
| P4 | `/estilo` con todos sus subcomandos (lista, ver, `<id> <prop> <valor>`, style string, reset, animacion, guardar, cargar, presets, exportar, deshacer, ayuda); `A.cargar()` al arrancar con aviso si el fichero esta mal (`_aplicar_config_estilo`); `_aplicar_tema_en_caliente()` compartido con `/tema`; `estilo_animacion` en `_CONFIG_DEFAULTS`; `/estilo` en `/ayuda` | `cognia/cli.py` (`_slash_estilo`, `_estilo_*`) |
| P5 | prompt (texto, glifo, posicion, color, glow estatico), barra de estado (secciones, posicion, alineacion, separador), menus, Ctrl-R y el selector con `A.clases_pt` | `cognia/cli.py` (`_mensaje_prompt`, `_pie_prompt`, `_frag_prompt`), `cognia/ux/barra_estado.py`, `cognia/ux/selector.py` |
| P6 | glifos y textos de `tool.*`, `aviso.degradado`, `footer.turno`, `pensando.*`, `separador.regla`, `diff.mas/menos`, `enlace` (visible apaga OSC 8), `respuesta.codigo` (tema pygments), `--help` con el Theme; contrato remoto intacto (`COGNIA_REMOTO=1` -> glifos clasicos) | `cognia/ux/renderer.py`, `cognia/harness/render_tools.py`, `cognia/console/diff_render.py`, `cognia/harness/enlaces.py`, `cognia/ux/markdown_vivo.py` |
| P7 | banner por elemento: textos, estilos por estado, caja, alineacion, visible con aviso de identidad, gradiente, glow y barrido con `BannerVivo` en la Live del arranque; `cli._reimprimir_banner` | `cognia/cli.py` (`_aspecto_del_banner`, `_print_startup_panel`, `_print_banner_completo`), `scripts/banner_gate_conpty.py` |
| P8 | spinner por elemento: `spinner.tool` / `spinner.pensar` animados con `LineaViva` dentro del `console.status`; los tres `console.status` de `spinner.comando` pasan por `spinner_vivo.comando()` | `cognia/ux/spinner_vivo.py`, `cognia/ux/renderer.py`, `cognia/cli.py`, `scripts/spinner_gate_conpty.py` |
| P9 | pulso del prompt (`prompt.etiqueta/marco/flecha/espera`) con UN hilo finito (`_arrancar_pulso_prompt` / `_rearmar_pulso_prompt` / `_cerrar_pulso_prompt`) y hot reload por mtime (`_toolbar` marca, `_aplicar_recarga_estilo` aplica) | `cognia/cli.py`, `scripts/prompt_gate_conpty.py` |
| P10 | modelo puro del editor (navegacion, filtro, edicion por tipo, undo/redo, presets en memoria, preview determinista) + transacciones en memoria del registro | `cognia/ux/editor_aspecto.py`, `cognia/ux/aspecto.py` (seccion 12) |
| P11 | Application full-screen del editor con las guardas, la preview animada solo cuando toca, `abrir_editor()` y el gancho `/estilo` a secas (`cli._estilo_editor`) | `cognia/ux/editor_app.py`, `cognia/cli.py` |
| P6b | caja de `panel.borde` (`glifo`: rounded/square/heavy/double/none) y textos de `panel.titulo` en los paneles de `/compactar`, `/modulos`, `/costo`, `/stats` (`cli._panel_chrome`; default byte-identico) | `cognia/cli.py`, `cognia/ux/aspecto.py` (seccion 17) |
| acento | `/color X` escribe `respuesta.texto.color` en el registro (`cli._acento_a_registro`) y `/estilo respuesta.texto color X` (o style string, o reset) mueve el acento en caliente y persiste `COGNIA_ACCENT` (`cli._acento_desde_registro`); un `COGNIA_ACCENT` heredado sin override no se pisa | `cognia/cli.py`, `cognia/ux/aspecto.py` (seccion 18) |

Tests: `tests/test_ux_aspecto.py`, `test_ux_glow`, `test_ux_spinner_vivo`,
`test_renderer_estetica`, `test_cli_banner_layout`, `test_harness_banner_adaptativo`,
`test_ux_editor_aspecto`, `test_ux_editor_app`, `test_cli_estilo`,
`test_harness_render_tools`, `test_marco_prompt` (el conteo del dia esta en
`MANAGER_LOG.md`, seccion "Sistema de estilos: ultima tanda P6 + P9").

**Pendiente REAL** (lo que `/estilo` avisa al guardar, `aspecto.paso_pendiente`):

| que | estado hoy |
|---|---|
| `agentes.acento/panel/borde/texto` (vista F2) | se validan, guardan y previsualizan; la vista F2 no lee el registro (`enganchado=False`) |
| migracion E11 en `cli.py` | quedan `[success_dim]` x4 y `[bold]` x6 literales fuera de los tokens del tema |
| `barra.*` animada, glow de `barra.estado`/`barra.modo`, animacion de `prompt.texto/continuacion/busqueda/seleccion` y `menu.*` | solo el pulso de P9 anima (etiqueta/marco/flecha/espera) |
| `sistema.*`, `aviso.info/error`, `tool.verbo/objeto`, `panel.cuerpo`: texto/glifo/glow/visible | solo color/negrita/italica por token |
| `/estilo banner` | avisa "llega con P7"; `cli._reimprimir_banner` existe y no esta cableado |
| `global.fps` / `global.respuesta_sangria` / `global.glifos` | se validan; el motor corre a `glow.FPS = 12` |
| P12 | no empezado |
| P13 (puerta final: sesion e2e con `/estilo`, presets, `/tema` x3, remoto y pipe; contraste de los 5 presets con `scripts/contraste_tema.py`) | las puertas ConPTY de banner/spinner/prompt/editor existen por separado |
