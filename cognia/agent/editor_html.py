# -*- coding: utf-8 -*-
"""
cognia/agent/editor_html.py
===========================
La PAGINA del editor visual de flujos: lienzo estilo n8n, paleta de nodos,
panel de propiedades, historial de versiones y chat con el modelo local.

POR QUE EXISTE (2026-08-29)
---------------------------
`flujoteca_view.py` ya pintaba un flujo, pero de SOLO LECTURA: se miraba y
se cerraba. Editar un flujo obligaba a escribir JSON a mano o a pedirselo al
modelo a ciegas. Este modulo es la mitad-cliente del editor: una plantilla
HTML autocontenida que habla con el servidor local
(`cognia/agent/flujoteca_editor.py`) por los endpoints `/api/*`.

Va separado del servidor por una razon practica: son ~1300 lineas de CSS, DOM
y JS que cambian por motivos de diseno, mientras que el servidor cambia por
motivos de seguridad y de contrato. Mezclarlos hace ilegibles los dos.

REGLAS DE COMPOSICION (cada una viene de un fallo ya pagado)
------------------------------------------------------------
  - `.replace()` sobre placeholders, NUNCA `str.format`: las llaves dobles
    de las expresiones `{{id}}` de los flujos revientan el formateo.
  - LOS CUATRO PLACEHOLDERS SE SUSTITUYEN DE UNA SOLA PASADA (un `re.sub`
    con los cuatro alternados), y el dato del dueno pasa antes por
    `_neutralizar_placeholders`. Encadenar `.replace()` deja que lo
    sustituido primero se reinterprete despues: con `__TITLE__` el primero,
    un flujo llamado literalmente `__TOKEN__` acababa con el token de sesion
    dentro del `<title>` -- o sea en el titulo de la pestana, el historial y
    los marcadores, PERSISTIDO EN DISCO. Reproducido en vivo el 2026-08-29
    (rev_seguridad, hallazgo 2). Con una sola pasada el orden deja de
    existir, que es lo unico que no se rompe cuando alguien anada el quinto
    placeholder.
  - Sin acentos graves de plantilla JS en NINGUNA parte, ni en la prosa ni en
    el codigo: un solo acento grave suelto se lleva el fichero. Todo el JS
    concatena con `+`.
  - Todo `json.dumps` que va dentro de un `<script>` escapa TODOS los `<`
    (y de paso `>` y `&`) como `\\u003c`, no solo el cierre `</`. Escapar el
    cierre de etiqueta NO basta: `<!--` y `<script` meten al tokenizador de
    HTML en `script data escaped` y en ese estado el `</script>` de la
    plantilla ya no cierra el bloque. Medido en Chromium el 2026-08-29
    (rev_seguridad, hallazgo 3): un `args` con `<!--<script>...` dejaba
    `typeof D === "undefined"`, cero nodos, sin chat y sin Guardar, pero con
    la barra pintada -- parece un flujo vacio, no una pagina rota.
  - `textContent` SIEMPRE, nunca `innerHTML` con dato del dueno (el unico
    `innerHTML` de la pagina escribe una entidad constante). A proposito NO
    hay una funcion `esc()` de escape de HTML: mientras el DOM se construya
    con `createElement`/`textContent` no hace falta ninguna, y tener una a
    mano invita a volver a construir HTML concatenando cadenas. Los `args`
    que se pintan son texto del dueno, y esto seria XSS local real aunque el
    origen sea 127.0.0.1.
  - CERO CDN: ni `<script src=...>` ni `<link href=http...>`. La pagina
    tiene que funcionar sin red. La unica cadena `http` de la plantilla es el
    namespace de SVG, y va partida en dos trozos para que ninguna
    comprobacion de "sin CDN" que busque el literal la confunda con una
    descarga (no hay red: es un identificador, no una URL que se visite).
    Es la UNICA excepcion legitima a esa comprobacion: cualquier otra cadena
    `http` partida en trozos es un CDN colandose, y hay que rechazarla.

EL FALLBACK ES PARTE DEL DISENO, NO UN EXTRA
--------------------------------------------
Si el `fetch` al servidor falla (CI, `COGNIA_REMOTO=1`, maquina sin
display, servidor ya apagado), la pagina NO se queda en blanco: entra en
solo-lectura con un banner honesto y los botones "Copiar JSON" / "Pegar
JSON", para que el flujo se pueda mover a mano con `/flujoteca importar`.
Por eso `render()` embebe los datos iniciales: el lienzo pinta ANTES del
primer fetch y no depende de el.

Y LA DEGRADACION ES REVERSIBLE (arreglado 2026-08-29)
-----------------------------------------------------
`degradar()` era una puerta de un solo sentido: `S.soloLectura` se ponia a
true y no volvia a false NUNCA. Un solo `POST /api/pos` fallido -- el del
debounce de 800 ms al mover un nodo, con el portatil suspendiendose o el
servidor reiniciandose -- dejaba la pestana en solo-lectura PERMANENTE, y
acto seguido `validarAhora()` volvia a acertar y el indicador decia
"conectado con Cognia" con todos los botones muertos y el banner puesto. La
unica salida era recargar, y la pagina no lo decia (rev_ciclo-de-vida,
hallazgo 3). Ahora `marcarOnline(true)` llama a `rearmar()`, y mientras esta
degradada la pagina se REPINGA sola con retroceso exponencial (2 s -> 30 s)
diciendo en el banner cuando lo va a reintentar. Nadie tiene que recargar.

LOS AVISOS DEL SERVIDOR SE PINTAN (arreglado 2026-08-29)
---------------------------------------------------------
El servidor emite `aviso` a proposito en dos sitios (catalogo caido, flujo
ilegible) y `_normalizar` lo tiraba a la basura con su whitelist cerrada; el
cliente tampoco lo miraba. Una familia opt-in con un import roto abria el
editor con la paleta vacia y CERO mensaje (rev_contratos, hallazgo 2): el
vacio silencioso que esta casa tiene nombrado como su fallo tipico. Ahora
`aviso` viaja en los dos niveles y se pinta en `#aviso`, un banner AMBAR
distinto del rojo de "sin conexion", cerrable, y que no deshabilita nada:
un aviso no es una caida.

LOS TIPOS DEL FLUJO SE SANEAN EN LA FRONTERA (arreglado 2026-08-29)
--------------------------------------------------------------------
Un `args` dict tumbaba el arranque ENTERO de la pagina: `(n.args || "")
.replace(...)` lanzaba `TypeError` en `pintarNodo` y `arrancar()` moria a
medias -- 1 de 4 nodos pintados, flechas al vacio, minimapa y barra de
versiones del flujo ANTERIOR y, al cambiar de flujo, un toast rojo que decia
"sin conexion con Cognia" (el `.catch` de `cargarFlujo` se tragaba el
TypeError y lo disfrazaba de caida de red). Medido en Chromium, y es el
gemelo exacto del bug de `flow_view.py:113` ya arreglado en Python. El flujo
llega de disco: ni `importar`, ni un JSON tecleado, ni un fichero viejo
prometen un tipo. Ahora `sanearFlujo()` corre en CADA frontera (datos
embebidos, `/api/flujo`, pegar JSON, respuesta del chat), `aTexto()` cubre
los puntos de pintado, y `pintar()`/`pintarNodos()`/`arrancar()` van con
`try/catch`: lo que se convierte SE DICE en el banner ambar y un nodo
imposible pierde su caja, no la pagina.

EL DOBLE CLIC SE CUENTA A MANO (arreglado 2026-08-29)
------------------------------------------------------
El atajo estaba en la hoja de ayuda y NUNCA funciono: sobre un nodo no
llegaba ni `click` ni `dblclick`. Dos causas independientes, las dos en el
`pointerdown` del lienzo -- `pintar()` reconstruia el nodo entre los dos
clics, y `setPointerCapture` redirigia el evento al `<svg>` (con
`e.target.closest(".nodo")` a null). La via que decide es contar los
`pointerdown` por id + tiempo + distancia, que no depende de ninguna de las
dos; el `dblclick` nativo se queda de refuerzo, resolviendo el nodo por
COORDENADA. Leccion general: un gesto que depende de que el DOM sobreviva al
repintado no es un gesto, es una coincidencia.

Y EL EDITOR NO VALIDA EN JS
---------------------------
Ni un ciclo, ni un wire colgado, ni una tool inexistente se deciden en el
navegador. Todo lo que se guarda pasa por `flows.validar()` en Python
(endpoint `/api/guardar`); `/api/validar` da la senal en vivo para
deshabilitar el boton Guardar y anclar el error al nodo culpable, pero la
verdad esta siempre en el servidor.

CONTRATO (copiado del plan, FASE 0 y PEDIDO 3)
----------------------------------------------
Firmas publicas:

    HTML: str                                    # plantilla con placeholders
    render(datos: dict, *, base: str, token: str) -> str

`base` es la URL del servidor (`http://127.0.0.1:<puerto>`, SIN barra final)
y `token` el de un solo arranque, que el cliente manda en la cabecera
`X-Cognia-Token` de cada fetch. Los dos se inyectan por `.replace()`.

LA FORMA EXACTA DE `datos` (esto es lo que el servidor tiene que servir)
------------------------------------------------------------------------
Es la respuesta de `GET /api/flujo` mas dos claves: `flujos` y `catalogo`.
TODAS las claves son opcionales: `render()` normaliza y la pagina pinta
igual con un dict vacio (asi un test puede llamar a `render({})`).

    {
      "ok": True,                       # ignorado por la pagina
      "nombre": "informe semanal",      # nombre del flujo abierto
      "descripcion": "...",             # una linea, opcional
      "version": 3,                     # version cargada (0 = sin guardar)
      "flujo": {                        # EL DAG, tal cual lo come flows.py
        "nombre": "informe semanal",
        "nodos": [
          {"id": "a", "tool": "leer_archivo", "args": "notas.md",
           "wires": ["b"],              # ids de los hijos
           "reintentos": 2,             # opcional, int
           "timeout_s": 30,             # opcional, float
           "saltar_si": "ERROR",        # opcional, str (subcadena)
           "modelo": "pensar-qwen38"}   # opcional, str
        ]
      },
      "ui": {"pos": {"a": {"x": 96, "y": 128}}},   # posiciones manuales
      "layout": {...},                  # salida de flow_view.build_layout;
                                        # opcional, solo respaldo si no hay pos
      "versiones": [                    # de la mas nueva a la mas vieja
        {"v": 3, "ts": "2026-08-29T10:00:00", "nota": "anado el informe",
         "n_nodos": 4, "actual": True, "existe": True}
      ],
      "flujos": [                       # = flujoteca.listar()
        {"nombre": "informe semanal", "slug": "informe-semanal",
         "descripcion": "...", "version_actual": 3, "n_versiones": 3,
         "n_nodos": 4, "modificado": "2026-08-29T10:00:00"}
      ],
      "catalogo": {                     # = catalogo_nodos.paleta() + catalogo()
        "categorias": [{"id": "lectura", "nombre": "Archivos: leer",
                        "color": "#3a42e9", "color_osc": "#898fff",
                        "icono": "file"}],
        "nodos": [{"nombre": "leer_archivo", "descripcion": "...",
                   "categoria": "lectura", "color": "#3a42e9",
                   "icono": "file", "danger": False, "familia": "",
                   "flag": "", "activa": True,
                   "params": [{"nombre": "ruta", "tipo": "string",
                               "requerido": True, "descripcion": "...",
                               "clave": False}]}]
      }
    }

Los `params` se usan para GENERAR el formulario del panel de propiedades y
para componer el string `args` con la convencion de `tools.armar_args`:
los posicionales (`clave` falso) se unen con " | " en orden, y los de clave
se anaden como `nombre=valor` (con " | " delante en `ejecutar`, cuyo parser
lo exige). El textarea de `args` crudo sigue estando y manda sobre el
formulario: el formulario es una ayuda, no una carcel.

Geometria copiada literal de n8n: rejilla 16, nodo 96x96 (256x96 el
"configurable", el que tiene 2 o mas hijos), radius 12, paso horizontal 224,
puerto 16 px, mas de 24 px con tallo de 46, arista `stroke-width: 2`, path
transparente de 40 px sobre cada arista e histeresis de 600 ms al salir del
hover (sin esos dos ultimos, la toolbar de la arista es inusable). Bezier con
tangentes horizontales; arista hacia atras en dos tramos con bajada de 130 px.
Arista discontinua `5,6` cuando el destino tiene `saltar_si`. Autosave de
posiciones con debounce de 800 ms. Tema claro y oscuro con `localStorage`.

Las tres FORMAS de nodo salen del GRAFO, no del catalogo (Cognia no tiene
tools disparadoras y seria deshonesto inventarlas): `trigger` = sin padres
(lado izquierdo redondeado a 36 y SIN puerto de entrada), `configurable` =
2 o mas hijos (256x96, icono a la izquierda), `default` = el resto.
"""
from __future__ import annotations

import html as _html
import json
import re as _re

__all__ = ["HTML", "render"]


# ---------------------------------------------------------------------------
# La plantilla. Cadena RAW: las barras invertidas de los regex de JS tienen
# que llegar al navegador tal cual.
# ---------------------------------------------------------------------------
HTML: str = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --lienzo:#eef0f3; --panel:#ffffff; --borde:#d0d7de; --texto:#1f2328;
  --texto2:#59636e; --acento:#0969da; --cable:#57606a; --nodo:#ffffff;
  --nodo-borde:#1f2328; --peligro:#cf222e; --ok:#1a7f37; --punto:#c6ccd4;
  --sombra:0 6px 20px rgba(31,35,40,.14); --aviso:#9a6700;
}
:root[data-tema="oscuro"]{
  --lienzo:#1c2128; --panel:#161b22; --borde:#30363d; --texto:#e6edf3;
  --texto2:#8b949e; --acento:#58a6ff; --cable:#8b949e; --nodo:#ffffff;
  --nodo-borde:#0d1117; --peligro:#ff7b72; --ok:#3fb950; --punto:#30363d;
  --sombra:0 6px 20px rgba(1,4,9,.55); --aviso:#d29922;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden}
body{background:var(--lienzo);color:var(--texto);display:flex;flex-direction:column;
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
button,input,select,textarea{font:inherit;color:inherit}
button{padding:5px 10px;background:var(--panel);border:1px solid var(--borde);
  border-radius:6px;cursor:pointer}
button:hover:not(:disabled){border-color:var(--acento)}
button:disabled{opacity:.45;cursor:not-allowed}
button.primario{background:var(--acento);border-color:var(--acento);color:#fff}
input,select,textarea{background:var(--panel);border:1px solid var(--borde);
  border-radius:6px;padding:5px 8px;width:100%}
textarea{resize:vertical;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
code{background:var(--lienzo);border:1px solid var(--borde);border-radius:4px;
  padding:0 4px;font-family:ui-monospace,Consolas,monospace;font-size:12px}
/* ---------- barra superior ---------- */
header{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--panel);
  border-bottom:1px solid var(--borde);flex-wrap:wrap;z-index:6}
header h1{font-size:15px;font-weight:600;margin:0 6px 0 0;white-space:nowrap}
header select{width:auto;max-width:220px}
header .sep{flex:1}
#estado{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--texto2);
  white-space:nowrap}
#punto-estado{width:9px;height:9px;border-radius:50%;background:var(--ok)}
#punto-estado.mal{background:var(--peligro)}
/* DOS banners y no uno: #banner es la CAIDA (rojo, la pagina esta en
   solo-lectura) y #aviso es un AVISO del servidor (ambar, se sigue
   editando). Pintar los dos igual hacia que "el catalogo no cargo" pareciera
   "te has quedado sin servidor". */
#banner{padding:8px 14px;background:var(--panel);border-bottom:1px solid var(--peligro);
  color:var(--peligro);font-size:13px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#aviso{padding:8px 14px;background:var(--panel);border-bottom:1px solid var(--aviso);
  color:var(--aviso);font-size:13px;display:flex;align-items:flex-start;gap:10px}
#aviso-txt{display:flex;flex-direction:column;gap:3px;min-width:0;word-break:break-word}
/* 'display:flex' GANA al 'display:none' que el navegador le da a [hidden]:
   sin esta linea los dos banners se ven como una franja vacia con su boton
   "cerrar" nada mas abrir la pagina. Cazado en Chromium, 2026-08-29. */
#banner[hidden],#aviso[hidden]{display:none}
#banner .sep,#aviso .sep{flex:1}
#banner button,#aviso button{font-size:12px;padding:2px 8px;white-space:nowrap}
/* ---------- estructura ---------- */
main{flex:1;display:flex;min-height:0}
aside{background:var(--panel);overflow-y:auto;flex-shrink:0}
#chat{width:290px;border-right:1px solid var(--borde);display:flex;flex-direction:column}
#centro{flex:1;display:flex;flex-direction:column;min-width:0}
#paleta{width:320px;border-left:1px solid var(--borde);display:none;flex-direction:column}
#props{width:340px;border-left:1px solid var(--borde);display:none;padding:12px 14px}
#paleta.abierto,#props.abierto{display:flex}
#props.abierto{display:block}
aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--texto2);
  margin:0 0 8px;font-weight:600;display:flex;align-items:center;gap:6px}
/* ---------- lienzo ---------- */
#lienzo{flex:1;position:relative;overflow:hidden;background:var(--lienzo)}
#svg{position:absolute;inset:0;width:100%;height:100%;touch-action:none;
  cursor:default;display:block}
#svg.panear{cursor:grab}
#svg.paneando{cursor:grabbing}
.caja{fill:var(--nodo);stroke:var(--nodo-borde);stroke-width:1.6}
.nodo.sel .caja{stroke:var(--acento);stroke-width:2.6}
.nodo{cursor:grab}
.nodo.saltado{opacity:.55}
.anillo{fill:none;stroke:var(--peligro);stroke-width:2;opacity:.42}
/* Los NODOS son claros en los dos temas (decision de flujoteca_view), asi que
   el texto DENTRO de la caja lleva color fijo oscuro: con var(--texto) se
   volvia blanco sobre blanco en tema oscuro. El texto de FUERA vive sobre el
   lienzo y si sigue al tema. */
.n-id{fill:#1f2328;font-size:12.5px;font-weight:600}
.n-tool{fill:#59636e;font-size:11px}
.n-arg{fill:#59636e;font-size:10.5px}
.n-id.fuera{fill:var(--texto)}
.n-tool.fuera,.n-arg.fuera{fill:var(--texto2)}
.puerto{fill:var(--nodo);stroke:var(--nodo-borde);stroke-width:1.4}
.puerto.salida{cursor:crosshair}
.puerto.salida:hover{fill:#f2f4f7;stroke-width:2}
.rombo{fill:var(--nodo);stroke:var(--nodo-borde);stroke-width:1.4}
.mas{cursor:pointer}
.mas rect{fill:#e5e5e5;stroke:#cfcfcf;stroke-width:1.5}
.mas path{stroke:#333;stroke-width:1.6;fill:none;stroke-linecap:round}
.mas line{stroke:var(--cable);stroke-width:2}
.mas:hover rect{fill:#d7dbe0}
.arista{stroke:var(--cable);stroke-width:2;fill:none;stroke-linecap:square}
.arista.corta{stroke-dasharray:5 6}
.arista.viva{stroke:var(--acento)}
.golpe{stroke:transparent;stroke-width:40;fill:none;pointer-events:stroke;cursor:pointer}
.fantasma{stroke:var(--acento);stroke-width:2;fill:none;stroke-dasharray:4 5}
#marquee{fill:rgba(9,105,218,.10);stroke:var(--acento);stroke-width:1;stroke-dasharray:4 3}
.badge circle,.badge rect{fill:var(--nodo);stroke:var(--nodo-borde);stroke-width:1.2}
.badge text{fill:#1f2328;font-size:9.5px;font-weight:700}
.badge path{stroke:#1f2328;stroke-width:1.4;fill:none;stroke-linecap:round}
.err-nodo{fill:var(--peligro);font-size:11px;font-weight:600}
/* ---------- flotantes del lienzo ---------- */
#zoombar{position:absolute;left:12px;bottom:12px;display:flex;gap:5px;
  background:var(--panel);border:1px solid var(--borde);border-radius:8px;padding:4px;
  box-shadow:var(--sombra)}
#zoombar button{padding:3px 8px}
#nivel-zoom{font-size:12px;color:var(--texto2);align-self:center;padding:0 4px;min-width:44px;
  text-align:center}
#mini{position:absolute;right:12px;bottom:12px;background:var(--panel);
  border:1px solid var(--borde);border-radius:8px;box-shadow:var(--sombra);cursor:pointer}
#tb-arista{position:absolute;display:none;gap:6px;background:var(--panel);
  border:1px solid var(--borde);border-radius:8px;padding:5px;box-shadow:var(--sombra);
  transform:translate(-50%,-50%);z-index:4}
#tb-arista.visible{display:flex}
#tb-arista button{padding:2px 8px;font-size:13px}
#toast{position:absolute;left:50%;bottom:56px;transform:translateX(-50%);background:var(--panel);
  border:1px solid var(--borde);border-radius:8px;padding:7px 13px;box-shadow:var(--sombra);
  display:none;max-width:70%;font-size:13px;z-index:5}
#toast.visible{display:block}
#toast.malo{border-color:var(--peligro);color:var(--peligro)}
/* ---------- linea de tiempo ---------- */
#tiempo{border-top:1px solid var(--borde);background:var(--panel);padding:7px 12px;
  display:flex;align-items:center;gap:8px;overflow-x:auto;white-space:nowrap;min-height:44px}
#tiempo .et{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--texto2);
  font-weight:600;margin-right:4px}
.vchip{border:1px solid var(--borde);border-radius:16px;padding:2px 10px;font-size:12px;
  cursor:pointer;background:var(--panel);display:inline-flex;gap:6px;align-items:center}
.vchip:hover{border-color:var(--acento)}
.vchip[aria-current="true"]{border-color:var(--acento);color:var(--acento);font-weight:600}
.vchip.borrada{opacity:.5;text-decoration:line-through}
.vchip .n{color:var(--texto2);font-size:11px}
#mirando{color:var(--aviso);font-size:12px;display:none;gap:6px;align-items:center}
#mirando.visible{display:inline-flex}
/* ---------- chat ---------- */
#chat header{border:0;background:transparent;padding:10px 12px 4px}
#hist{flex:1;overflow-y:auto;padding:6px 12px;display:flex;flex-direction:column;gap:8px}
.msg{border:1px solid var(--borde);border-radius:9px;padding:7px 10px;font-size:13px;
  white-space:pre-wrap;word-break:break-word}
.msg.yo{background:var(--lienzo)}
.msg.mal{border-color:var(--peligro);color:var(--peligro)}
.msg .meta{font-size:11px;color:var(--texto2);margin-top:4px}
#sugerencias{display:flex;flex-direction:column;gap:5px;padding:0 12px 6px}
#sugerencias button{text-align:left;font-size:12px;color:var(--texto2)}
#caja-chat{padding:8px 12px 12px;border-top:1px solid var(--borde);display:flex;
  flex-direction:column;gap:6px}
#pensando{display:none;font-size:12px;color:var(--texto2);align-items:center;gap:7px}
#pensando.visible{display:flex}
.girando{width:11px;height:11px;border:2px solid var(--borde);border-top-color:var(--acento);
  border-radius:50%;animation:giro .8s linear infinite}
@keyframes giro{to{transform:rotate(360deg)}}
/* ---------- paleta ---------- */
#paleta .cuerpo{overflow-y:auto;overflow-x:hidden;flex:1;padding:0 10px 12px}
/* width:100% + margin desborda (box-sizing no cuenta el margen): sin el
   calc, el panel entero se queda con una barra horizontal. */
#buscador{margin:10px;width:calc(100% - 20px)}
.cat{margin-top:8px}
.cat > .cab{display:flex;align-items:center;gap:7px;cursor:pointer;padding:5px 4px;
  border-radius:6px;font-weight:600;font-size:13px}
.cat > .cab:hover{background:var(--lienzo)}
.cat .flecha{color:var(--texto2);font-size:10px;width:10px}
.pt{display:flex;gap:9px;align-items:flex-start;padding:6px 4px 6px 8px;border-radius:6px;
  cursor:grab}
.pt:hover{background:var(--lienzo)}
.pt > div{min-width:0}
.pt .tit{font-size:13px;font-weight:500;word-break:break-word}
.pt .des{font-size:11.5px;color:var(--texto2);line-height:1.35;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pt.apagada{opacity:.5}
/* Cajon de una familia APAGADA: se pinta plegado y atenuado con el comando
   que lo enciende. Un cajon vacio y mudo no dice que te estas perdiendo 26
   herramientas; este si. */
.cat.apagada{opacity:.6}
.cat.apagada > .cab{cursor:default;font-weight:500}
.cat.apagada > .cab:hover{background:transparent}
.cat .comoencender{font-size:11.5px;color:var(--texto2);line-height:1.35;
  padding:0 4px 4px 26px;word-break:break-word}
.pill{font-size:9.5px;border:1px solid var(--borde);border-radius:10px;padding:0 5px;
  color:var(--texto2);margin-left:5px}
.pill.peligro{border-color:var(--peligro);color:var(--peligro)}
.ico{flex:0 0 22px;height:22px;margin-top:1px}
/* ---------- propiedades ---------- */
#props .campo{margin-bottom:9px}
#props label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--texto2);margin-bottom:3px}
#props .ayuda{font-size:11.5px;color:var(--texto2);margin:-1px 0 7px}
#props .tres{display:flex;gap:7px}
#props .tres > div{flex:1}
.chip-w{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--borde);
  border-radius:14px;padding:1px 4px 1px 9px;font-size:12px;margin:0 5px 5px 0}
.chip-w button{border:0;background:transparent;padding:0 4px;color:var(--texto2)}
#props .bloque{border-top:1px solid var(--borde);margin-top:12px;padding-top:10px}
#props .interp{font-size:11.5px;color:var(--texto2)}
#props .interp button{padding:1px 6px;font-size:11px;margin:2px 4px 0 0}
#err-props{color:var(--peligro);font-size:12.5px;margin-bottom:8px;display:none}
#err-props.visible{display:block}
/* ---------- modales ---------- */
.velo{position:fixed;inset:0;background:rgba(0,0,0,.35);display:none;align-items:center;
  justify-content:center;z-index:20}
.velo.visible{display:flex}
.modal{background:var(--panel);border:1px solid var(--borde);border-radius:12px;padding:16px;
  width:min(620px,92vw);max-height:86vh;overflow:auto;box-shadow:var(--sombra)}
.modal h3{margin:0 0 10px;font-size:15px}
.modal .fila{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
#hoja table{border-collapse:collapse;width:100%;font-size:13px}
#hoja td{padding:3px 8px 3px 0;vertical-align:top}
#hoja td:first-child{white-space:nowrap;color:var(--texto2);width:150px}
#hoja h4{margin:12px 0 4px;font-size:12px;text-transform:uppercase;color:var(--texto2);
  letter-spacing:.05em}
</style></head><body>
<header>
  <h1 id="titulo"></h1>
  <select id="sel-flujo" title="Cambiar de flujo"></select>
  <button id="b-guardar" class="primario" title="Ctrl+S">Guardar</button>
  <button id="b-validar" title="Preguntar al servidor si el grafo es valido">Validar</button>
  <button id="b-copiar" title="Copiar el JSON del flujo al portapapeles">Copiar JSON</button>
  <button id="b-pegar" title="Pegar un JSON de flujo">Pegar JSON</button>
  <span class="sep"></span>
  <span id="estado"><span id="punto-estado"></span><span id="estado-txt">conectando</span></span>
  <button id="b-tema" title="Claro / oscuro">&#9789;</button>
  <button id="b-ayuda" title="Atajos de teclado">?</button>
</header>
<div id="banner" hidden></div>
<div id="aviso" hidden><div id="aviso-txt"></div><span class="sep"></span>
  <button id="b-aviso-x" title="Ocultar este aviso">cerrar</button></div>
<main>
  <aside id="chat">
    <header><h2>Chat del flujo</h2></header>
    <div id="hist"></div>
    <div id="sugerencias"></div>
    <div id="caja-chat">
      <div id="pensando"><span class="girando"></span><span id="pensando-txt"></span></div>
      <textarea id="msg" rows="3" placeholder="Pide un cambio: anade un paso que escriba el resultado en informe.md"></textarea>
      <button id="b-enviar" class="primario">Enviar al modelo</button>
    </div>
  </aside>
  <div id="centro">
    <div id="lienzo">
      <svg id="svg"></svg>
      <div id="tb-arista">
        <button id="b-arista-borrar" title="Borrar esta conexion">&#128465;</button>
        <button id="b-arista-mas" title="Insertar un nodo en medio">+</button>
      </div>
      <div id="zoombar">
        <button id="b-menos" title="Alejar">&minus;</button>
        <span id="nivel-zoom">100%</span>
        <button id="b-mas" title="Acercar">+</button>
        <button id="b-ajustar" title="Ajustar (0)">&#9974;</button>
        <button id="b-nodos" title="Panel de nodos (Tab)">Nodos</button>
      </div>
      <svg id="mini" width="190" height="120"></svg>
      <div id="toast"></div>
    </div>
    <div id="tiempo">
      <span class="et">Versiones</span>
      <span id="chips-v"></span>
      <span id="mirando"><span>viendo una version antigua</span>
        <button id="b-restaurar">Restaurar</button>
        <button id="b-volver">Volver a la actual</button></span>
    </div>
  </div>
  <aside id="paleta">
    <input id="buscador" type="search" placeholder="Buscar nodo (Tab abre y cierra)" autocomplete="off">
    <div class="cuerpo" id="lista-paleta"></div>
  </aside>
  <aside id="props"></aside>
</main>

<div class="velo" id="velo-guardar"><div class="modal">
  <h3>Guardar una version nueva</h3>
  <div class="campo"><label for="nota">Nota (opcional)</label>
    <input id="nota" placeholder="que cambia esta version"></div>
  <div class="fila"><button data-cerrar="velo-guardar">Cancelar</button>
    <button id="b-guardar-ok" class="primario">Guardar</button></div>
</div></div>

<div class="velo" id="velo-pegar"><div class="modal">
  <h3>Pegar el JSON de un flujo</h3>
  <p class="interp">Se acepta el flujo entero (con nombre y nodos) o solo la lista de nodos.
     Nada se escribe en disco hasta que pulses Guardar.</p>
  <textarea id="json-pegar" rows="14"></textarea>
  <div class="fila"><button data-cerrar="velo-pegar">Cancelar</button>
    <button id="b-pegar-ok" class="primario">Cargar en el lienzo</button></div>
</div></div>

<div class="velo" id="velo-copiar"><div class="modal">
  <h3>JSON del flujo</h3>
  <textarea id="json-copiar" rows="16"></textarea>
  <div class="fila"><button data-cerrar="velo-copiar">Cerrar</button></div>
</div></div>

<div class="velo" id="velo-hoja"><div class="modal" id="hoja">
  <h3>Atajos de teclado</h3>
  <div id="hoja-cuerpo"></div>
  <div class="fila"><button data-cerrar="velo-hoja">Cerrar</button></div>
</div></div>

<script>
"use strict";
/* =========================================================================
   DATOS Y CONSTANTES
   ========================================================================= */
var D = __DATA__;
var BASE = "__BASE__";
var TOKEN = "__TOKEN__";

/* El namespace de SVG. Va partido para que ninguna comprobacion de "sin CDN"
   que busque el literal http lo tome por una descarga: aqui no hay red.
   ESTA LINEA ES LA UNICA EXCEPCION LEGITIMA a la regla de cero descargas
   externas, y es justo lo que vuelve evadible un test que solo busque el
   literal pegado (rev_contratos, 2026-08-29: "ojo, eso vuelve trivialmente
   evadible test_render_sin_cdn si manana alguien mete una descarga igual de
   partida"). Regla para quien revise este fichero: si aparece una SEGUNDA
   cadena de protocolo partida en trozos, no es un namespace, es una
   descarga colandose -- rechazala. */
var NS = "http:" + "//www.w3.org/2000/svg";

var REJILLA = 16, NW = 96, NH = 96, NW_CONF = 256, PASO_X = 224, PASO_Y = 168;
var PUERTO = 8, TALLO = 46, MAS = 24, BAJADA = 130, HISTERESIS = 600;
var TOPE_UNDO = 60, DEBOUNCE_POS = 800, DEBOUNCE_VAL = 600;
/* Retroceso del reintento automatico cuando la pagina esta degradada. El
   tope de 30 s existe para no machacar un servidor que se esta reiniciando
   ni dejar la pestana pidiendo para siempre cada 2 s. */
var REINTENTO_MIN = 2000, REINTENTO_MAX = 30000;
/* Ventana del doble clic detectado a mano (ver el pointerdown del lienzo).
   450 ms es lo que usan de facto los escritorios; los 6 px de tolerancia
   dejan pasar el temblor de la mano sin confundir un arrastre corto con un
   doble clic. */
var DOBLE_MS = 450, DOBLE_PX = 6;

/* Los 14 iconos, dibujados a mano en una caja de 24x24. Trazo, no relleno:
   asi el color de la categoria se aplica con stroke=currentColor y el nodo
   se queda neutro (regla de n8n: el color va SOLO en el icono).
   TIENE QUE ESTAR AQUI TODO `icono` de catalogo_nodos.CATEGORIAS: `icono()`
   cae a `ICONOS.box` con cualquier nombre que no conozca, o sea que un cajon
   con un icono que falte se ve EXACTAMENTE igual que "Otros" y sin un solo
   error en consola. Asi llevaban `pantalla` ("monitor") y `escena` ("cube")
   desde que se escribio la tabla; lo cazo
   tests/test_catalogo_nodos.py::test_todo_icono_de_la_tabla_lo_sabe_dibujar_editor_html. */
var ICONOS = {
  file: ["M6 2h7l5 5v15H6z", "M13 2v5h5"],
  pen: ["M4 20l1-4L16 5l3 3L8 19z", "M14 7l3 3"],
  code: ["M9 7l-5 5 5 5", "M15 7l5 5-5 5"],
  terminal: ["M3 4h18v16H3z", "M7 9l3 3-3 3", "M13 15h5"],
  globe: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M3 12h18",
          "M12 3c3 3 3 15 0 18", "M12 3c-3 3-3 15 0 18"],
  brain: ["M12 5a3 3 0 0 0-5 2 3 3 0 0 0-1 5 3 3 0 0 0 2 5 3 3 0 0 0 4 2z",
          "M12 5a3 3 0 0 1 5 2 3 3 0 0 1 1 5 3 3 0 0 1-2 5 3 3 0 0 1-4 2z",
          "M12 5v14"],
  sparkles: ["M11 3l1.7 4.3L17 9l-4.3 1.7L11 15l-1.7-4.3L5 9l4.3-1.7z",
             "M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z"],
  layers: ["M12 3l9 5-9 5-9-5z", "M3 13l9 5 9-5", "M3 17l9 5 9-5"],
  image: ["M3 5h18v14H3z", "M8 11a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2z",
          "M4 17l5-5 4 4 3-3 4 4"],
  monitor: ["M3 4h18v12H3z", "M9 20h6", "M12 16v4"],
  cube: ["M4 8h12v12H4z", "M8 4h12v12", "M4 8l4-4", "M16 8l4-4", "M16 20l4-4"],
  book: ["M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z", "M8 20a3 3 0 0 1 0-6h10"],
  tool: ["M20 4a4.2 4.2 0 0 1-5.4 5.4L6 18l-2-2 8.6-8.6A4.2 4.2 0 0 1 18 2z"],
  box: ["M12 3l9 5v8l-9 5-9-5V8z", "M3 8l9 5 9-5", "M12 13v10"]
};

var SUGERENCIAS = [
  "anade un paso que escriba el resultado en informe.md",
  "mete una busqueda web antes de resumir",
  "hazlo reintentable"
];

var ATAJOS = [
  ["Grafo", [
    ["Supr / Retroceso", "borrar los nodos seleccionados (o la arista bajo el raton)"],
    ["Ctrl + C / Ctrl + V", "copiar y pegar nodos (los ids repetidos se renumeran)"],
    ["Ctrl + Z / Ctrl + Y", "deshacer y rehacer (Ctrl+Shift+Z tambien rehace)"],
    ["Ctrl + A", "seleccionar todos los nodos"],
    ["F2", "renombrar el id del nodo seleccionado"],
    ["D", "deshabilitar el nodo: le pone saltar_si"],
    ["Doble clic", "abrir el panel de propiedades"]]],
  ["Lienzo", [
    ["Rueda", "zoom hacia el cursor (Ctrl + rueda tambien)"],
    ["Espacio + arrastrar", "mover el lienzo (tambien Ctrl + arrastrar, o el boton central)"],
    ["Arrastrar en vacio", "rectangulo de seleccion (con Shift, suma a lo ya elegido)"],
    ["0", "ajustar el zoom a todo el flujo"],
    ["1", "zoom al 100%"],
    ["+ / -", "acercar y alejar"]]],
  ["Paneles", [
    ["Tab", "abrir y cerrar el panel de nodos"],
    ["Escape", "cerrar los paneles y cancelar lo que se este arrastrando"],
    ["Ctrl + S", "guardar una version nueva"],
    ["?", "esta hoja"]]]
];

/* =========================================================================
   ESTADO
   ========================================================================= */
var S = {
  nombre: D.nombre || "", descripcion: D.descripcion || "",
  version: D.version || 0,
  flujo: D.flujo || {nombre: "", nodos: []},
  pos: (D.ui && D.ui.pos) || {},
  versiones: D.versiones || [], flujos: D.flujos || [],
  cat: D.catalogo || {categorias: [], nodos: []},
  sel: {}, tx: 40, ty: 40, k: 1,
  arrastre: null, panea: null, marquee: null, conectando: null,
  espacio: false, aristaViva: null, aristaTimer: null,
  pendiente: null, propsId: null, mirandoV: null,
  undo: [], redo: [], online: BASE ? null : false, soloLectura: false,
  errValidar: "", errNodo: "", tPos: null, tVal: null, tToast: null,
  portapapeles: [], reloj: null,
  /* El doble clic se cuenta a mano: ultimo pointerdown sobre un nodo, y
     cuando se abrio el panel por ultima vez (para no abrirlo dos veces si
     el 'dblclick' nativo tambien llega). */
  ultimoDown: null, tProps: 0
};

/* =========================================================================
   UTILIDADES
   ========================================================================= */
function $(s){ return document.querySelector(s); }
/* AQUI VIVIA esc(). Se BORRO el 2026-08-29: estaba definida y no la llamaba
   NADIE en las 2.354 lineas (rev_seguridad, negativo verificado). No se
   "cablea donde toque" porque no toca en ningun sitio: todo el DOM de esta
   pagina se construye con createElement/createElementNS + textContent +
   setAttribute con claves fijas, y ahi escapar a mano seria escapar dos
   veces (se veria "&amp;" literal en la tarjeta de un nodo). El unico
   innerHTML de la pagina escribe una entidad constante para el icono del
   tema. Dejarla habria sido peor que no tenerla: una funcion de escape a
   mano es la invitacion a volver a construir HTML concatenando cadenas, que
   es exactamente el bug que esta pagina no tiene. Si alguna vez hace falta
   HTML de verdad, el arreglo es un createElement mas, no resucitar esto. */
function el(n, a){
  var e = document.createElementNS(NS, n);
  for(var k in a) if(a[k] !== null && a[k] !== undefined) e.setAttribute(k, a[k]);
  return e;
}
function div(clase, texto){
  var d = document.createElement("div");
  if(clase) d.className = clase;
  if(texto !== undefined) d.textContent = texto;
  return d;
}
function snap(v){ return Math.round(v / REJILLA) * REJILLA; }
function clonar(o){ return JSON.parse(JSON.stringify(o)); }
function toast(txt, malo){
  var t = $("#toast");
  t.textContent = txt;
  t.className = "visible" + (malo ? " malo" : "");
  if(S.tToast) clearTimeout(S.tToast);
  S.tToast = setTimeout(function(){ t.className = ""; }, malo ? 6000 : 3200);
}
/* --------- LOS TIPOS DEL JSON DE DISCO NO ESTAN GARANTIZADOS -------------
   Un flujo puede venir de un fichero tecleado a mano, de /flujoteca
   importar, de una version vieja o del modelo: NADA promete el tipo de sus
   campos. El 2026-08-29 un args dict tumbo el arranque ENTERO de la
   pagina: (n.args || "").replace(...) lanzaba TypeError dentro de
   pintarNodo y arrancar() moria a medias -- 1 de 2 nodos pintados, la
   flecha al vacio, el minimapa en blanco, la barra de versiones vacia y el
   indicador clavado en "conectando" PARA SIEMPRE, sin banner ni aviso. Es el
   gemelo en JS del bug de flow_view.py:113 que ya se arreglo en Python, y
   es el vacio silencioso que esta casa tiene fichado: "roto" y "vacio" se
   veian igual.

   La defensa va en TRES capas y las tres hacen falta, porque cada una cae
   por un motivo distinto:
     1. sanearFlujo() en CADA FRONTERA por donde entra un flujo (datos
        embebidos, /api/flujo, pegar JSON, respuesta del chat): deja los
        tipos canonicos y DICE EN AMBAR lo que tuvo que convertir. Convertir
        en silencio seria cambiarle el dato al dueno a escondidas.
     2. aTexto()/aLista() en los puntos de pintado: cubren la quinta
        frontera que alguien anada sin acordarse de la capa 1.
     3. try/catch por nodo en pintarNodos y alrededor de pintar() y del
        arranque: un nodo raro pierde SU caja, no la pagina.

   aTexto usa JSON.stringify para un dict a proposito: "[object Object]"
   esconde el dato del dueno y {"ruta":"x"} se lo ensena. */
function aTexto(v){
  if(v === null || v === undefined) return "";
  if(typeof v === "string") return v;
  if(typeof v === "number" || typeof v === "boolean") return String(v);
  try{ var s = JSON.stringify(v); return s === undefined ? String(v) : s; }
  catch(e){ return String(v); }
}
function aLista(v){
  if(Array.isArray(v)) return v;
  if(v === null || v === undefined || v === "") return [];
  return [v];
}
function aNumero(v){
  var n = typeof v === "number" ? v : parseFloat(aTexto(v));
  return isFinite(n) ? n : 0;
}
function tipoDe(v){
  if(v === null) return "null";
  if(Array.isArray(v)) return "lista";
  return typeof v === "object" ? "dict" : typeof v;
}
/* Deja flujo con tipos canonicos y devuelve TAMBIEN la lista de lo que
   toco, para poder decirlo. No borra informacion: lo que no es del tipo
   esperado se CONVIERTE (el dueno lo ve en el nodo y en el panel), y lo
   unico que se descarta es un "nodo" que ni siquiera es un objeto, porque
   no hay nada que pintar de el. */
function normalizarFlujo(flujo){
  var f = (flujo && typeof flujo === "object" && !Array.isArray(flujo)) ? flujo
        : (Array.isArray(flujo) ? {nodos: flujo} : {});
  var ns = Array.isArray(f.nodos) ? f.nodos : [];
  var buenos = [], avisos = [], vistos = {}, i, j, n, v;
  if(!Array.isArray(f.nodos) && f.nodos !== undefined && f.nodos !== null)
    avisos.push("'nodos' era " + tipoDe(f.nodos) + " y no una lista");
  for(i = 0; i < ns.length; i++){
    n = ns[i];
    if(!n || typeof n !== "object" || Array.isArray(n)){
      avisos.push("el nodo #" + (i + 1) + " era " + tipoDe(n) + ", no un objeto: descartado");
      continue;
    }
    if(typeof n.id !== "string" || !n.id){
      v = aTexto(n.id) || ("nodo_" + (i + 1));
      avisos.push("un nodo tenia id " + tipoDe(n.id) + ": ahora es \"" + v + "\"");
      n.id = v;
    }
    if(typeof n.tool !== "string"){
      avisos.push("nodo \"" + n.id + "\": tool era " + tipoDe(n.tool) + ", convertido a texto");
      n.tool = aTexto(n.tool);
    }
    if(n.args === undefined || n.args === null){
      n.args = "";
    }else if(typeof n.args !== "string"){
      avisos.push("nodo \"" + n.id + "\": args era " + tipoDe(n.args) + ", convertido a texto");
      n.args = aTexto(n.args);
    }
    if(!Array.isArray(n.wires)){
      if(n.wires !== undefined && n.wires !== null)
        avisos.push("nodo \"" + n.id + "\": wires era " + tipoDe(n.wires) + ", convertido a lista");
      n.wires = aLista(n.wires);
    }
    for(j = 0; j < n.wires.length; j++)
      if(typeof n.wires[j] !== "string") n.wires[j] = aTexto(n.wires[j]);
    if(n.saltar_si !== undefined && n.saltar_si !== null && typeof n.saltar_si !== "string"){
      avisos.push("nodo \"" + n.id + "\": saltar_si era " + tipoDe(n.saltar_si) + ", convertido a texto");
      n.saltar_si = aTexto(n.saltar_si);
    }
    if(n.reintentos !== undefined && n.reintentos !== null && typeof n.reintentos !== "number"){
      avisos.push("nodo \"" + n.id + "\": reintentos era " + tipoDe(n.reintentos) + ", convertido a numero");
      n.reintentos = aNumero(n.reintentos);
    }
    if(n.timeout_s !== undefined && n.timeout_s !== null && typeof n.timeout_s !== "number"){
      avisos.push("nodo \"" + n.id + "\": timeout_s era " + tipoDe(n.timeout_s) + ", convertido a numero");
      n.timeout_s = aNumero(n.timeout_s);
    }
    if(n.modelo !== undefined && n.modelo !== null && typeof n.modelo !== "string")
      n.modelo = aTexto(n.modelo);
    /* Un id repetido NO se renombra (renombrar cambia el grafo del dueno sin
       que lo pida), pero se dice: nodoPorId devuelve siempre el primero, o
       sea que el segundo se veria pero no se podria editar. */
    if(vistos[n.id]) avisos.push("el id \"" + n.id + "\" esta repetido: solo se puede editar el primero");
    vistos[n.id] = 1;
    buenos.push(n);
  }
  return {nombre: aTexto(f.nombre), nodos: buenos, avisos: avisos};
}
/* La frontera. fuente es de donde vino el flujo, para que el aviso ambar
   diga a quien reclamar. */
function sanearFlujo(fuente){
  var r = normalizarFlujo(S.flujo);
  S.flujo = {nombre: r.nombre || S.nombre || "", nodos: r.nodos};
  if(r.avisos.length)
    avisar("este flujo traia campos con un tipo raro y se han convertido para poder " +
           "editarlo (en disco siguen como estaban hasta que guardes una version): " +
           r.avisos.join("; "), fuente);
  return r.avisos.length;
}
function nodos(){ return S.flujo.nodos || []; }
function nodoPorId(id){
  var ns = nodos();
  for(var i = 0; i < ns.length; i++) if(ns[i].id === id) return ns[i];
  return null;
}
function idsSel(){ return Object.keys(S.sel); }
function enCampo(){
  var a = document.activeElement;
  if(!a) return false;
  var t = (a.tagName || "").toLowerCase();
  return t === "input" || t === "textarea" || t === "select" || a.isContentEditable;
}
function icono(nombre, color, tam){
  var g = el("g", {});
  var d = ICONOS[nombre] || ICONOS.box;
  var s = (tam || 24) / 24;
  var w = el("g", {transform: "scale(" + s.toFixed(3) + ")", stroke: color || "#57606a",
                   fill: "none", "stroke-width": 1.8, "stroke-linecap": "round",
                   "stroke-linejoin": "round"});
  for(var i = 0; i < d.length; i++) w.appendChild(el("path", {d: d[i]}));
  g.appendChild(w);
  return g;
}

/* --------- catalogo: ficha de una tool, color segun el tema --------- */
var _porNombre = null, _porCat = null;
function indexar(){
  _porNombre = {}; _porCat = {};
  var ns = (S.cat && S.cat.nodos) || [], cs = (S.cat && S.cat.categorias) || [], i;
  for(i = 0; i < ns.length; i++) _porNombre[ns[i].nombre] = ns[i];
  for(i = 0; i < cs.length; i++) _porCat[cs[i].id] = cs[i];
}
function ficha(tool){
  if(!_porNombre) indexar();
  return _porNombre[tool] || null;
}
function colorDe(tool){
  var f = ficha(tool);
  if(!_porCat) indexar();
  var c = f ? _porCat[f.categoria] : null;
  var osc = document.documentElement.getAttribute("data-tema") === "oscuro";
  if(c) return (osc ? (c.color_osc || c.color) : c.color) || "#7d7d87";
  return (f && f.color) || "#7d7d87";
}
function iconoDe(tool){
  var f = ficha(tool);
  if(f && f.icono) return f.icono;
  if(!_porCat) indexar();
  var c = f ? _porCat[f.categoria] : null;
  return (c && c.icono) || "box";
}
function paramsDe(tool){
  var f = ficha(tool);
  return (f && f.params) || [];
}

/* =========================================================================
   TOPOLOGIA Y POSICIONES
   ========================================================================= */
function padresDe(){
  var p = {}, ns = nodos(), i, j;
  for(i = 0; i < ns.length; i++) p[ns[i].id] = [];
  for(i = 0; i < ns.length; i++){
    var ws = ns[i].wires || [];
    for(j = 0; j < ws.length; j++) if(p[ws[j]]) p[ws[j]].push(ns[i].id);
  }
  return p;
}
function forma(n, padres){
  if(!(padres[n.id] || []).length) return "trigger";
  if((n.wires || []).length >= 2) return "configurable";
  return "default";
}
function anchoDe(n, padres){ return forma(n, padres) === "configurable" ? NW_CONF : NW; }

/* Posiciones que faltan: columnas por profundidad topologica, igual que
   flow_view.build_layout. Las manuales de meta["ui"]["pos"] siempre ganan. */
function completarPos(){
  var ns = nodos(), padres = padresDe(), nivel = {}, i;
  function prof(id, visto){
    if(nivel[id] !== undefined) return nivel[id];
    visto = visto || {};
    if(visto[id]) return 0;
    visto[id] = 1;
    var p = padres[id] || [], m = 0;
    for(var j = 0; j < p.length; j++) m = Math.max(m, 1 + prof(p[j], visto));
    nivel[id] = p.length ? m : 0;
    return nivel[id];
  }
  for(i = 0; i < ns.length; i++) prof(ns[i].id);
  /* El ancho de la columna es el del nodo MAS ANCHO que cae en ella: un
     nodo configurable mide 256 y con un paso fijo de 224 se comeria la
     columna siguiente (y sus aristas se dibujarian como si fueran hacia
     atras, con el lazo por debajo). */
  var anchoCol = {}, maxCol = 0;
  for(i = 0; i < ns.length; i++){
    var c0 = nivel[ns[i].id] || 0;
    anchoCol[c0] = Math.max(anchoCol[c0] || NW, anchoDe(ns[i], padres));
    maxCol = Math.max(maxCol, c0);
  }
  var xCol = {}, acum = 40;
  for(i = 0; i <= maxCol; i++){
    xCol[i] = snap(acum);
    acum += (anchoCol[i] || NW) + (PASO_X - NW);
  }
  /* La FILA se hereda del primer padre mas el indice de hermano: asi dos
     hijos del mismo nodo se apilan en vez de quedar en la misma linea, que
     es lo que hacia pasar una arista por DEBAJO de otro nodo. */
  var ocupado = {};
  function libre(c, y){
    var lista = ocupado[c] || (ocupado[c] = []);
    var choca = true;
    while(choca){
      choca = false;
      for(var j = 0; j < lista.length; j++){
        if(Math.abs(lista[j] - y) < PASO_Y - 24){ y += PASO_Y; choca = true; break; }
      }
    }
    lista.push(y);
    return y;
  }
  var orden = ns.slice().sort(function(a, b){
    return (nivel[a.id] || 0) - (nivel[b.id] || 0);
  });
  for(i = 0; i < orden.length; i++){
    var id = orden[i].id, c = nivel[id] || 0;
    if(S.pos[id] && typeof S.pos[id].x === "number"){
      (ocupado[c] = ocupado[c] || []).push(S.pos[id].y);
      continue;
    }
    var p0 = (padres[id] || [])[0], y = 48;
    if(p0 && S.pos[p0]){
      var padre = nodoPorId(p0);
      var idx = padre ? (padre.wires || []).indexOf(id) : 0;
      y = S.pos[p0].y + Math.max(0, idx) * PASO_Y;
    }
    S.pos[id] = {x: xCol[c], y: snap(libre(c, y))};
  }
}
function posDe(id){
  var p = S.pos[id];
  if(p && typeof p.x === "number") return p;
  S.pos[id] = {x: 40, y: 48};
  return S.pos[id];
}

/* =========================================================================
   VISTA: PAN, ZOOM, REJILLA
   ========================================================================= */
var svg = $("#svg"), vista, gAristas, gNodos, gExtra, patron, fondo;
function montarSvg(){
  svg.textContent = "";
  var defs = el("defs", {});
  patron = el("pattern", {id: "puntos", patternUnits: "userSpaceOnUse",
                          width: REJILLA, height: REJILLA});
  patron.appendChild(el("circle", {cx: 1, cy: 1, r: 1, fill: "var(--punto)"}));
  defs.appendChild(patron);
  var m = el("marker", {id: "flecha", viewBox: "0 0 9 7", refX: 8.5, refY: 3.5,
                        markerWidth: 7, markerHeight: 6, orient: "auto"});
  m.appendChild(el("path", {d: "M0,0 L9,3.5 L0,7 Z", fill: "var(--cable)"}));
  defs.appendChild(m);
  svg.appendChild(defs);
  fondo = el("rect", {x: 0, y: 0, width: "100%", height: "100%", fill: "url(#puntos)"});
  svg.appendChild(fondo);
  vista = el("g", {id: "vista"});
  gAristas = el("g", {});
  gNodos = el("g", {});
  gExtra = el("g", {});
  vista.appendChild(gAristas); vista.appendChild(gNodos); vista.appendChild(gExtra);
  svg.appendChild(vista);
}
function aplicarVista(){
  vista.setAttribute("transform", "translate(" + S.tx + " " + S.ty + ") scale(" + S.k + ")");
  var g = REJILLA * S.k;
  patron.setAttribute("width", g);
  patron.setAttribute("height", g);
  patron.setAttribute("patternTransform",
    "translate(" + (S.tx % g - 9 * S.k) + " " + (S.ty % g - 9 * S.k) + ") scale(" + S.k + ")");
  $("#nivel-zoom").textContent = Math.round(S.k * 100) + "%";
  colocarToolbarArista();
  pintarMini();
}
function caja(){ return $("#lienzo").getBoundingClientRect(); }
function aMundo(cx, cy){
  var r = caja();
  return {x: (cx - r.left - S.tx) / S.k, y: (cy - r.top - S.ty) / S.k};
}
function aPantalla(x, y){ return {x: x * S.k + S.tx, y: y * S.k + S.ty}; }
function zoomA(k1, mx, my){
  var r = caja();
  if(mx === undefined){ mx = r.width / 2; my = r.height / 2; }
  k1 = Math.min(3, Math.max(0.15, k1));
  S.tx = mx - (mx - S.tx) * (k1 / S.k);
  S.ty = my - (my - S.ty) * (k1 / S.k);
  S.k = k1;
  aplicarVista();
}
function limites(){
  var ns = nodos(), padres = padresDe();
  if(!ns.length) return null;
  var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for(var i = 0; i < ns.length; i++){
    var p = posDe(ns[i].id), w = anchoDe(ns[i], padres);
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x + w); y1 = Math.max(y1, p.y + NH + 34);
  }
  return {x0: x0, y0: y0, x1: x1, y1: y1};
}
function ajustar(){
  var b = limites(), r = caja();
  if(!b){ S.k = 1; S.tx = 40; S.ty = 40; aplicarVista(); return; }
  var m = 60;
  var k = Math.min((r.width - m) / Math.max(1, b.x1 - b.x0),
                   (r.height - m) / Math.max(1, b.y1 - b.y0), 1);
  S.k = Math.max(0.15, k);
  S.tx = (r.width - (b.x1 - b.x0) * S.k) / 2 - b.x0 * S.k;
  S.ty = (r.height - (b.y1 - b.y0) * S.k) / 2 - b.y0 * S.k;
  aplicarVista();
}

/* =========================================================================
   ARISTAS
   ========================================================================= */
function despl(d){ return d >= 0 ? 0.5 * d : 0.25 * 25 * Math.sqrt(-d); }
function camino(x1, y1, x2, y2){
  if(x2 < x1 - 20){
    /* Hacia atras: dos tramos que bajan 130px por debajo, como n8n. Una
       bezier recta atravesaria los nodos y no se leeria. */
    var my = Math.max(y1, y2) + BAJADA, mx = (x1 + x2) / 2;
    return "M " + x1 + "," + y1 + " C " + (x1 + 40) + "," + y1 + " " + (x1 + 40) + "," + my +
           " " + mx + "," + my + " C " + (x2 - 40) + "," + my + " " + (x2 - 40) + "," + y2 +
           " " + x2 + "," + y2;
  }
  var o = despl(x2 - x1);
  return "M " + x1 + "," + y1 + " C " + (x1 + o) + "," + y1 + " " + (x2 - o) + "," + y2 +
         " " + x2 + "," + y2;
}
function medio(x1, y1, x2, y2){
  if(x2 < x1 - 20) return {x: (x1 + x2) / 2, y: Math.max(y1, y2) + BAJADA};
  return {x: (x1 + x2) / 2, y: (y1 + y2) / 2};
}
function puertoSalida(n, padres){
  var p = posDe(n.id);
  return {x: p.x + anchoDe(n, padres), y: p.y + NH / 2};
}
function puertoEntrada(n){
  var p = posDe(n.id);
  return {x: p.x, y: p.y + NH / 2};
}

/* =========================================================================
   PINTAR EL LIENZO
   ========================================================================= */
function pintar(){
  /* CAPA 3 de la defensa de tipos (ver arriba): pintar() lo llaman ~30
     sitios, y varios estan DENTRO del arranque. Una excepcion aqui no puede
     llevarse por delante el resto de arrancar() -- eso es exactamente lo que
     paso con el args dict: la pagina quedo muda, con el indicador en
     "conectando" para siempre, indistinguible de un servidor lento. Ahora
     el fallo SE VE (banner ambar + console.error) y lo demas sigue. */
  try{
    completarPos();
    var padres = padresDe();
    pintarAristas(padres);
    pintarNodos(padres);
    pintarMini();
    /* La linea de tiempo NO se repinta aqui: pintar() corre en cada frame de
       un arrastre y reconstruir los chips 60 veces por segundo es puro churn. */
  }catch(err){
    fallo("pintar el lienzo", err);
  }
}
/* El unico sitio que convierte una excepcion en algo que el dueno VE. El
   aviso ambar deduplica por texto, asi que un fallo que se repite en cada
   frame de un arrastre no llena la pantalla de banners. */
function fallo(donde, err){
  var m = err && err.message ? err.message : String(err);
  try{ if(window.console && console.error) console.error("[editor] " + donde, err); }catch(e){}
  try{ avisar("no se pudo " + donde + ": " + m +
              ". Lo demas sigue funcionando; copia el JSON si algo falta.", "editor"); }catch(e){}
}

function pintarAristas(padres){
  gAristas.textContent = "";
  var ns = nodos(), i, j;
  for(i = 0; i < ns.length; i++){
    var a = ns[i], ws = a.wires || [];
    for(j = 0; j < ws.length; j++){
      var b = nodoPorId(ws[j]);
      if(!b) continue;
      var p = puertoSalida(a, padres), q = puertoEntrada(b);
      var d = camino(p.x, p.y, q.x, q.y);
      var g = el("g", {});
      /* El path transparente de 40px es lo que hace acertable una linea de
         2px con el raton. Sin el, la toolbar de la arista no se puede usar. */
      var golpe = el("path", {d: d, class: "golpe"});
      golpe.dataset.de = a.id; golpe.dataset.a = b.id;
      var linea = el("path", {d: d, class: "arista" + (b.saltar_si ? " corta" : ""),
                              "marker-end": "url(#flecha)",
                              "vector-effect": "non-scaling-stroke"});
      if(S.aristaViva && S.aristaViva.de === a.id && S.aristaViva.a === b.id)
        linea.setAttribute("class", linea.getAttribute("class") + " viva");
      g.appendChild(linea); g.appendChild(golpe);
      gAristas.appendChild(g);
      (function(de, hacia, mx, my){
        golpe.addEventListener("pointerenter", function(){ entrarArista(de, hacia, mx, my); });
        golpe.addEventListener("pointerleave", salirArista);
      })(a.id, b.id, medio(p.x, p.y, q.x, q.y).x, medio(p.x, p.y, q.x, q.y).y);
    }
  }
}

function pintarNodos(padres){
  gNodos.textContent = "";
  var ns = nodos();
  for(var i = 0; i < ns.length; i++){
    /* Un nodo raro pierde SU caja, no el lienzo entero: antes el primer
       nodo con un campo de tipo inesperado se llevaba los seis. En su hueco
       queda una caja punteada con el id, para que el dueno la pueda ver,
       seleccionar y abrir (F2/doble clic siguen yendo por id). */
    try{
      gNodos.appendChild(pintarNodo(ns[i], padres));
    }catch(err){
      fallo("pintar el nodo \"" + aTexto(ns[i] && ns[i].id) + "\"", err);
      try{ gNodos.appendChild(nodoRoto(ns[i])); }catch(e2){}
    }
  }
}
function nodoRoto(n){
  var p = posDe(n.id);
  var g = el("g", {class: "nodo roto", transform: "translate(" + p.x + " " + p.y + ")"});
  g.dataset.id = n.id;
  g.appendChild(el("rect", {x: 0, y: 0, width: NW, height: NH, rx: 12, class: "caja",
                            "stroke-dasharray": "5,5"}));
  g.appendChild(txt(aTexto(n.id), NW / 2, NH / 2 + 5, "n-id", "middle"));
  g.appendChild(txt("no se pudo pintar", NW / 2, NH + 18, "n-arg fuera", "middle"));
  return g;
}

function pintarNodo(n, padres){
  var p = posDe(n.id), f = forma(n, padres), w = anchoDe(n, padres);
  var fi = ficha(n.tool), col = colorDe(n.tool);
  var g = el("g", {class: "nodo" + (S.sel[n.id] ? " sel" : "") + (n.saltar_si ? " saltado" : ""),
                   transform: "translate(" + p.x + " " + p.y + ")"});
  g.dataset.id = n.id;

  if(f === "trigger"){
    /* Lado izquierdo redondeado a 36 y sin puerto de entrada: la firma
       visual del disparador. Aqui significa "nodo sin padres". */
    var r = 36, rr = 12;
    var d = "M " + r + ",0 H " + (w - rr) + " a " + rr + "," + rr + " 0 0 1 " + rr + "," + rr +
            " V " + (NH - rr) + " a " + rr + "," + rr + " 0 0 1 " + (-rr) + "," + rr +
            " H " + r + " a " + r + "," + r + " 0 0 1 " + (-r) + "," + (-r) +
            " V " + r + " a " + r + "," + r + " 0 0 1 " + r + "," + (-r) + " Z";
    g.appendChild(el("path", {d: d, class: "caja"}));
  }else{
    g.appendChild(el("rect", {x: 0, y: 0, width: w, height: NH, rx: 12, class: "caja"}));
  }
  if(fi && fi.danger)
    g.appendChild(f === "trigger"
      ? el("rect", {x: -5, y: -5, width: w + 10, height: NH + 10, rx: 20, class: "anillo"})
      : el("rect", {x: -5, y: -5, width: w + 10, height: NH + 10, rx: 17, class: "anillo"}));

  var ico = icono(iconoDe(n.tool), col, 44);
  /* aTexto y NO (n.args || ""): con un args dict eso lanzaba
     "TypeError: .replace is not a function" y se llevaba la pagina entera
     (ver "LOS TIPOS DEL JSON DE DISCO NO ESTAN GARANTIZADOS"). */
  var argsCorto = aTexto(n.args).replace(/\s+/g, " ").slice(0, f === "configurable" ? 30 : 16);
  if(f === "configurable"){
    ico.setAttribute("transform", "translate(20 26)");
    g.appendChild(ico);
    g.appendChild(txt(n.id, 78, 44, "n-id"));
    g.appendChild(txt(n.tool, 78, 62, "n-tool"));
    if(argsCorto) g.appendChild(txt(argsCorto, 78, 78, "n-arg"));
  }else{
    ico.setAttribute("transform", "translate(" + (w / 2 - 22) + " " + (NH / 2 - 26) + ")");
    g.appendChild(ico);
    g.appendChild(txt(n.tool, w / 2, NH - 16, "n-tool", "middle"));
    g.appendChild(txt(n.id, w / 2, NH + 18, "n-id fuera", "middle"));
    if(argsCorto) g.appendChild(txt(argsCorto, w / 2, NH + 32, "n-arg fuera", "middle"));
  }

  /* Badges de control de flujo: en Cognia no son nodos, son campos. */
  var bx = w - 12, by = 12;
  if(n.saltar_si){ g.appendChild(badge(bx, by, "salto")); bx -= 21; }
  if(n.reintentos > 0){ g.appendChild(badge(bx, by, "rein", n.reintentos)); bx -= 21; }
  if(n.timeout_s){ g.appendChild(badge(bx, by, "reloj")); }

  /* Puertos. El de entrada no existe en un trigger (no tiene padres). */
  if(f !== "trigger")
    g.appendChild(el("circle", {cx: 0, cy: NH / 2, r: PUERTO, class: "puerto entrada"}));
  var sal = el("circle", {cx: w, cy: NH / 2, r: PUERTO, class: "puerto salida"});
  sal.dataset.puerto = "salida";
  g.appendChild(sal);

  /* Rombo inferior: los nodos de la categoria IA (o con modelo fijado) hablan
     con un modelo. En n8n eso es un puerto de conexion de tipo IA; en Cognia
     no hay un segundo tipo de arista, asi que el rombo es SENAL, no puerto:
     no se arrastra desde el, y lo dice su title. Fingir un puerto que no
     conecta nada seria UI muerta. */
  if((fi && fi.categoria === "ia") || n.modelo){
    var rb = el("path", {d: "M 0,-7 L 7,0 L 0,7 L -7,0 Z", class: "rombo",
                         transform: "translate(" + (w / 2) + " " + NH + ")"});
    var ti = el("title", {});
    ti.textContent = "conexion de tipo IA: este paso habla con el modelo" +
                     (n.modelo ? " (" + n.modelo + ")" : "");
    rb.appendChild(ti);
    g.appendChild(rb);
  }

  /* El "+" al final de un puerto de salida suelto. */
  if(!(n.wires || []).length && !S.soloLectura){
    var gm = el("g", {class: "mas", transform: "translate(" + (w + PUERTO) + " " + NH / 2 + ")"});
    gm.appendChild(el("line", {x1: 0, y1: 0, x2: TALLO, y2: 0}));
    var c = el("g", {transform: "translate(" + TALLO + " " + (-MAS / 2) + ")"});
    c.appendChild(el("rect", {x: 2, y: 2, width: 20, height: 20, rx: 5}));
    c.appendChild(el("path", {d: "M8 12h8m-4-4v8"}));
    gm.appendChild(c);
    gm.dataset.mas = n.id;
    g.appendChild(gm);
  }

  if(S.errNodo === n.id && S.errValidar)
    g.appendChild(txt(S.errValidar.slice(0, 60), 0, -12, "err-nodo"));
  return g;
}

function txt(s, x, y, clase, anclaje){
  var t = el("text", {x: x, y: y, class: clase, "pointer-events": "none"});
  if(anclaje) t.setAttribute("text-anchor", anclaje);
  t.textContent = s;
  return t;
}
function badge(x, y, tipo, num){
  var g = el("g", {class: "badge"});
  g.appendChild(el("circle", {cx: x, cy: y, r: 9}));
  if(tipo === "salto")
    g.appendChild(el("path", {d: "M" + (x - 4) + " " + (y - 4) + "l4 4-4 4M" + (x + 3) +
                                 " " + (y - 4) + "v8"}));
  else if(tipo === "reloj")
    g.appendChild(el("path", {d: "M" + x + " " + (y - 4) + "v4h3"}));
  else{
    var t = el("text", {x: x, y: y + 3.5, "text-anchor": "middle"});
    t.textContent = String(num);
    g.appendChild(t);
  }
  var ti = el("title", {});
  ti.textContent = tipo === "salto" ? "tiene saltar_si"
                 : tipo === "reloj" ? "tiene timeout_s" : "reintentos: " + num;
  g.appendChild(ti);
  return g;
}

/* --------- minimapa --------- */
function pintarMini(){
  var mini = $("#mini");
  mini.textContent = "";
  var b = limites();
  if(!b) return;
  var W = 190, H = 120, m = 8;
  var k = Math.min((W - m * 2) / Math.max(1, b.x1 - b.x0), (H - m * 2) / Math.max(1, b.y1 - b.y0));
  var ox = m - b.x0 * k, oy = m - b.y0 * k;
  var ns = nodos(), padres = padresDe();
  for(var i = 0; i < ns.length; i++){
    var p = posDe(ns[i].id), w = anchoDe(ns[i], padres);
    mini.appendChild(el("rect", {x: p.x * k + ox, y: p.y * k + oy,
      width: Math.max(2, w * k), height: Math.max(2, NH * k), rx: 2,
      fill: colorDe(ns[i].tool), opacity: S.sel[ns[i].id] ? 1 : .55}));
  }
  var r = caja();
  mini.appendChild(el("rect", {x: (-S.tx / S.k) * k + ox, y: (-S.ty / S.k) * k + oy,
    width: (r.width / S.k) * k, height: (r.height / S.k) * k,
    fill: "none", stroke: "var(--acento)", "stroke-width": 1}));
  mini.dataset.k = k; mini.dataset.ox = ox; mini.dataset.oy = oy;
}
$("#mini").addEventListener("pointerdown", function(e){
  var mini = $("#mini"), k = parseFloat(mini.dataset.k || 1);
  var r = mini.getBoundingClientRect();
  var mx = (e.clientX - r.left - parseFloat(mini.dataset.ox || 0)) / k;
  var my = (e.clientY - r.top - parseFloat(mini.dataset.oy || 0)) / k;
  var c = caja();
  S.tx = c.width / 2 - mx * S.k;
  S.ty = c.height / 2 - my * S.k;
  aplicarVista();
});

/* =========================================================================
   TOOLBAR DE LA ARISTA (con la histeresis de 600 ms)
   ========================================================================= */
function entrarArista(de, a, mx, my){
  if(S.aristaTimer){ clearTimeout(S.aristaTimer); S.aristaTimer = null; }
  S.aristaViva = {de: de, a: a, x: mx, y: my};
  $("#tb-arista").className = "visible";
  colocarToolbarArista();
}
function salirArista(){
  if(S.aristaTimer) clearTimeout(S.aristaTimer);
  /* 600 ms de gracia: sin ellos, el raton no llega a los botones. */
  S.aristaTimer = setTimeout(function(){
    S.aristaViva = null;
    $("#tb-arista").className = "";
  }, HISTERESIS);
}
$("#tb-arista").addEventListener("pointerenter", function(){
  if(S.aristaTimer){ clearTimeout(S.aristaTimer); S.aristaTimer = null; }
});
$("#tb-arista").addEventListener("pointerleave", salirArista);
function colocarToolbarArista(){
  if(!S.aristaViva) return;
  var p = aPantalla(S.aristaViva.x, S.aristaViva.y);
  var t = $("#tb-arista");
  t.style.left = p.x + "px";
  t.style.top = p.y + "px";
}
$("#b-arista-borrar").onclick = function(){
  if(!S.aristaViva || S.soloLectura) return;
  instantanea();
  var n = nodoPorId(S.aristaViva.de);
  if(n) n.wires = (n.wires || []).filter(function(w){ return w !== S.aristaViva.a; });
  S.aristaViva = null;
  $("#tb-arista").className = "";
  cambio();
};
$("#b-arista-mas").onclick = function(){
  if(!S.aristaViva || S.soloLectura) return;
  S.pendiente = {insertar: {de: S.aristaViva.de, a: S.aristaViva.a},
                 x: S.aristaViva.x, y: S.aristaViva.y - NH / 2};
  $("#tb-arista").className = "";
  abrirPaleta();
};

/* =========================================================================
   INTERACCION DEL LIENZO
   ========================================================================= */
svg.addEventListener("wheel", function(e){
  e.preventDefault();
  var r = caja();
  zoomA(S.k * Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
}, {passive: false});

svg.addEventListener("pointerdown", function(e){
  var gm = e.target.closest ? e.target.closest(".mas") : null;
  if(gm && !S.soloLectura){
    var id = gm.dataset.mas;
    var n = nodoPorId(id), padres = padresDe();
    var p = puertoSalida(n, padres);
    S.pendiente = {de: id, x: p.x + TALLO + 40, y: p.y - NH / 2};
    abrirPaleta();
    return;
  }
  var g = e.target.closest ? e.target.closest(".nodo") : null;
  if(g && e.target.dataset && e.target.dataset.puerto === "salida" && !S.soloLectura){
    S.conectando = {de: g.dataset.id, x: 0, y: 0};
    svg.setPointerCapture(e.pointerId);
    return;
  }
  /* DOBLE CLIC = ABRIR PROPIEDADES. Se detecta AQUI, contando pointerdown
     por id + tiempo + distancia, y no con el evento 'dblclick'. El atajo
     esta en la hoja de ayuda desde el primer dia y NUNCA funciono (medido
     en Chromium el 2026-08-29: sobre un nodo no llegaba ni 'click' ni
     'dblclick'; sobre el <h1> si, o sea que no era el instrumento). Dos
     causas INDEPENDIENTES, las dos en este mismo handler:
       1. pintar() reconstruia el <g> del nodo DENTRO del pointerdown: el
          elemento del primer clic ya no existia en el segundo y el
          navegador no emite el par (contrafactual en vivo: congelando
          pintar, 0 dblclick -> 1 dblclick).
       2. svg.setPointerCapture() redirige los eventos al <svg>: el
          dblclick llegaba con e.target === svg y closest(".nodo") null,
          asi que abrirProps no se llamaba igual ("svg//closest=false").
     Contar los pointerdown es inmune a LAS DOS: no depende de que el nodo
     sobreviva al repintado ni de a quien apunte e.target. Las dos causas se
     arreglan ademas por separado (abajo: repintar solo si cambia la
     seleccion; y el 'dblclick' nativo resolviendo el nodo por coordenada),
     pero la via que DECIDE es esta. Y funciona tambien en solo-lectura:
     mirar las propiedades de un nodo sin servidor es legitimo. */
  if(g && !(e.target.dataset && e.target.dataset.puerto)){
    var idc = g.dataset.id;
    var ahora = Date.now();
    var ult = S.ultimoDown;
    if(ult && ult.id === idc && (ahora - ult.t) < DOBLE_MS &&
       Math.abs(e.clientX - ult.x) <= DOBLE_PX && Math.abs(e.clientY - ult.y) <= DOBLE_PX){
      S.ultimoDown = null;
      S.tProps = ahora;
      abrirProps(idc);
      return;
    }
    S.ultimoDown = {id: idc, t: ahora, x: e.clientX, y: e.clientY};
  }
  if(g && !S.soloLectura){
    var id2 = g.dataset.id;
    var eraSel = !!S.sel[id2], antesN = idsSel().length;
    if(e.ctrlKey || e.metaKey || e.shiftKey){
      if(S.sel[id2]) delete S.sel[id2]; else S.sel[id2] = 1;
    }else if(!S.sel[id2]){
      S.sel = {}; S.sel[id2] = 1;
    }
    instantanea();
    var m = aMundo(e.clientX, e.clientY);
    var base = {};
    var ids = idsSel();
    for(var i = 0; i < ids.length; i++) base[ids[i]] = {x: posDe(ids[i]).x, y: posDe(ids[i]).y};
    S.arrastre = {mx: m.x, my: m.y, base: base, movio: false};
    svg.setPointerCapture(e.pointerId);
    /* CAUSA 1 del doble clic muerto, arreglada en su raiz: solo se repinta
       si la SELECCION cambio. Antes se reconstruia el nodo en cada
       pointerdown -- incluido el segundo clic sobre un nodo YA
       seleccionado, donde no hay nada que repintar -- y eso destruia el
       elemento entre los dos clics. De paso ahorra un repintado completo
       del lienzo al empezar cada arrastre. */
    if(!eraSel || idsSel().length !== antesN) pintar();
    return;
  }
  /* Fondo, igual que n8n: espacio, Ctrl o el boton central arrastran el
     LIENZO; el boton izquierdo a secas dibuja el rectangulo de seleccion, y
     Shift lo suma a lo que ya estaba elegido. */
  if(S.espacio || e.button === 1 || ((e.ctrlKey || e.metaKey) && e.button === 0)){
    S.panea = {mx: e.clientX, my: e.clientY, tx: S.tx, ty: S.ty};
    svg.classList.add("paneando");
    svg.setPointerCapture(e.pointerId);
    return;
  }
  if(e.button === 0){
    var w = aMundo(e.clientX, e.clientY);
    S.marquee = {x0: w.x, y0: w.y, x1: w.x, y1: w.y, suma: e.shiftKey};
    if(!S.marquee.suma){ S.sel = {}; pintar(); cerrarProps(); }
    svg.setPointerCapture(e.pointerId);
  }
});

svg.addEventListener("pointermove", function(e){
  if(S.panea){
    S.tx = S.panea.tx + (e.clientX - S.panea.mx);
    S.ty = S.panea.ty + (e.clientY - S.panea.my);
    aplicarVista();
    return;
  }
  if(S.arrastre){
    var m = aMundo(e.clientX, e.clientY);
    var dx = m.x - S.arrastre.mx, dy = m.y - S.arrastre.my;
    if(Math.abs(dx) > 2 || Math.abs(dy) > 2) S.arrastre.movio = true;
    for(var id in S.arrastre.base){
      S.pos[id] = {x: snap(S.arrastre.base[id].x + dx), y: snap(S.arrastre.base[id].y + dy)};
    }
    pintar();
    return;
  }
  if(S.conectando){
    var w = aMundo(e.clientX, e.clientY);
    S.conectando.x = w.x; S.conectando.y = w.y;
    pintarFantasma();
    return;
  }
  if(S.marquee){
    var w2 = aMundo(e.clientX, e.clientY);
    S.marquee.x1 = w2.x; S.marquee.y1 = w2.y;
    pintarMarquee();
  }
});

svg.addEventListener("pointerup", function(e){
  if(S.panea){ S.panea = null; svg.classList.remove("paneando"); return; }
  if(S.arrastre){
    var movio = S.arrastre.movio;
    S.arrastre = null;
    if(movio) guardarPosPronto(); else S.undo.pop();
    return;
  }
  if(S.conectando){
    var w = aMundo(e.clientX, e.clientY);
    var destino = nodoCercano(w.x, w.y);
    var de = S.conectando.de;
    S.conectando = null;
    gExtra.textContent = "";
    if(destino && destino.id !== de){
      instantanea();
      var n = nodoPorId(de);
      n.wires = n.wires || [];
      if(n.wires.indexOf(destino.id) < 0) n.wires.push(destino.id);
      cambio();
    }else if(!S.soloLectura){
      /* Soltar en el vacio abre la paleta y conecta lo que se elija: es el
         truco de UX mas rentable de n8n. */
      S.pendiente = {de: de, x: snap(w.x), y: snap(w.y - NH / 2)};
      abrirPaleta();
    }
    return;
  }
  if(S.marquee){
    var m = S.marquee;
    S.marquee = null;
    gExtra.textContent = "";
    var x0 = Math.min(m.x0, m.x1), x1 = Math.max(m.x0, m.x1);
    var y0 = Math.min(m.y0, m.y1), y1 = Math.max(m.y0, m.y1);
    if(Math.abs(x1 - x0) > 4 || Math.abs(y1 - y0) > 4){
      var ns = nodos(), padres = padresDe();
      for(var i = 0; i < ns.length; i++){
        var p = posDe(ns[i].id), w2 = anchoDe(ns[i], padres);
        if(p.x < x1 && p.x + w2 > x0 && p.y < y1 && p.y + NH > y0) S.sel[ns[i].id] = 1;
      }
      pintar();
    }
  }
});

/* El 'dblclick' nativo se queda como SEGUNDA via (raton con doble clic de
   hardware, accesibilidad, un navegador que emita el par pese al repintado),
   con la CAUSA 2 arreglada: el nodo se resuelve por COORDENADA y no por
   e.target.closest(), que devolvia null siempre que el puntero estaba
   capturado por el <svg>. El guardia de 700 ms evita abrir dos veces cuando
   la via de los pointerdown ya lo hizo (abrirProps roba el foco). */
svg.addEventListener("dblclick", function(e){
  var g = e.target.closest ? e.target.closest(".nodo") : null;
  var id = g ? g.dataset.id : null;
  if(!id){
    var w = aMundo(e.clientX, e.clientY);
    var n = nodoEnPunto(w.x, w.y);
    if(n) id = n.id;
  }
  if(!id) return;
  if(S.propsId === id && (Date.now() - (S.tProps || 0)) < 700) return;
  S.tProps = Date.now();
  abrirProps(id);
});
/* Acierto ESTRICTO: dentro de la caja. nodoCercano vale para soltar una
   arista (60 px de tolerancia), pero para un doble clic esa tolerancia
   abriria el nodo de al lado al hacer doble clic en el vacio. */
function nodoEnPunto(x, y){
  var ns = nodos(), padres = padresDe();
  for(var i = ns.length - 1; i >= 0; i--){
    var p = posDe(ns[i].id), w = anchoDe(ns[i], padres);
    if(x >= p.x && x <= p.x + w && y >= p.y && y <= p.y + NH) return ns[i];
  }
  return null;
}

function nodoCercano(x, y){
  var ns = nodos(), padres = padresDe(), mejor = null, dmin = 60;
  for(var i = 0; i < ns.length; i++){
    var q = puertoEntrada(ns[i]);
    var d = Math.hypot(q.x - x, q.y - y);
    var p = posDe(ns[i].id), w = anchoDe(ns[i], padres);
    var dentro = x >= p.x && x <= p.x + w && y >= p.y && y <= p.y + NH;
    if(dentro) return ns[i];
    if(d < dmin){ dmin = d; mejor = ns[i]; }
  }
  return mejor;
}
function pintarFantasma(){
  gExtra.textContent = "";
  var n = nodoPorId(S.conectando.de);
  if(!n) return;
  var p = puertoSalida(n, padresDe());
  gExtra.appendChild(el("path", {class: "fantasma",
    d: camino(p.x, p.y, S.conectando.x, S.conectando.y)}));
}
function pintarMarquee(){
  gExtra.textContent = "";
  var m = S.marquee;
  gExtra.appendChild(el("rect", {id: "marquee",
    x: Math.min(m.x0, m.x1), y: Math.min(m.y0, m.y1),
    width: Math.abs(m.x1 - m.x0), height: Math.abs(m.y1 - m.y0)}));
}

/* arrastrar y soltar desde la paleta */
$("#lienzo").addEventListener("dragover", function(e){ e.preventDefault(); });
$("#lienzo").addEventListener("drop", function(e){
  e.preventDefault();
  var tool = "";
  try{ tool = e.dataTransfer.getData("text/plain"); }catch(err){}
  if(!tool || S.soloLectura) return;
  var w = aMundo(e.clientX, e.clientY);
  anadirNodo(tool, snap(w.x - NW / 2), snap(w.y - NH / 2));
});

/* =========================================================================
   MUTACIONES DEL GRAFO
   ========================================================================= */
function idLibre(base){
  var b = String(base || "n").replace(/[^a-zA-Z0-9_\-]/g, "_").slice(0, 24) || "n";
  if(!nodoPorId(b)) return b;
  var i = 2;
  while(nodoPorId(b + "_" + i)) i++;
  return b + "_" + i;
}
function anadirNodo(tool, x, y, opciones){
  instantanea();
  var id = idLibre(tool);
  var n = {id: id, tool: tool, args: "", wires: []};
  nodos().push(n);
  S.pos[id] = {x: x, y: y};
  var o = opciones || {};
  if(o.de){
    var p = nodoPorId(o.de);
    if(p){ p.wires = p.wires || []; if(p.wires.indexOf(id) < 0) p.wires.push(id); }
  }
  if(o.insertar){
    var a = nodoPorId(o.insertar.de), b = nodoPorId(o.insertar.a);
    if(a && b){
      a.wires = (a.wires || []).filter(function(w){ return w !== b.id; });
      a.wires.push(id);
      n.wires = [b.id];
    }
  }
  S.sel = {}; S.sel[id] = 1;
  cambio();
  abrirProps(id);
  return id;
}
function borrarSeleccion(){
  var ids = idsSel();
  if(!ids.length || S.soloLectura) return;
  instantanea();
  var fuera = {};
  for(var i = 0; i < ids.length; i++) fuera[ids[i]] = 1;
  S.flujo.nodos = nodos().filter(function(n){ return !fuera[n.id]; });
  var ns = nodos();
  for(var j = 0; j < ns.length; j++)
    ns[j].wires = (ns[j].wires || []).filter(function(w){ return !fuera[w]; });
  for(var k in fuera) delete S.pos[k];
  S.sel = {};
  cerrarProps();
  cambio();
}
function renombrar(viejo, nuevo){
  nuevo = String(nuevo || "").replace(/[^a-zA-Z0-9_\-]/g, "_");
  if(!nuevo || nuevo === viejo) return viejo;
  if(nodoPorId(nuevo)){ toast("ya hay un nodo con el id " + nuevo, true); return viejo; }
  instantanea();
  var n = nodoPorId(viejo);
  if(!n) return viejo;
  n.id = nuevo;
  var ns = nodos();
  for(var i = 0; i < ns.length; i++)
    ns[i].wires = (ns[i].wires || []).map(function(w){ return w === viejo ? nuevo : w; });
  S.pos[nuevo] = S.pos[viejo];
  delete S.pos[viejo];
  if(S.sel[viejo]){ delete S.sel[viejo]; S.sel[nuevo] = 1; }
  if(S.propsId === viejo) S.propsId = nuevo;
  cambio();
  return nuevo;
}
function copiar(){
  var ids = idsSel();
  if(!ids.length) return;
  S.portapapeles = [];
  for(var i = 0; i < ids.length; i++){
    var n = nodoPorId(ids[i]);
    if(n) S.portapapeles.push({n: clonar(n), p: clonar(posDe(ids[i]))});
  }
  toast(S.portapapeles.length + " nodos copiados");
}
function pegar(){
  if(!S.portapapeles.length || S.soloLectura) return;
  instantanea();
  var mapa = {}, nuevos = {}, i;
  for(i = 0; i < S.portapapeles.length; i++){
    var viejo = S.portapapeles[i].n.id;
    mapa[viejo] = idLibre(viejo);
    nuevos[mapa[viejo]] = 1;
  }
  S.sel = {};
  for(i = 0; i < S.portapapeles.length; i++){
    var c = clonar(S.portapapeles[i].n);
    var viejoId = c.id;
    c.id = mapa[viejoId];
    /* Los wires internos a la copia se renumeran; los que apuntaban fuera de
       la seleccion se conservan si ese nodo sigue existiendo. */
    c.wires = (c.wires || []).map(function(w){ return mapa[w] || w; })
                             .filter(function(w){ return !!nuevos[w] || !!nodoPorId(w); });
    nodos().push(c);
    S.pos[c.id] = {x: snap(S.portapapeles[i].p.x + 40), y: snap(S.portapapeles[i].p.y + 40)};
    S.sel[c.id] = 1;
  }
  cambio();
}

/* --------- undo / redo por instantaneas (simple y correcto) --------- */
function instantanea(){
  S.undo.push(JSON.stringify({f: S.flujo, p: S.pos}));
  if(S.undo.length > TOPE_UNDO) S.undo.shift();
  S.redo = [];
}
function aplicar(txt){
  var o = JSON.parse(txt);
  S.flujo = o.f; S.pos = o.p;
  S.sel = {};
  cerrarProps();
  cambio();
}
function deshacer(){
  if(!S.undo.length){ toast("nada que deshacer"); return; }
  S.redo.push(JSON.stringify({f: S.flujo, p: S.pos}));
  aplicar(S.undo.pop());
}
function rehacer(){
  if(!S.redo.length){ toast("nada que rehacer"); return; }
  S.undo.push(JSON.stringify({f: S.flujo, p: S.pos}));
  aplicar(S.redo.pop());
}

/* Un cambio del grafo: repinta, pide validacion en vivo y guarda posiciones. */
function cambio(){
  pintar();
  if(S.propsId) pintarProps();
  validarPronto();
  guardarPosPronto();
}

/* =========================================================================
   RED
   ========================================================================= */
function api(ruta, opciones){
  if(!BASE) return Promise.reject(new Error("sin servidor"));
  var o = opciones || {};
  var cab = {"X-Cognia-Token": TOKEN};
  if(o.body) cab["Content-Type"] = "application/json";
  return fetch(BASE + ruta, {method: o.method || "GET", headers: cab,
                             body: o.body ? JSON.stringify(o.body) : undefined})
    .then(function(r){
      return r.json().catch(function(){ return {ok: false, error: "respuesta ilegible (" + r.status + ")"}; });
    })
    .then(function(j){ marcarOnline(true); return j; })
    .catch(function(e){ marcarOnline(false); throw e; });
}
function marcarOnline(ok){
  if(S.online === ok) return;
  S.online = ok;
  $("#punto-estado").className = ok ? "" : "mal";
  $("#estado-txt").textContent = ok ? "conectado con Cognia" : "sin conexion";
  if(ok) rearmar(); else degradar();
}
function degradar(){
  S.soloLectura = true;
  S.online = false;
  $("#punto-estado").className = "mal";
  $("#estado-txt").textContent = "sin conexion";
  $("#b-guardar").disabled = true;
  $("#b-validar").disabled = true;
  $("#b-enviar").disabled = true;
  pintar();
  /* Sin BASE no hay servidor al que volver (render con base=""): el banner
     se queda fijo y no se reintenta nada. Con BASE, la caida es casi siempre
     temporal -- el POST /api/pos del debounce pillando una suspension del
     portatil o un reinicio del servidor -- asi que se repinga sola. */
  if(BASE) reintentarPronto(); else pintarBanner("");
}
/* La vuelta atras de degradar(). ANTES no existia: S.soloLectura se ponia a
   true y no volvia a false en todo el fichero, asi que un unico fetch fallido
   dejaba la pestana muerta hasta recargar mientras el indicador decia
   "conectado con Cognia" (rev_ciclo-de-vida, hallazgo 3). */
function rearmar(){
  pararReintento();
  $("#banner").hidden = true;
  if(!S.soloLectura) return;
  S.soloLectura = false;
  /* Se REHABILITA respetando las otras guardas, no a lo bruto: mirando una
     version antigua Guardar sigue apagado, y con el chat en vuelo Enviar
     tambien (S.reloj solo corre mientras hay una peticion de chat viva). */
  $("#b-validar").disabled = false;
  $("#b-enviar").disabled = !!S.reloj;
  $("#b-guardar").disabled = !!S.mirandoV || !!S.errValidar;
  pintar();
  toast("conexion recuperada: ya puedes editar");
  /* La verdad del boton Guardar la tiene el servidor, no esta funcion. */
  validarAhora();
}
function pintarBanner(cola){
  var b = $("#banner");
  b.textContent = "";
  b.appendChild(div(null,
    "Sin conexion con Cognia: la pagina sigue en solo-lectura. " +
    "Puedes copiar el JSON y pegarlo con /flujoteca importar." +
    (cola ? "  " + cola : "")));
  if(BASE){
    b.appendChild(div("sep"));
    var r = document.createElement("button");
    r.textContent = "reintentar ahora";
    r.onclick = function(){ pararReintento(); reintentarPronto(0); };
    b.appendChild(r);
  }
  b.hidden = false;
}
/* Reintento con retroceso exponencial: 2 s, 4 s, 8 s ... hasta 30 s. Es lo
   que hace que la pagina se RECUPERE SOLA sin que el dueno tenga que saber
   que hay que recargar (cosa que ademas la pagina no decia). */
var tReintento = null, esperaReintento = 0;
function pararReintento(){
  if(tReintento){ clearTimeout(tReintento); tReintento = null; }
  esperaReintento = 0;
}
function reintentarPronto(forzar){
  if(!BASE || tReintento) return;
  var espera = forzar === 0 ? 0 :
    (esperaReintento ? Math.min(esperaReintento * 2, REINTENTO_MAX) : REINTENTO_MIN);
  esperaReintento = espera || REINTENTO_MIN;
  pintarBanner(espera ? "Reintentando la conexion en " +
                        Math.round(espera / 1000) + " s..."
                      : "Reintentando la conexion...");
  tReintento = setTimeout(function(){
    tReintento = null;
    pintarBanner("Reintentando la conexion...");
    /* api() ya llama a marcarOnline: si esto contesta, rearmar() entra solo.
       Si no, el catch encadena el siguiente reintento (marcarOnline(false)
       no vuelve a degradar: S.online ya es false). */
    api("/api/flujos").then(function(j){
      if(j && j.ok && j.flujos){ S.flujos = j.flujos; pintarSelectorFlujos(); }
      if(j && j.aviso) avisar(j.aviso, "servidor");
    }).catch(function(){ reintentarPronto(); });
  }, espera);
}

/* ------------------------------------------------------------------
   AVISOS DEL SERVIDOR
   El servidor emite 'aviso' cuando algo se degrado pero la pagina sigue
   siendo util: el catalogo no cargo (una familia opt-in con el import
   roto) o el flujo pedido no se pudo leer. Sin esto, el editor abria con
   la paleta vacia y CERO explicacion -- el vacio silencioso que esta casa
   tiene fichado como su fallo tipico. Va en AMBAR y no deshabilita nada:
   no es una caida, se sigue editando.
   ------------------------------------------------------------------ */
var avisosVistos = {};
function avisar(txt, fuente){
  txt = String(txt == null ? "" : txt).trim();
  if(!txt) return;
  /* El ping del reintento repite el mismo aviso cada pocos segundos: se
     pinta una vez, no una lista que crece sola. */
  var clave = (fuente || "") + "|" + txt;
  if(avisosVistos[clave]) return;
  avisosVistos[clave] = 1;
  $("#aviso-txt").appendChild(div(null, (fuente ? fuente + ": " : "") + txt));
  $("#aviso").hidden = false;
}
$("#b-aviso-x").onclick = function(){ $("#aviso").hidden = true; };

var tPos = null;
function guardarPosPronto(){
  if(S.soloLectura || !BASE) return;
  if(tPos) clearTimeout(tPos);
  /* Debounce de 800 ms. /api/pos NO crea version: las posiciones viven en
     meta["ui"]["pos"], fuera del DAG. */
  tPos = setTimeout(function(){
    api("/api/pos", {method: "POST", body: {nombre: S.nombre, pos: S.pos}})
      .catch(function(){});
  }, DEBOUNCE_POS);
}
var tVal = null;
function validarPronto(){
  if(!BASE) return;
  if(tVal) clearTimeout(tVal);
  tVal = setTimeout(validarAhora, DEBOUNCE_VAL);
}
function validarAhora(){
  if(!BASE) return;
  api("/api/validar", {method: "POST", body: {flujo: S.flujo}}).then(function(j){
    S.errValidar = j.ok ? "" : (j.error || "flujo invalido");
    S.errNodo = "";
    if(!j.ok){
      /* El servidor dice "nodo 'x': ...": se ancla el aviso a ese nodo. */
      var m = /nodo '([^']+)'/.exec(S.errValidar);
      if(m) S.errNodo = m[1];
    }
    $("#b-guardar").disabled = !j.ok || S.soloLectura || !!S.mirandoV;
    var e = $("#err-props");
    if(e){
      e.textContent = S.errValidar;
      e.className = S.errValidar ? "visible" : "";
    }
    pintar();
  }).catch(function(){});
}

/* =========================================================================
   BARRA SUPERIOR
   ========================================================================= */
function tema(t){
  document.documentElement.setAttribute("data-tema", t);
  $("#b-tema").innerHTML = t === "oscuro" ? "&#9788;" : "&#9789;";
  indexar();
  pintar();
  if(S.propsId) pintarProps();
  pintarPaleta();
}
(function(){
  var t = null;
  try{ t = localStorage.getItem("cognia_editor_tema"); }catch(e){}
  if(!t) t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
             ? "oscuro" : "claro";
  document.documentElement.setAttribute("data-tema", t);
})();
$("#b-tema").onclick = function(){
  var n = document.documentElement.getAttribute("data-tema") === "oscuro" ? "claro" : "oscuro";
  tema(n);
  try{ localStorage.setItem("cognia_editor_tema", n); }catch(e){}
};
$("#b-mas").onclick = function(){ zoomA(S.k * 1.2); };
$("#b-menos").onclick = function(){ zoomA(S.k / 1.2); };
$("#b-ajustar").onclick = ajustar;
$("#b-nodos").onclick = function(){ alternarPaleta(); };
$("#b-validar").onclick = function(){
  if(!BASE){ toast("sin servidor: la validacion vive en Python", true); return; }
  api("/api/validar", {method: "POST", body: {flujo: S.flujo}}).then(function(j){
    if(j.ok) toast("flujo valido: " + (j.orden || []).length + " nodos en orden");
    else toast(j.error || "flujo invalido", true);
    validarAhora();
  }).catch(function(){ toast("sin conexion con Cognia", true); });
};
$("#b-copiar").onclick = function(){
  var txt = JSON.stringify(S.flujo, null, 2);
  var hecho = false;
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt);
      hecho = true;
    }
  }catch(e){}
  $("#json-copiar").value = txt;
  abrirVelo("velo-copiar");
  $("#json-copiar").select();
  if(hecho) toast("JSON copiado al portapapeles");
};
$("#b-pegar").onclick = function(){
  $("#json-pegar").value = "";
  abrirVelo("velo-pegar");
  $("#json-pegar").focus();
};
$("#b-pegar-ok").onclick = function(){
  var crudo = $("#json-pegar").value;
  var o;
  try{ o = JSON.parse(crudo); }
  catch(e){ toast("eso no es JSON: " + e.message, true); return; }
  var nuevo = Array.isArray(o) ? {nombre: S.nombre, nodos: o} : o;
  if(!nuevo || !Array.isArray(nuevo.nodos)){ toast("el JSON no tiene 'nodos'", true); return; }
  instantanea();
  S.flujo = {nombre: nuevo.nombre || S.nombre, nodos: nuevo.nodos};
  S.pos = {};
  S.sel = {};
  /* FRONTERA: esto es JSON tecleado o pegado, el sitio con MENOS garantias
     de tipos de todo el editor. */
  sanearFlujo("el JSON pegado");
  cerrarVelo("velo-pegar");
  cambio();
  ajustar();
  toast("cargado en el lienzo: pulsa Guardar para crear una version");
};
$("#b-guardar").onclick = function(){
  if(S.soloLectura) return;
  $("#nota").value = "";
  abrirVelo("velo-guardar");
  $("#nota").focus();
};
$("#b-guardar-ok").onclick = function(){
  var nota = $("#nota").value;
  cerrarVelo("velo-guardar");
  api("/api/guardar", {method: "POST",
      body: {nombre: S.nombre, flujo: S.flujo, nota: nota, pos: S.pos}})
    .then(function(j){
      if(!j.ok){ toast(j.error || "no se guardo", true); return; }
      S.version = j.version;
      toast("guardado: version " + j.version);
      recargarVersiones();
    })
    .catch(function(){ toast("sin conexion con Cognia: no se guardo nada", true); });
};
$("#b-ayuda").onclick = function(){ abrirVelo("velo-hoja"); };
document.addEventListener("click", function(e){
  var c = e.target.getAttribute ? e.target.getAttribute("data-cerrar") : null;
  if(c) cerrarVelo(c);
});
function abrirVelo(id){ $("#" + id).classList.add("visible"); }
function cerrarVelo(id){ $("#" + id).classList.remove("visible"); }
function cerrarVelos(){
  var v = document.querySelectorAll(".velo.visible");
  for(var i = 0; i < v.length; i++) v[i].classList.remove("visible");
}

/* --------- selector de flujo --------- */
/* El <h1> y el TITULO DE LA PESTANA se ponen SIEMPRE juntos. Antes el
   titulo del documento se escribia en un solo sitio (arrancar), asi que al
   cambiar de flujo con el selector la cabecera decia uno y la pestana
   seguia diciendo el anterior: con tres editores abiertos, ninguna pestana
   decia la verdad. */
function ponerTitulo(){
  $("#titulo").textContent = S.nombre || "flujo sin nombre";
  document.title = "Cognia - " + (S.nombre || "editor de flujos");
}
function pintarSelectorFlujos(){
  var s = $("#sel-flujo");
  s.textContent = "";
  var vistos = {}, i;
  var lista = S.flujos.slice();
  if(S.nombre && !lista.some(function(f){ return f.nombre === S.nombre; }))
    lista.unshift({nombre: S.nombre, n_nodos: nodos().length});
  for(i = 0; i < lista.length; i++){
    if(vistos[lista[i].nombre]) continue;
    vistos[lista[i].nombre] = 1;
    var o = document.createElement("option");
    o.value = lista[i].nombre;
    o.textContent = lista[i].nombre + " (" + (lista[i].n_nodos || 0) + ")";
    if(lista[i].nombre === S.nombre) o.selected = true;
    s.appendChild(o);
  }
}
$("#sel-flujo").onchange = function(){
  var n = $("#sel-flujo").value;
  if(n === S.nombre) return;
  cargarFlujo(n, null);
};
function cargarFlujo(nombre, v){
  if(!BASE){ toast("sin servidor: no se puede cambiar de flujo", true); return; }
  var ruta = "/api/flujo?nombre=" + encodeURIComponent(nombre) + (v ? "&v=" + v : "");
  var cambioDeFlujo = (nombre !== S.nombre);
  api(ruta).then(function(j){
    if(!j.ok){ toast(j.error || "no se pudo abrir", true); return; }
    S.nombre = aTexto(j.nombre) || nombre;
    S.descripcion = aTexto(j.descripcion);
    S.version = j.version || 0;
    S.flujo = j.flujo || {nombre: S.nombre, nodos: []};
    S.pos = (j.ui && j.ui.pos) || {};
    if(j.versiones) S.versiones = j.versiones;
    S.mirandoV = v || null;
    S.sel = {}; S.undo = []; S.redo = [];
    /* El historial del chat es DE ESTE flujo. Al cambiar de flujo hay que
       vaciarlo y resembrar la descripcion: si no, la burbuja del flujo
       anterior se queda ahi diciendo algo que ya no es verdad, y el
       modelo parece haber hablado de un flujo del que no sabe nada.
       Volver a otra VERSION del mismo flujo no lo vacia: es la misma
       conversacion. */
    if(cambioDeFlujo){
      $("#hist").textContent = "";
      if(S.descripcion) msg(S.descripcion, "ia", "descripcion del flujo");
    }
    cerrarProps();
    /* FRONTERA: el flujo que acaba de llegar viene de un fichero de disco. */
    sanearFlujo("el flujo \"" + S.nombre + "\"");
    ponerTitulo();
    pintarSelectorFlujos();
    pintarMirando();
    cambio();
    ajustar();
  }).catch(function(){ toast("sin conexion con Cognia", true); });
}
function recargarVersiones(){
  if(!BASE) return;
  api("/api/flujo?nombre=" + encodeURIComponent(S.nombre)).then(function(j){
    if(j.ok && j.versiones){ S.versiones = j.versiones; pintarTiempo(); }
  }).catch(function(){});
  recargarListaFlujos();
}
/* Guardar cambia el numero de nodos del flujo, y ese numero se pinta en el
   selector de la cabecera: sin este refresco el desplegable seguia diciendo
   "informe semanal (6)" con 7 nodos ya guardados en disco. Es barato y es la
   unica cifra de la pagina que puede quedarse mintiendo despues de guardar. */
function recargarListaFlujos(){
  if(!BASE) return;
  api("/api/flujos").then(function(j){
    if(j && j.ok && j.flujos){ S.flujos = j.flujos; pintarSelectorFlujos(); }
  }).catch(function(){});
}

/* =========================================================================
   LINEA DE TIEMPO DE VERSIONES
   ========================================================================= */
function pintarTiempo(){
  var c = $("#chips-v");
  c.textContent = "";
  if(!S.versiones.length){
    c.appendChild(div("vchip", "sin versiones todavia"));
    return;
  }
  for(var i = 0; i < S.versiones.length; i++){
    (function(v){
      var b = document.createElement("button");
      b.className = "vchip" + (v.existe === false ? " borrada" : "");
      b.setAttribute("aria-current", String(S.mirandoV ? v.v === S.mirandoV : !!v.actual));
      b.appendChild(div(null, "v" + v.v));
      /* aTexto y no (v.nota || ""): meta.versiones sale del JSON del
         flujo en disco y una nota que no sea texto reventaba .slice -- y
         con ella la barra de versiones ENTERA (mismo genero que el args
         dict). */
      var meta = div("n", (aTexto(v.nota) || "sin nota").slice(0, 28) + "  " +
                          aTexto(v.ts).replace("T", " ").slice(0, 16));
      b.appendChild(meta);
      b.onclick = function(){
        if(v.existe === false){ toast("esa version fue borrada: no queda cuerpo", true); return; }
        if(v.actual){ volverAActual(); return; }
        cargarFlujo(S.nombre, v.v);
        toast("viendo la version " + v.v + " en solo lectura: pulsa Restaurar para adoptarla");
      };
      c.appendChild(b);
    })(S.versiones[i]);
  }
}
function pintarMirando(){
  var m = $("#mirando");
  m.className = S.mirandoV ? "visible" : "";
  $("#b-guardar").disabled = !!S.mirandoV || S.soloLectura;
  pintarTiempo();
}
function volverAActual(){ cargarFlujo(S.nombre, null); }
$("#b-volver").onclick = volverAActual;
$("#b-restaurar").onclick = function(){
  if(!S.mirandoV) return;
  api("/api/restaurar", {method: "POST",
      body: {nombre: S.nombre, version: S.mirandoV, nota: "restaurada desde el editor"}})
    .then(function(j){
      if(!j.ok){ toast(j.error || "no se restauro", true); return; }
      toast("restaurada como version " + j.version);
      S.mirandoV = null;
      cargarFlujo(S.nombre, null);
    })
    .catch(function(){ toast("sin conexion con Cognia", true); });
};

/* =========================================================================
   PALETA DE NODOS
   ========================================================================= */
var plegadas = {};
function abrirPaleta(){
  $("#paleta").classList.add("abierto");
  pintarPaleta();
  $("#buscador").focus();
  $("#buscador").select();
}
function cerrarPaleta(){
  $("#paleta").classList.remove("abierto");
  S.pendiente = null;
}
function alternarPaleta(){
  if($("#paleta").classList.contains("abierto")) cerrarPaleta(); else abrirPaleta();
}
$("#buscador").addEventListener("input", function(){ pintarPaleta(); });
$("#buscador").addEventListener("keydown", function(e){
  if(e.key === "Enter"){
    var primero = $("#lista-paleta .pt");
    if(primero) primero.click();
  }
});
function pintarPaleta(){
  var cont = $("#lista-paleta");
  if(!cont) return;
  cont.textContent = "";
  var q = ($("#buscador").value || "").toLowerCase().trim();
  var cats = (S.cat.categorias || []).slice();
  var nds = (S.cat.nodos || []);
  if(!nds.length){
    cont.appendChild(div("interp", "El catalogo llega del servidor (/api/catalogo). " +
      "Sin conexion no hay paleta, pero el lienzo y el JSON siguen funcionando."));
    return;
  }
  var porCat = {}, i;
  for(i = 0; i < nds.length; i++){
    var n = nds[i];
    if(q && (n.nombre + " " + (n.descripcion || "")).toLowerCase().indexOf(q) < 0) continue;
    (porCat[n.categoria] = porCat[n.categoria] || []).push(n);
  }
  var orden = [];
  for(i = 0; i < cats.length; i++) orden.push(cats[i]);
  for(var k in porCat) if(!cats.some(function(c){ return c.id === k; }))
    orden.push({id: k, nombre: k, icono: "box", color: "#7d7d87"});
  var osc = document.documentElement.getAttribute("data-tema") === "oscuro";
  for(i = 0; i < orden.length; i++){
    var c = orden[i], items = porCat[c.id] || [];
    var col = (osc ? (c.color_osc || c.color) : c.color) || "#7d7d87";
    if(!items.length){
      /* Cajon vacio porque su FAMILIA esta apagada (pantalla, medios,
         escena, horizonte: 4 de 13 con la instalacion por defecto, o sea
         26 de las ~96 tools). Antes se saltaba y quedaba un hueco mudo que
         no decia nada; ahora se pinta plegado, atenuado y con el comando
         exacto que lo enciende, para que el dueno vea QUE MAS PODRIA TENER.
         Con el buscador escrito no se pintan: una busqueda no puede casar
         con tools que ni siquiera estan cargadas. */
      if(!q && c.apagada && c.como_encender)
        cont.appendChild(cajonApagado(c, col));
      continue;
    }
    var cajon = div("cat");
    var cab = div("cab");
    var fl = div("flecha", plegadas[c.id] ? "▸" : "▾");
    cab.appendChild(fl);
    var ic = document.createElementNS(NS, "svg");
    ic.setAttribute("class", "ico"); ic.setAttribute("viewBox", "0 0 24 24");
    ic.appendChild(icono(c.icono, col, 22));
    cab.appendChild(ic);
    cab.appendChild(div(null, c.nombre + " (" + items.length + ")"));
    (function(id){ cab.onclick = function(){ plegadas[id] = !plegadas[id]; pintarPaleta(); }; })(c.id);
    cajon.appendChild(cab);
    if(!plegadas[c.id] || q){
      for(var j = 0; j < items.length; j++) cajon.appendChild(itemPaleta(items[j], col));
    }
    cont.appendChild(cajon);
  }
  if(!cont.childNodes.length)
    cont.appendChild(div("interp", "Ningun nodo coincide con " + q));
}
function cajonApagado(c, col){
  /* Plegado de verdad (no hay nada que desplegar: sus tools no estan en el
     registro), atenuado, y con la linea de "como se enciende" que fabrica
     catalogo_nodos.paleta() con el nombre y el flag REALES de
     harness/familias.py -- nada de textos inventados aqui. */
  var cajon = div("cat apagada");
  var cab = div("cab");
  cab.appendChild(div("flecha", "▸"));
  var ic = document.createElementNS(NS, "svg");
  ic.setAttribute("class", "ico"); ic.setAttribute("viewBox", "0 0 24 24");
  ic.appendChild(icono(c.icono, col, 22));
  cab.appendChild(ic);
  /* Sin numero al lado: cuantas tools trae una familia apagada NO se sabe
     hasta cargarla (sus tools no estan en el registro), y poner un numero
     inventado seria peor que no ponerlo. */
  cab.appendChild(div(null, c.nombre));
  var p = div("pill", "apagada");
  p.style.display = "inline-block";
  cab.appendChild(p);
  cajon.appendChild(cab);
  cajon.appendChild(div("comoencender", c.como_encender));
  /* Que hace cada familia, en el tooltip: el "que" sale de familias.py. */
  var ques = [];
  for(var i = 0; i < (c.fuentes || []).length; i++){
    var f = c.fuentes[i];
    if(f && f.que) ques.push((f.familia || f.flag) + ": " + f.que);
  }
  if(ques.length) cajon.title = ques.join("\n");
  return cajon;
}
function itemPaleta(n, col){
  var f = div("pt" + (n.activa === false ? " apagada" : ""));
  f.draggable = true;
  var ic = document.createElementNS(NS, "svg");
  ic.setAttribute("class", "ico"); ic.setAttribute("viewBox", "0 0 24 24");
  ic.appendChild(icono(n.icono || "box", col, 22));
  f.appendChild(ic);
  var cuerpo = div(null);
  var t = div("tit");
  t.textContent = n.nombre;
  if(n.danger){
    var p = div("pill peligro", "danger");
    p.style.display = "inline-block";
    t.appendChild(p);
  }
  if(n.activa === false){
    var p2 = div("pill", n.flag ? ("apagada: " + n.flag) : "apagada");
    p2.style.display = "inline-block";
    t.appendChild(p2);
  }
  cuerpo.appendChild(t);
  cuerpo.appendChild(div("des", n.descripcion || ""));
  f.appendChild(cuerpo);
  f.addEventListener("dragstart", function(e){
    try{ e.dataTransfer.setData("text/plain", n.nombre); }catch(err){}
  });
  f.onclick = function(){
    if(S.soloLectura){ toast("solo lectura: sin conexion con Cognia", true); return; }
    var p = S.pendiente;
    var r = caja();
    var centro = aMundo(r.left + r.width / 2, r.top + r.height / 2);
    var x = p ? p.x : snap(centro.x - NW / 2), y = p ? p.y : snap(centro.y - NH / 2);
    anadirNodo(n.nombre, x, y, p || {});
    S.pendiente = null;
  };
  return f;
}

/* =========================================================================
   PANEL DE PROPIEDADES
   ========================================================================= */
function abrirProps(id){
  S.propsId = id;
  S.sel = {}; S.sel[id] = 1;
  $("#props").classList.add("abierto");
  pintar();
  pintarProps();
}
function cerrarProps(){
  S.propsId = null;
  $("#props").classList.remove("abierto");
}
function campo(etiqueta, control, ayuda){
  var d = div("campo");
  var l = document.createElement("label");
  l.textContent = etiqueta;
  d.appendChild(l);
  d.appendChild(control);
  if(ayuda) d.appendChild(div("ayuda", ayuda));
  return d;
}
function entrada(valor, tipo){
  var i = document.createElement(tipo === "textarea" ? "textarea" : "input");
  if(tipo && tipo !== "textarea") i.type = tipo;
  if(tipo === "textarea") i.rows = 3;
  if(tipo === "checkbox") i.checked = !!valor; else i.value = valor === undefined || valor === null ? "" : valor;
  if(tipo === "checkbox") i.style.width = "auto";
  return i;
}
function pintarProps(){
  var cont = $("#props");
  cont.textContent = "";
  var n = nodoPorId(S.propsId);
  if(!n){ cerrarProps(); return; }
  var f = ficha(n.tool);

  var h = document.createElement("h2");
  h.textContent = "Nodo";
  var x = document.createElement("button");
  x.textContent = "×";
  x.style.marginLeft = "auto";
  x.onclick = cerrarProps;
  h.appendChild(x);
  cont.appendChild(h);

  var err = div("", S.errValidar);
  err.id = "err-props";
  err.className = S.errValidar ? "visible" : "";
  cont.appendChild(err);

  /* id */
  var iId = entrada(n.id, "text");
  iId.id = "campo-id";
  iId.onchange = function(){
    var puesto = renombrar(n.id, iId.value);
    /* Si el id se rechazo (duplicado), el campo tiene que volver a la verdad:
       dejarlo con el texto tecleado haria creer que el cambio entro. */
    iId.value = puesto;
  };
  cont.appendChild(campo("id del nodo", iId,
    "Es el nombre con el que otros nodos leen su salida: {{" + n.id + "}}"));

  /* tool */
  var sTool = document.createElement("select");
  var nds = (S.cat.nodos || []);
  if(!nds.length || !ficha(n.tool)){
    var o0 = document.createElement("option");
    o0.value = n.tool; o0.textContent = n.tool;
    sTool.appendChild(o0);
  }
  for(var i = 0; i < nds.length; i++){
    var o = document.createElement("option");
    o.value = nds[i].nombre;
    o.textContent = nds[i].nombre + (nds[i].activa === false ? "  (apagada)" : "");
    if(nds[i].nombre === n.tool) o.selected = true;
    sTool.appendChild(o);
  }
  sTool.onchange = function(){
    instantanea();
    n.tool = sTool.value;
    cambio();
  };
  cont.appendChild(campo("tool", sTool, f ? (f.descripcion || "") :
    "esta tool no esta en el catalogo del servidor: al guardar, flows.validar la rechazara"));

  /* formulario generado a partir de params */
  var ps = paramsDe(n.tool);
  if(ps.length){
    var vals = camposDesdeArgs(n.tool, n.args);
    var bloque = div("bloque");
    var t2 = document.createElement("h2");
    t2.textContent = "Parametros";
    bloque.appendChild(t2);
    for(var j = 0; j < ps.length; j++){
      (function(p){
        var tipo = "text";
        var largo = /texto|mensaje|contenido|prompt|codigo|cuerpo|instruc/.test(p.nombre) ||
                    /texto largo|multilinea/.test(p.descripcion || "");
        if(p.tipo === "integer" || p.tipo === "number") tipo = "number";
        else if(p.tipo === "boolean") tipo = "checkbox";
        else if(largo) tipo = "textarea";
        var c = entrada(vals[p.nombre], tipo);
        c.dataset.param = p.nombre;
        c.oninput = function(){ recomponerArgs(n); };
        var eti = p.nombre + (p.requerido ? " *" : "") + (p.clave ? "  (clave)" : "");
        bloque.appendChild(campo(eti, c, p.descripcion || ""));
      })(ps[j]);
    }
    cont.appendChild(bloque);
  }

  /* args crudo: manda sobre el formulario */
  var iArgs = entrada(aTexto(n.args), "textarea");
  iArgs.id = "campo-args";
  iArgs.rows = 4;
  iArgs.oninput = function(){
    n.args = iArgs.value;
    pintar();
    validarPronto();
    guardarPosPronto();
  };
  cont.appendChild(campo("args (crudo)", iArgs,
    "Lo que se ejecuta es esto. El formulario de arriba solo lo compone."));

  /* interpolacion */
  var ayuda = div("bloque");
  var t3 = document.createElement("h2");
  t3.textContent = "Usar la salida de otro nodo";
  ayuda.appendChild(t3);
  ayuda.appendChild(div("interp",
    "Escribe {{id}} dentro de args y Cognia lo cambia por el resultado de ese nodo " +
    "antes de ejecutar. Pulsa uno para insertarlo donde tengas el cursor:"));
  var fila = div("interp");
  var ns = nodos();
  for(var q = 0; q < ns.length; q++){
    if(ns[q].id === n.id) continue;
    (function(id){
      var b = document.createElement("button");
      b.textContent = "{{" + id + "}}";
      b.onclick = function(){ insertarEnArgs(n, "{{" + id + "}}"); };
      fila.appendChild(b);
    })(ns[q].id);
  }
  if(!fila.childNodes.length) fila.appendChild(div("interp", "(no hay otros nodos todavia)"));
  ayuda.appendChild(fila);
  cont.appendChild(ayuda);

  /* wires */
  var bw = div("bloque");
  var t4 = document.createElement("h2");
  t4.textContent = "Va a";
  bw.appendChild(t4);
  var ws = n.wires || [];
  for(var w = 0; w < ws.length; w++){
    (function(destino){
      var chip = div("chip-w");
      chip.appendChild(div(null, destino));
      var b = document.createElement("button");
      b.textContent = "×";
      b.onclick = function(){
        instantanea();
        n.wires = (n.wires || []).filter(function(z){ return z !== destino; });
        cambio();
      };
      chip.appendChild(b);
      bw.appendChild(chip);
    })(ws[w]);
  }
  var sAdd = document.createElement("select");
  var o1 = document.createElement("option");
  o1.value = ""; o1.textContent = "conectar a...";
  sAdd.appendChild(o1);
  for(var z = 0; z < ns.length; z++){
    if(ns[z].id === n.id || ws.indexOf(ns[z].id) >= 0) continue;
    var oz = document.createElement("option");
    oz.value = ns[z].id; oz.textContent = ns[z].id;
    sAdd.appendChild(oz);
  }
  sAdd.onchange = function(){
    if(!sAdd.value) return;
    instantanea();
    n.wires = n.wires || [];
    n.wires.push(sAdd.value);
    cambio();
  };
  bw.appendChild(sAdd);
  cont.appendChild(bw);

  /* control de flujo */
  var bc = div("bloque");
  var t5 = document.createElement("h2");
  t5.textContent = "Control de flujo";
  bc.appendChild(t5);
  var iSalt = entrada(n.saltar_si || "", "text");
  iSalt.onchange = function(){
    instantanea();
    if(iSalt.value) n.saltar_si = iSalt.value; else delete n.saltar_si;
    cambio();
  };
  bc.appendChild(campo("saltar_si", iSalt,
    "El nodo se SALTA si este texto aparece en alguna salida anterior. " +
    "Un nodo sin padres no ve ninguna salida, asi que nunca se salta."));
  var tres = div("tres");
  var iRe = entrada(n.reintentos === undefined ? "" : n.reintentos, "number");
  iRe.onchange = function(){
    instantanea();
    var v = parseInt(iRe.value, 10);
    if(v > 0) n.reintentos = v; else delete n.reintentos;
    cambio();
  };
  var iTo = entrada(n.timeout_s === undefined ? "" : n.timeout_s, "number");
  iTo.onchange = function(){
    instantanea();
    var v = parseFloat(iTo.value);
    if(v > 0) n.timeout_s = v; else delete n.timeout_s;
    cambio();
  };
  var d1 = campo("reintentos", iRe), d2 = campo("timeout_s", iTo);
  tres.appendChild(d1); tres.appendChild(d2);
  bc.appendChild(tres);
  var iMod = entrada(n.modelo || "", "text");
  iMod.onchange = function(){
    instantanea();
    if(iMod.value) n.modelo = iMod.value; else delete n.modelo;
    cambio();
  };
  bc.appendChild(campo("modelo (opcional)", iMod, "solo si este paso pide un modelo concreto"));
  cont.appendChild(bc);

  var bb = document.createElement("button");
  bb.textContent = "Borrar este nodo";
  bb.style.marginTop = "12px";
  bb.onclick = function(){ S.sel = {}; S.sel[n.id] = 1; borrarSeleccion(); };
  cont.appendChild(bb);
}
function insertarEnArgs(n, texto){
  var ta = $("#campo-args");
  if(!ta) return;
  var i = ta.selectionStart === null ? ta.value.length : ta.selectionStart;
  ta.value = ta.value.slice(0, i) + texto + ta.value.slice(ta.selectionEnd || i);
  n.args = ta.value;
  ta.focus();
  ta.selectionStart = ta.selectionEnd = i + texto.length;
  pintar();
  validarPronto();
}

/* --------- args <-> formulario (convencion de tools.armar_args) --------- */
function camposDesdeArgs(tool, args){
  var ps = paramsDe(tool), vals = {}, texto = String(args || ""), i;
  var claves = [];
  for(i = 0; i < ps.length; i++) if(ps[i].clave) claves.push(ps[i].nombre);
  if(claves.length){
    var re = new RegExp("(?:\\s\\|\\s|\\s)(" + claves.join("|") + ")=", "");
    var m = re.exec(texto);
    if(m){
      var cola = texto.slice(m.index);
      texto = texto.slice(0, m.index);
      var re2 = new RegExp("(?:\\s\\|\\s|\\s)(" + claves.join("|") + ")=([^|]*)", "g"), mm;
      while((mm = re2.exec(cola))) vals[mm[1]] = mm[2].trim();
    }
  }
  var pos = [];
  for(i = 0; i < ps.length; i++) if(!ps[i].clave) pos.push(ps[i].nombre);
  var piezas = texto.split(" | ");
  for(i = 0; i < pos.length; i++){
    if(i >= piezas.length) break;
    vals[pos[i]] = (i === pos.length - 1 ? piezas.slice(i).join(" | ") : piezas[i]).trim();
  }
  return vals;
}
function recomponerArgs(n){
  var ps = paramsDe(n.tool), pos = [], claves = [], i;
  var campos = document.querySelectorAll("#props [data-param]");
  var vals = {};
  for(i = 0; i < campos.length; i++){
    var c = campos[i];
    vals[c.dataset.param] = c.type === "checkbox" ? (c.checked ? "true" : "") : c.value;
  }
  for(i = 0; i < ps.length; i++){
    var p = ps[i], v = vals[p.nombre];
    if(v === undefined || v === "") continue;
    if(p.clave) claves.push(p.nombre + "=" + v); else pos.push(v);
  }
  /* Misma convencion que tools.armar_args: posicionales unidos con " | " y
     las claves como nombre=valor. 'ejecutar' exige el pipe delante de CADA
     clave, porque su parser confunde 'timeout=' con un token del comando. */
  var sep = n.tool === "ejecutar" ? " | " : " ";
  var args = pos.join(" | ");
  if(claves.length) args += sep + claves.join(sep);
  n.args = args;
  var ta = $("#campo-args");
  if(ta) ta.value = args;
  pintar();
  validarPronto();
  guardarPosPronto();
}

/* =========================================================================
   CHAT
   ========================================================================= */
function msg(texto, quien, meta){
  var d = div("msg " + quien);
  d.textContent = texto;
  if(meta) d.appendChild(div("meta", meta));
  $("#hist").appendChild(d);
  $("#hist").scrollTop = $("#hist").scrollHeight;
  return d;
}
function pintarSugerencias(){
  var c = $("#sugerencias");
  c.textContent = "";
  for(var i = 0; i < SUGERENCIAS.length; i++){
    (function(s){
      var b = document.createElement("button");
      b.textContent = s;
      b.onclick = function(){ $("#msg").value = s; enviarChat(); };
      c.appendChild(b);
    })(SUGERENCIAS[i]);
  }
}
function enviarChat(){
  var texto = ($("#msg").value || "").trim();
  if(!texto) return;
  if(!BASE || S.soloLectura){
    msg("Sin conexion con Cognia: el chat necesita el servidor local.", "mal");
    return;
  }
  msg(texto, "yo");
  $("#msg").value = "";
  $("#b-enviar").disabled = true;
  /* El backend local tarda decenas de segundos. Sin los segundos corriendo
     parece colgado: es un modo de fallo conocido de esta casa. */
  var t0 = Date.now();
  $("#pensando").className = "visible";
  $("#pensando-txt").textContent = "pensando... 0 s";
  if(S.reloj) clearInterval(S.reloj);
  S.reloj = setInterval(function(){
    $("#pensando-txt").textContent = "pensando... " +
      Math.round((Date.now() - t0) / 1000) + " s";
  }, 500);
  function fin(){
    if(S.reloj){ clearInterval(S.reloj); S.reloj = null; }
    $("#pensando").className = "";
    /* Si la peticion murio por caida, api() ya degrado ANTES de este catch:
       reactivar Enviar aqui a secas dejaba un boton vivo en una pagina de
       solo-lectura. Cuando vuelva la conexion lo rearma rearmar(). */
    $("#b-enviar").disabled = S.soloLectura;
  }
  api("/api/chat", {method: "POST",
      body: {nombre: S.nombre, flujo: S.flujo, mensaje: texto}})
    .then(function(j){
      fin();
      var meta = (j.ms !== undefined ? Math.round(j.ms) + " ms" : "") +
                 (j.modelo ? "  ·  " + j.modelo : "");
      if(!j.ok || !j.flujo){
        /* "no hice nada, y por esto" NO es un fallo: el modelo puede haber
           decidido que la instruccion ya estaba cumplida, y eso es la
           respuesta buena. Se distingue por ESTRUCTURA, no por el texto:
           en flujo_ia solo el camino _igual() rellena `resumen` cuando ok
           es false (_fallo lo deja vacio). Pintarlo en rojo hacia que la
           respuesta correcta pareciera un error, y ademas se perdia la
           explicacion, que era lo unico util del turno. */
        var deliberado = !!(j.resumen || "").trim();
        var texto = deliberado
          ? (j.resumen + "  (" + (j.motivo || "sin cambios") + ")")
          : (j.motivo || j.error || "el modelo no devolvio un flujo valido");
        msg(texto, deliberado ? "ia" : "mal", meta);
        return;
      }
      instantanea();
      S.flujo = j.flujo;
      /* FRONTERA: lo que devuelve el modelo pasa por flows.validar en el
         servidor, pero el saneo aqui cuesta nada y no depende de eso. */
      sanearFlujo("el modelo");
      /* Se conservan las posiciones de los ids que sobreviven; los nuevos
         caen por topologia. Asi un cambio del modelo no baraja el lienzo. */
      var vivos = {};
      for(var i = 0; i < (S.flujo.nodos || []).length; i++) vivos[S.flujo.nodos[i].id] = 1;
      for(var k in S.pos) if(!vivos[k]) delete S.pos[k];
      S.sel = {};
      cerrarProps();
      cambio();
      animarEntrada();
      msg(j.resumen || "flujo actualizado", "ia", meta);
    })
    .catch(function(){
      fin();
      msg("sin conexion con Cognia", "mal");
    });
}
function animarEntrada(){
  /* Transicion suave: el lienzo se atenua y vuelve. Barato y evita que el
     cambio del modelo parezca un parpadeo sin causa. */
  svg.style.transition = "opacity .18s ease";
  svg.style.opacity = "0.25";
  setTimeout(function(){ svg.style.opacity = "1"; }, 190);
}
$("#b-enviar").onclick = enviarChat;
$("#msg").addEventListener("keydown", function(e){
  if(e.key === "Enter" && (e.ctrlKey || e.metaKey)){ e.preventDefault(); enviarChat(); }
});

/* =========================================================================
   ATAJOS
   ========================================================================= */
document.addEventListener("keydown", function(e){
  if(e.key === " " && !enCampo()){ S.espacio = true; svg.classList.add("panear"); }
  var ctrl = e.ctrlKey || e.metaKey;
  if(e.key === "Escape"){
    cerrarVelos();
    cerrarPaleta();
    cerrarProps();
    S.conectando = null; S.marquee = null; S.pendiente = null;
    gExtra.textContent = "";
    pintar();
    return;
  }
  if(ctrl && (e.key === "s" || e.key === "S")){
    e.preventDefault();
    if(!$("#b-guardar").disabled) $("#b-guardar").click();
    return;
  }
  if(enCampo()) return;   /* sin esto, teclear "d" en un campo apaga un nodo */
  if(e.key === "Tab"){ e.preventDefault(); alternarPaleta(); return; }
  if(ctrl && (e.key === "a" || e.key === "A")){
    e.preventDefault();
    var ns = nodos();
    S.sel = {};
    for(var i = 0; i < ns.length; i++) S.sel[ns[i].id] = 1;
    pintar();
    return;
  }
  if(ctrl && (e.key === "c" || e.key === "C")){ copiar(); return; }
  if(ctrl && (e.key === "v" || e.key === "V")){ pegar(); return; }
  if(ctrl && (e.key === "z" || e.key === "Z")){
    e.preventDefault();
    if(e.shiftKey) rehacer(); else deshacer();
    return;
  }
  if(ctrl && (e.key === "y" || e.key === "Y")){ e.preventDefault(); rehacer(); return; }
  if(e.key === "Delete" || e.key === "Backspace"){
    e.preventDefault();
    if(S.aristaViva){ $("#b-arista-borrar").click(); return; }
    borrarSeleccion();
    return;
  }
  if(e.key === "F2"){
    e.preventDefault();
    var id = idsSel()[0];
    if(!id) return;
    abrirProps(id);
    var c = $("#campo-id");
    if(c){ c.focus(); c.select(); }
    return;
  }
  if(e.key === "d" || e.key === "D"){
    var ids = idsSel();
    if(!ids.length || S.soloLectura) return;
    instantanea();
    var padres = padresDe();
    var aviso = false;
    for(var j = 0; j < ids.length; j++){
      var n = nodoPorId(ids[j]);
      if(!n) continue;
      if(n.saltar_si) delete n.saltar_si;
      else{
        n.saltar_si = "RESULTADO";
        if(!(padres[n.id] || []).length) aviso = true;
      }
    }
    cambio();
    toast(aviso ? "deshabilitar es saltar_si: un nodo SIN padres no ve ninguna salida " +
                  "previa, asi que se ejecutara igual"
                : "saltar_si cambiado en " + ids.length + " nodos");
    return;
  }
  if(e.key === "0"){ ajustar(); return; }
  if(e.key === "1"){ zoomA(1); return; }
  if(e.key === "+" || e.key === "="){ zoomA(S.k * 1.2); return; }
  if(e.key === "-" || e.key === "_"){ zoomA(S.k / 1.2); return; }
  if(e.key === "?"){ abrirVelo("velo-hoja"); return; }
});
document.addEventListener("keyup", function(e){
  if(e.key === " "){ S.espacio = false; svg.classList.remove("panear"); }
});
function pintarHoja(){
  var c = $("#hoja-cuerpo");
  c.textContent = "";
  for(var i = 0; i < ATAJOS.length; i++){
    var h = document.createElement("h4");
    h.textContent = ATAJOS[i][0];
    c.appendChild(h);
    var t = document.createElement("table");
    for(var j = 0; j < ATAJOS[i][1].length; j++){
      var tr = document.createElement("tr");
      var td1 = document.createElement("td");
      td1.textContent = ATAJOS[i][1][j][0];
      var td2 = document.createElement("td");
      td2.textContent = ATAJOS[i][1][j][1];
      tr.appendChild(td1); tr.appendChild(td2);
      t.appendChild(tr);
    }
    c.appendChild(t);
  }
}

/* =========================================================================
   ARRANQUE
   ========================================================================= */
window.addEventListener("resize", function(){ aplicarVista(); pintarMini(); });

/* ARRANCAR VA EN DOS MITADES CON RED DE SEGURIDAD CADA UNA.
   Antes era un solo bloque sin proteger y una excepcion en el pintado (la
   del args dict, medida el 2026-08-29) mataba TODO lo que venia despues,
   incluido el primer fetch: la pagina se quedaba con medio lienzo, la barra
   de versiones vacia y el indicador clavado en "conectando" PARA SIEMPRE
   -- indistinguible de un servidor lento, sin un solo mensaje. Ahora:
     - si revienta el PINTADO, la red sigue arrancando (el indicador dice la
       verdad y el editor sigue hablando con Cognia), y
     - el motivo real sale en el banner ambar, no solo en la consola.
   Que la pagina quede a medias es aceptable; que no lo diga, no. */
function arrancar(){
  try{ arrancarPintado(); }
  catch(err){ fallo("montar el editor", err); }
  try{ arrancarRed(); }
  catch(err){
    fallo("hablar con Cognia", err);
    /* Sin esto el indicador se queda en "conectando" para siempre. */
    try{ marcarOnline(false); }catch(e){}
  }
}

function arrancarPintado(){
  montarSvg();
  indexar();
  /* Lo PRIMERO: los datos embebidos son datos de disco y pueden traer
     cualquier tipo (ver la cabecera de la defensa de tipos). Va aqui y no
     junto a var S porque avisar necesita el DOM y su propio estado ya
     inicializados. */
  sanearFlujo("los datos iniciales");
  ponerTitulo();
  pintarSelectorFlujos();
  pintarSugerencias();
  pintarHoja();
  tema(document.documentElement.getAttribute("data-tema") || "claro");
  pintar();
  pintarTiempo();
  ajustar();
  aplicarVista();
  if(S.descripcion) msg(S.descripcion, "ia", "descripcion del flujo");
  /* Los avisos que YA venian embebidos en el HTML: un flujo ilegible deja
     el lienzo vacio y el catalogo caido deja la paleta vacia. Sin pintarlos,
     las dos cosas se ven exactamente igual que "aqui no habia nada". */
  avisar(D.aviso, "servidor");
  if(D.catalogo) avisar(D.catalogo.aviso, "catalogo de nodos");
}

function arrancarRed(){
  if(!BASE){
    degradar();
    return;
  }
  /* El primer fetch decide si hay servidor. La pagina ya esta pintada con
     los datos embebidos, asi que un fallo aqui degrada, no vacia. */
  api("/api/flujos").then(function(j){
    if(j && j.ok && j.flujos){ S.flujos = j.flujos; pintarSelectorFlujos(); }
    if(j && j.aviso) avisar(j.aviso, "servidor");
    marcarOnline(true);
    if(!(S.cat.nodos || []).length){
      api("/api/catalogo").then(function(c){
        /* El aviso va ANTES del ok: cuando el catalogo revienta, 'aviso' es
           lo unico que explica por que la paleta se queda vacia. */
        if(c) avisar(c.aviso, "catalogo de nodos");
        if(c && c.ok){
          S.cat = {categorias: c.categorias || [], nodos: c.nodos || []};
          indexar();
          pintar();
          pintarPaleta();
        }
      }).catch(function(){});
    }
    validarAhora();
  }).catch(function(){ marcarOnline(false); });
}
arrancar();
</script></body></html>"""


def _normalizar(datos: dict) -> dict:
    """`datos` con todas las claves puestas: la pagina nunca ve un `undefined`.

    Se acepta un dict vacio a proposito: un test puede llamar a `render({})` y
    la pagina tiene que pintar el lienzo vacio, no reventar.
    """
    d = dict(datos or {})
    flujo = d.get("flujo")
    if not isinstance(flujo, dict):
        flujo = {}
    nodos = flujo.get("nodos")
    if not isinstance(nodos, list):
        nodos = []
    nombre = str(d.get("nombre") or flujo.get("nombre") or "")
    ui = d.get("ui")
    pos = ui.get("pos") if isinstance(ui, dict) else None
    cat = d.get("catalogo")
    if not isinstance(cat, dict):
        cat = {}
    salida = {
        "nombre": nombre,
        "descripcion": str(d.get("descripcion") or ""),
        "version": int(d.get("version") or 0),
        "flujo": {"nombre": str(flujo.get("nombre") or nombre), "nodos": nodos},
        "ui": {"pos": pos if isinstance(pos, dict) else {}},
        "versiones": list(d.get("versiones") or []),
        "flujos": list(d.get("flujos") or []),
        # `aviso` EN LOS DOS NIVELES. El servidor lo emite a proposito en dos
        # sitios (`flujoteca_editor._datos_pagina` cuando el flujo no se puede
        # leer, y `_catalogo` cuando `catalogo_nodos.paleta()` revienta) y
        # esta whitelist cerrada lo tiraba a la basura: el editor abria con
        # la paleta vacia o el lienzo en blanco y CERO explicacion. Va como
        # cadena siempre puesta, igual que el resto: la pagina no ve
        # `undefined` nunca.
        "aviso": str(d.get("aviso") or ""),
        "catalogo": {"categorias": list(cat.get("categorias") or []),
                     "nodos": list(cat.get("nodos") or []),
                     "aviso": str(cat.get("aviso") or "")},
    }
    if isinstance(d.get("layout"), dict):
        salida["layout"] = d["layout"]
    return salida


_RX_PLACEHOLDER = _re.compile("__TITLE__|__BASE__|__TOKEN__|__DATA__")


def _neutralizar_placeholders(texto: str) -> str:
    """Rompe cualquier `__XXX__` del texto del DUENO antes de que se sustituya.

    EL ATAQUE (reproducido en vivo el 2026-08-29, rev_seguridad hallazgo 2).
    El nombre del flujo lo pone el dueno y entra en el `<title>` por el
    placeholder `__TITLE__`. Con los reemplazos ENCADENADOS y `__TITLE__` el
    primero, el texto que ese primer replace acababa de insertar lo volvia a
    mirar el replace siguiente:

        flujo llamado "__TOKEN__" -> <title>Cognia ... SECRETO-abc123</title>
        flujo llamado "__BASE__"  -> <title>Cognia ... http://127.0.0.1:5555</title>
        flujo llamado "__DATA__"  -> el JSON entero dentro del <title>

    El caso grave es el primero: el token de un solo arranque acaba en el
    titulo de la pestana y, por tanto, en el HISTORIAL y en los marcadores
    del navegador -- persistido en disco, fuera del ciclo de vida "de un solo
    arranque" que este modulo promete.

    Aqui van CINTURON Y TIRANTES, porque cada uno solo cubre la mitad:
      - esta funcion mata el patron en el dato del dueno (`__TOKEN__` sale
        como `_ _TOKEN__`, que ya no casa), y
      - `render()` sustituye los cuatro placeholders DE UNA SOLA PASADA, asi
        que lo insertado no se vuelve a leer.
    La de la pasada unica es la que sigue protegiendo cuando alguien anada un
    quinto placeholder y se olvide de llamar a esta; la de esta funcion es la
    que protege si alguien vuelve a encadenar `.replace()`.

    Se rompe metiendo un espacio entre los dos guiones bajos de APERTURA
    (`__TOKEN__` -> `_ _TOKEN__`): el nombre sigue siendo reconocible para el
    dueno -- no se borra ni se censura nada -- y ya no es el literal que
    busca el sustituidor. Todo ASCII a proposito: un caracter invisible seria
    mas bonito y menos auditable.
    """
    return _re.sub(r"__(?=[A-Za-z0-9_]*__)", "_ _", str(texto or ""))


def render(datos: dict, *, base: str, token: str) -> str:
    """La pagina lista para servir, con los datos iniciales ya embebidos.

    `datos` es el mismo dict que devuelve `/api/flujo` mas las claves
    `flujos` y `catalogo` (la forma exacta esta en la cabecera del modulo).

    EL JSON ESCAPA TODOS LOS `<` (2026-08-29). Escapar solo el cierre `</`
    NO basta, y esto se MIDIO en Chromium: `<!--` y `<script` meten al
    tokenizador de HTML en `script data escaped`, y en ese estado el
    `</script>` de la plantilla ya no cierra el bloque -- se traga el resto
    del documento, el JS entero muere por error de sintaxis y la pagina
    queda con la barra de herramientas pintada y CERO nodos. El caso no es
    un ataque: es un flujo normal que escribe una pagina web
    (`escribir_archivo` con `args = "pagina.html | <!--<script>..."`), y el
    dueno ve "un flujo vacio", no "una pagina rota", asi que no sospecha del
    contenido de un arg. `>` y `&` se escapan de paso, por barrer. Los tres
    caracteres estan siempre DENTRO de cadenas (la sintaxis JSON no los usa),
    `\\u003c` es JSON valido y literal JS valido, y `JSON.parse` los devuelve
    identicos: el dato no cambia ni un byte. NO SIMPLIFICAR a `.replace("</",
    "<\\\\/")`, que es justo la version que estaba rota.

    SIN ORDEN DE REEMPLAZOS: los cuatro placeholders se sustituyen de UNA
    PASADA con `_RX_PLACEHOLDER`, asi que da igual cual va antes y ninguno
    puede reinterpretar lo que otro acaba de insertar. Ademas el titulo pasa
    por `_neutralizar_placeholders` (ver ahi el ataque completo).
    """
    limpios = _normalizar(datos)
    crudo = (json.dumps(limpios, ensure_ascii=False)
             .replace("&", "\\u0026")
             .replace("<", "\\u003c")
             .replace(">", "\\u003e"))
    # El nombre del flujo es DATO DEL DUENO: se neutraliza ANTES de escapar.
    titulo = _html.escape(
        "Cognia - editor de flujos" +
        (" - " + _neutralizar_placeholders(limpios["nombre"])
         if limpios["nombre"] else ""),
        quote=True)
    # La base nunca lleva barra final: el cliente concatena "/api/...".
    base_limpia = _html.escape(str(base or "").rstrip("/"), quote=True)
    token_limpio = _html.escape(str(token or ""), quote=True)
    trozos = {"__TITLE__": titulo, "__BASE__": base_limpia,
              "__TOKEN__": token_limpio, "__DATA__": crudo}
    return _RX_PLACEHOLDER.sub(lambda m: trozos[m.group(0)], HTML)


if __name__ == "__main__":  # pragma: no cover - ayuda manual
    import sys
    demo = {
        "nombre": "demo",
        "descripcion": "flujo de prueba del editor",
        "version": 1,
        "flujo": {"nombre": "demo", "nodos": [
            {"id": "leer", "tool": "leer_archivo", "args": "notas.md", "wires": ["resumir"]},
            {"id": "resumir", "tool": "resumir", "args": "{{leer}}", "wires": ["escribir"]},
            {"id": "escribir", "tool": "escribir_archivo",
             "args": "informe.md | {{resumir}}", "wires": [], "reintentos": 2},
        ]},
        "ui": {"pos": {}},
        "versiones": [{"v": 1, "ts": "2026-08-29T10:00:00", "nota": "inicial",
                       "n_nodos": 3, "actual": True, "existe": True}],
        "flujos": [{"nombre": "demo", "n_nodos": 3}],
        "catalogo": {"categorias": [], "nodos": []},
    }
    destino = sys.argv[1] if len(sys.argv) > 1 else "editor_demo.html"
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(render(demo, base="", token=""))
    print(destino)
