# -*- coding: utf-8 -*-
"""tests/test_editor_html_js.py -- EJECUTAR el JavaScript del editor, no mirarlo.

POR QUE EXISTE (2026-08-29)
---------------------------
La verificacion en Chromium encontro dos ROJOS que la suite entera (13.189
tests) no cazaba, y el verificador escribio el motivo con todas las letras:

    "Ninguno de los dos ROJOS lo caza esta suite: los dos son de
     comportamiento del navegador y NO HAY NI UN TEST QUE EJECUTE EL JS."

Los dos rojos:
  A. el doble clic sobre un nodo NUNCA abria el panel de propiedades (atajo
     documentado en la hoja de ayuda de la propia pagina), por dos causas
     independientes: `pintar()` reconstruia el nodo dentro del `pointerdown`
     -asi que el elemento del primer clic ya no existia en el segundo- y
     `setPointerCapture` redirigia el evento al `<svg>`, con lo que
     `e.target.closest(".nodo")` daba null.
  B. un `args` dict tumbaba el arranque ENTERO de la pagina
     (`(n.args || "").replace is not a function`): medio lienzo, minimapa en
     blanco, barra de versiones vacia y el indicador clavado en "conectando"
     PARA SIEMPRE, sin banner ni aviso.

Los tests que habia son de Python: comprueban que el HTML *contiene* ciertas
cadenas. Con eso se puede escribir `.replace()` sobre un dict y aprobar. Este
fichero cierra ese hueco por el unico camino que lo cierra: EJECUTA el
JavaScript de la pagina en node, con un DOM minimo escrito a mano, y ademas
DISPARA eventos (pointerdown) para medir comportamiento, no texto.

QUE CUBRE Y QUE NO -- honestidad primero
----------------------------------------
CUBRE (y falla sin los arreglos de hoy, comprobado quitandolos):
  - `arrancar()` de punta a punta con un flujo venenoso (args dict, args
    numero, args None, wires en texto, id numerico, nota de version dict):
    que no lanza, que pinta TODOS los nodos, que el titulo se pone y que el
    aviso ambar explica lo que se convirtio.
  - el doble clic: dos `pointerdown` seguidos sobre el mismo nodo abren el
    panel; uno solo no; dos separados en el tiempo, tampoco.
  - que el doble clic sigue funcionando DESPUES de un repintado (la causa 1)
    y sin depender de `e.target` (la causa 2: se dispara sobre un hijo).
  - las funciones puras del normalizador (`aTexto`, `normalizarFlujo`).
  - los dos menores: `document.title` al cambiar de flujo y el refresco de la
    lista de flujos tras guardar.
NO CUBRE (y por eso el e2e de Playwright de abajo, y por eso se sigue
verificando a mano en un navegador de verdad):
  - layout, CSS, z-index, scroll, foco: el DOM de mentira no pinta nada. El
    fallo "el puerto quedaba tapado por la paleta" NO lo caza esto.
  - la emision REAL de `dblclick`/`click` por el navegador: aqui se disparan
    `pointerdown` a mano. Que el navegador los emita o no es justo lo que
    hacia fallar el atajo antes, y por eso el arreglo NO depende de ellos.
  - el `setPointerCapture` de verdad (aqui es un no-op), los gestos con
    raton fisico, el arrastre con inercia, y todo lo que pase en el servidor.
  - cualquier navegador que no sea el motor de JS de node.

El DOM de mentira es DELIBERADAMENTE tonto: si algun dia el editor necesita
una API del DOM que no esta aqui, el test peta con un `TypeError` claro y se
anade. Es preferible a un jsdom que no esta instalado (comprobado: no lo
esta) y a no ejecutar nada, que es donde estabamos.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from cognia.agent import editor_html

NODE = shutil.which("node")
sin_node = pytest.mark.skipif(NODE is None, reason="hace falta node para ejecutar el JS")


# ---------------------------------------------------------------------------
# EL ARNES: un DOM minimo en node donde corre el <script> de la pagina tal cual
# ---------------------------------------------------------------------------
ARNES = r"""
"use strict";
var fs = require("fs");
var vm = require("vm");

var html = fs.readFileSync(process.argv[2], "utf8");
var prueba = fs.readFileSync(process.argv[3], "utf8");

var VACIOS = {input: 1, br: 1, img: 1, meta: 1, hr: 1, link: 1, source: 1};

function Elem(tag){
  this.tagName = String(tag || "").toUpperCase();
  this.attrs = {};
  this.children = [];
  this.parentNode = null;
  this.dataset = {};
  this.style = {};
  this._texto = "";
  this._ls = {};
  this.hidden = false;
  this.value = "";
  this.checked = false;
  this.disabled = false;
  var yo = this;
  function clases(){
    var c = yo.attrs["class"];
    return c ? String(c).split(/\s+/).filter(Boolean) : [];
  }
  this.classList = {
    add: function(){
      var c = clases();
      for(var i = 0; i < arguments.length; i++)
        if(c.indexOf(arguments[i]) < 0) c.push(arguments[i]);
      yo.attrs["class"] = c.join(" ");
    },
    remove: function(){
      var fuera = Array.prototype.slice.call(arguments);
      yo.attrs["class"] = clases().filter(function(x){ return fuera.indexOf(x) < 0; }).join(" ");
    },
    contains: function(x){ return clases().indexOf(x) >= 0; },
    toggle: function(x){ if(clases().indexOf(x) < 0) this.add(x); else this.remove(x); }
  };
}
Object.defineProperty(Elem.prototype, "className", {
  get: function(){ return this.attrs["class"] || ""; },
  set: function(v){ this.attrs["class"] = String(v); }
});
Object.defineProperty(Elem.prototype, "id", {
  get: function(){ return this.attrs.id || ""; },
  set: function(v){ this.attrs.id = String(v); }
});
Object.defineProperty(Elem.prototype, "textContent", {
  get: function(){
    var s = this._texto;
    for(var i = 0; i < this.children.length; i++) s += this.children[i].textContent;
    return s;
  },
  set: function(v){ this.children = []; this._texto = v === null || v === undefined ? "" : String(v); }
});
Object.defineProperty(Elem.prototype, "innerHTML", {
  get: function(){ return this._html || ""; },
  set: function(v){ this._html = String(v); }
});
Object.defineProperty(Elem.prototype, "firstChild", {
  get: function(){ return this.children[0] || null; }
});
Object.defineProperty(Elem.prototype, "childNodes", {
  get: function(){ return this.children; }
});
Elem.prototype.setAttribute = function(k, v){ this.attrs[k] = String(v); };
Elem.prototype.getAttribute = function(k){ return k in this.attrs ? this.attrs[k] : null; };
Elem.prototype.removeAttribute = function(k){ delete this.attrs[k]; };
Elem.prototype.hasAttribute = function(k){ return k in this.attrs; };
Elem.prototype.appendChild = function(c){ c.parentNode = this; this.children.push(c); return c; };
Elem.prototype.getBoundingClientRect = function(){
  return {left: 0, top: 0, width: 1200, height: 800, right: 1200, bottom: 800, x: 0, y: 0};
};
Elem.prototype.setPointerCapture = function(){};
Elem.prototype.releasePointerCapture = function(){};
Elem.prototype.focus = function(){ DOC.activeElement = this; };
Elem.prototype.blur = function(){ DOC.activeElement = null; };
Elem.prototype.select = function(){};
Elem.prototype.addEventListener = function(t, fn){ (this._ls[t] = this._ls[t] || []).push(fn); };
Elem.prototype.removeEventListener = function(t, fn){
  var l = this._ls[t] || [];
  var i = l.indexOf(fn);
  if(i >= 0) l.splice(i, 1);
};
Elem.prototype.dispatchEvent = function(ev){
  ev.target = ev.target || this;
  var nodo = this;
  while(nodo){
    var l = (nodo._ls[ev.type] || []).slice();
    for(var i = 0; i < l.length; i++) l[i].call(nodo, ev);
    var prop = nodo["on" + ev.type];
    if(typeof prop === "function") prop.call(nodo, ev);
    nodo = nodo.parentNode;
  }
  return true;
};
Elem.prototype.closest = function(sel){
  var n = this;
  while(n){ if(casa(n, sel)) return n; n = n.parentNode; }
  return null;
};
Elem.prototype.querySelector = function(s){ return buscar(this, s)[0] || null; };
Elem.prototype.querySelectorAll = function(s){ return buscar(this, s); };

/* Selectores soportados: #id, .clase (encadenadas), etiqueta, [attr] y
   descendencia con espacios. Nada mas: si hace falta otro, salta aqui. */
function casa(el, sel){
  var partes = sel.match(/#[\w-]+|\.[\w-]+|\[[\w-]+\]|^[a-zA-Z][\w-]*/g) || [];
  for(var i = 0; i < partes.length; i++){
    var p = partes[i];
    if(p[0] === "#"){ if(el.attrs.id !== p.slice(1)) return false; }
    else if(p[0] === "."){ if(!el.classList.contains(p.slice(1))) return false; }
    else if(p[0] === "["){
      var a = p.slice(1, -1);
      var clave = a.replace(/^data-/, "").replace(/-(\w)/g, function(m, c){ return c.toUpperCase(); });
      if(!(a in el.attrs) && el.dataset[clave] === undefined) return false;
    }
    else if(el.tagName !== p.toUpperCase()) return false;
  }
  return partes.length > 0;
}
function descendientes(raiz, sel, out){
  for(var i = 0; i < raiz.children.length; i++){
    var c = raiz.children[i];
    if(casa(c, sel)) out.push(c);
    descendientes(c, sel, out);
  }
}
function buscar(raiz, sel){
  var pasos = String(sel).trim().split(/\s+(?![^\[]*\])/);
  var actual = [raiz];
  for(var p = 0; p < pasos.length; p++){
    var sig = [];
    for(var i = 0; i < actual.length; i++) descendientes(actual[i], pasos[p], sig);
    actual = sig;
  }
  return actual;
}

function parsear(markup, raiz){
  var re = /<\/?([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>/g;
  var pila = [raiz], m, ultimo = 0;
  while((m = re.exec(markup))){
    var texto = markup.slice(ultimo, m.index);
    ultimo = re.lastIndex;
    if(texto.trim()) pila[pila.length - 1]._texto += texto;
    if(m[0][1] === "/"){ if(pila.length > 1) pila.pop(); continue; }
    var e = new Elem(m[1]);
    var ra = /([a-zA-Z_:][-\w:.]*)(?:\s*=\s*"([^"]*)")?/g, ma;
    while((ma = ra.exec(m[2]))){
      var k = ma[1], v = ma[2] === undefined ? "" : ma[2];
      if(k === "hidden") e.hidden = true;
      else if(k.indexOf("data-") === 0)
        e.dataset[k.slice(5).replace(/-(\w)/g, function(x, c){ return c.toUpperCase(); })] = v;
      else if(k === "value") e.value = v;
      else e.attrs[k] = v;
    }
    pila[pila.length - 1].appendChild(e);
    if(!VACIOS[m[1].toLowerCase()] && !/\/\s*$/.test(m[2])) pila.push(e);
  }
}

var DOC = {
  documentElement: new Elem("html"),
  body: new Elem("body"),
  title: "",
  activeElement: null,
  _ls: {},
  createElement: function(t){ return new Elem(t); },
  createElementNS: function(ns, t){ return new Elem(t); },
  querySelector: function(s){ return buscar(DOC.body, s)[0] || null; },
  querySelectorAll: function(s){ return buscar(DOC.body, s); },
  addEventListener: function(t, fn){ (DOC._ls[t] = DOC._ls[t] || []).push(fn); },
  dispatchEvent: function(ev){
    var l = (DOC._ls[ev.type] || []).slice();
    for(var i = 0; i < l.length; i++) l[i].call(DOC, ev);
    return true;
  }
};

var i0 = html.indexOf("<script>");
var i1 = html.lastIndexOf("</script>");
if(i0 < 0 || i1 < 0){ console.log("###JSON###" + JSON.stringify({error: "sin <script>"})); process.exit(0); }
var js = html.slice(i0 + 8, i1);
var cuerpo = html.slice(html.indexOf("<body>") + 6, i0);
parsear(cuerpo, DOC.body);

/* fetch de mentira: registra las llamadas y contesta lo que le pida la
   prueba (RESPUESTAS por ruta). Ninguna red de verdad. */
var LLAMADAS = [];
var RESPUESTAS = {};
function fetchFalso(url, o){
  LLAMADAS.push({url: String(url), opciones: o || {}});
  var ruta = String(url).replace(/^https?:\/\/[^/]+/, "");
  var clave = ruta.split("?")[0];
  var j = RESPUESTAS[clave] === undefined ? {ok: true} : RESPUESTAS[clave];
  if(typeof j === "function") j = j(ruta, o);
  return Promise.resolve({status: 200, json: function(){ return Promise.resolve(j); }});
}

var ERRORES = [];
var consolaFalsa = {
  log: function(){},
  warn: function(){ ERRORES.push(["warn", Array.prototype.slice.call(arguments).map(String).join(" ")]); },
  error: function(){ ERRORES.push(["error", Array.prototype.slice.call(arguments).map(String).join(" ")]); }
};

var ctx = {
  document: DOC, window: null, navigator: {},
  localStorage: {getItem: function(){ return null; }, setItem: function(){}},
  console: consolaFalsa, fetch: fetchFalso,
  setTimeout: setTimeout, clearTimeout: clearTimeout,
  setInterval: setInterval, clearInterval: clearInterval,
  JSON: JSON, Math: Math, Date: Date, Promise: Promise, RegExp: RegExp,
  Object: Object, Array: Array, String: String, Number: Number, Error: Error,
  parseInt: parseInt, parseFloat: parseFloat, isFinite: isFinite, isNaN: isNaN,
  encodeURIComponent: encodeURIComponent, decodeURIComponent: decodeURIComponent,
  LLAMADAS: LLAMADAS, RESPUESTAS: RESPUESTAS, ERRORES: ERRORES, Elem: Elem
};
ctx.window = ctx;
ctx.globalThis = ctx;
ctx.window.matchMedia = function(){ return {matches: false}; };
ctx.window.addEventListener = function(){};
ctx.window.console = consolaFalsa;
vm.createContext(ctx);

/* Un evento de puntero de mentira, lo justo para el handler del lienzo. */
ctx.evento = function(tipo, extra){
  var e = {type: tipo, pointerId: 1, button: 0, clientX: 0, clientY: 0,
           ctrlKey: false, metaKey: false, shiftKey: false, altKey: false,
           preventDefault: function(){}, stopPropagation: function(){},
           timeStamp: Date.now()};
  for(var k in (extra || {})) e[k] = extra[k];
  return e;
};
ctx.nodoDom = function(id){
  var todos = buscar(DOC.body, ".nodo");
  for(var i = 0; i < todos.length; i++) if(todos[i].dataset.id === id) return todos[i];
  return null;
};
ctx.buscar = function(sel){ return buscar(DOC.body, sel); };

var salida = {arranque: "ok", errores: ERRORES};
try{
  vm.runInContext(js, ctx, {filename: "editor.js"});
}catch(err){
  salida.arranque = "EXCEPCION: " + (err && err.message ? err.message : String(err));
  salida.pila = String(err && err.stack || "").split("\n").slice(0, 4).join(" | ");
}

ctx.RESULTADO = {};
ctx.hecho = function(o){
  for(var k in o) salida[k] = o[k];
  console.log("###JSON###" + JSON.stringify(salida));
  process.exit(0);
};
try{
  vm.runInContext(prueba, ctx, {filename: "prueba.js"});
}catch(err){
  salida.prueba = "EXCEPCION: " + (err && err.message ? err.message : String(err));
  salida.pila = String(err && err.stack || "").split("\n").slice(0, 4).join(" | ");
  console.log("###JSON###" + JSON.stringify(salida));
  process.exit(0);
}
"""


def _correr(tmp_path, datos, prueba_js, base="http://127.0.0.1:9999", token="TK"):
    """Renderiza la pagina, la ejecuta en node y devuelve lo que reporte."""
    pagina = tmp_path / "pagina.html"
    pagina.write_text(editor_html.render(datos, base=base, token=token), encoding="utf-8")
    arnes = tmp_path / "arnes.js"
    arnes.write_text(ARNES, encoding="utf-8")
    prueba = tmp_path / "prueba.js"
    prueba.write_text(prueba_js, encoding="utf-8")
    r = subprocess.run([NODE, str(arnes), str(pagina), str(prueba)],
                       capture_output=True, text=True, timeout=60,
                       encoding="utf-8", errors="replace")
    salida = r.stdout or ""
    marca = salida.find("###JSON###")
    assert marca >= 0, "el arnes no reporto nada:\nSTDOUT:\n%s\nSTDERR:\n%s" % (salida, r.stderr)
    return json.loads(salida[marca + len("###JSON###"):].strip().splitlines()[0])


def _flujo_sano():
    return {
        "nombre": "sano",
        "version": 1,
        "flujo": {"nombre": "sano", "nodos": [
            {"id": "a", "tool": "listar", "args": ".", "wires": ["b"]},
            {"id": "b", "tool": "resumir", "args": "{{a}}", "wires": []},
        ]},
        "ui": {"pos": {"a": {"x": 0, "y": 0}, "b": {"x": 300, "y": 0}}},
        "versiones": [{"v": 1, "ts": "2026-08-29T10:00:00", "nota": "inicial",
                       "n_nodos": 2, "actual": True, "existe": True}],
        "flujos": [{"nombre": "sano", "n_nodos": 2}],
        "catalogo": {"categorias": [], "nodos": []},
    }


def _flujo_venenoso():
    """EXACTAMENTE el genero del ROJO B: campos con el tipo cambiado.

    Todos son alcanzables de verdad: `flujoteca.guardar()` rechaza los args
    dict, pero `/flujoteca importar`, un JSON tecleado a mano o un fichero
    viejo entran por otra puerta.
    """
    return {
        "nombre": "veneno",
        "version": 1,
        "flujo": {"nombre": "veneno", "nodos": [
            {"id": "a", "tool": "listar", "args": ".", "wires": ["b"]},
            {"id": "b", "tool": "escribir_archivo",
             "args": {"ruta": "informe.md", "texto": "hola"}, "wires": ["c"]},
            {"id": "c", "tool": "resumir", "args": 42, "wires": "d"},
            {"id": "d", "tool": "leer_archivo", "args": None,
             "reintentos": "2", "timeout_s": "30", "saltar_si": 7},
            {"id": 5, "tool": None, "args": ["a", "b"], "wires": []},
        ]},
        "ui": {"pos": {}},
        "versiones": [{"v": 1, "ts": "2026-08-29T10:00:00",
                       "nota": {"por": "el modelo"}, "n_nodos": 5, "actual": True}],
        "flujos": [{"nombre": "veneno", "n_nodos": 5}],
        "catalogo": {"categorias": [], "nodos": []},
    }


# ---------------------------------------------------------------------------
# ROJO B: el arranque entero contra un flujo con los tipos cambiados
# ---------------------------------------------------------------------------
@sin_node
def test_arranque_con_args_dict_no_lanza_y_pinta_todos_los_nodos(tmp_path):
    """El test que SOLO con esto habria cazado el rojo B.

    Sin el arreglo, `arrancar()` moria dentro de `pintarNodo` y esto sale con
    `arranque: EXCEPCION ... .replace is not a function` y 1 nodo pintado.
    """
    r = _correr(tmp_path, _flujo_venenoso(), """
      /* El setTimeout deja correr el primer fetch: el indicador de estado
         solo deja de decir "conectando" cuando contesta, y ESE era el unico
         sintoma visible del rojo B. */
      setTimeout(function(){ hecho({
        nodosPintados: buscar(".nodo").length,
        nodosEstado: S.flujo.nodos.length,
        titulo: document.title,
        estado: document.querySelector("#estado-txt").textContent,
        avisoVisible: !document.querySelector("#aviso").hidden,
        avisoTexto: document.querySelector("#aviso-txt").textContent,
        versionesPintadas: buscar("#chips-v .vchip").length,
        tiposArgs: S.flujo.nodos.map(function(n){ return typeof n.args; }),
        tiposId: S.flujo.nodos.map(function(n){ return typeof n.id; }),
        wiresC: JSON.stringify((S.flujo.nodos[2] || {}).wires),
        reintentosD: typeof (S.flujo.nodos[3] || {}).reintentos
      }); }, 30);
    """)
    assert r["arranque"] == "ok", r
    assert r["nodosEstado"] == 5
    # LOS CINCO pintados: antes se pintaba 1 y el resto desaparecia con la pagina.
    assert r["nodosPintados"] == 5, r
    assert r["titulo"] == "Cognia - veneno"
    # El indicador NO se queda clavado en "conectando" (ese era el unico
    # sintoma del rojo B, indistinguible de un servidor lento).
    assert r["estado"] != "conectando", r
    # Y la conversion se DICE: banner ambar, no reparacion silenciosa.
    assert r["avisoVisible"] is True
    assert "args era dict" in r["avisoTexto"], r["avisoTexto"]
    assert "args era number" in r["avisoTexto"], r["avisoTexto"]
    # La barra de versiones tambien sobrevive a una nota que no es texto.
    assert r["versionesPintadas"] == 1, r
    assert r["tiposArgs"] == ["string"] * 5, r
    assert r["tiposId"] == ["string"] * 5, r
    assert r["wiresC"] == '["d"]', r
    assert r["reintentosD"] == "number", r
    assert r["errores"] == [], r["errores"]


@sin_node
def test_flujo_sano_arranca_sin_un_solo_aviso(tmp_path):
    """El contrafactual del anterior: sin veneno, ni aviso ni conversiones.

    Sin esto, un normalizador demasiado entusiasta podria "arreglar" flujos
    sanos y llenar de ambar una pagina que esta perfecta.
    """
    r = _correr(tmp_path, _flujo_sano(), """
      hecho({
        nodosPintados: buscar(".nodo").length,
        avisoVisible: !document.querySelector("#aviso").hidden,
        titulo: document.title,
        aristas: buscar(".arista").length
      });
    """)
    assert r["arranque"] == "ok", r
    assert r["nodosPintados"] == 2
    assert r["aristas"] == 1
    assert r["avisoVisible"] is False, r
    assert r["titulo"] == "Cognia - sano"
    assert r["errores"] == []


@sin_node
def test_un_nodo_imposible_no_se_lleva_el_lienzo(tmp_path):
    """CAPA 3: si aun asi algo revienta al pintar un nodo, se pierde SU caja.

    Se fuerza el fallo desde la prueba (un `posDe` que lanza para un id) para
    medir la red de seguridad sin depender de que exista un bug de verdad.
    """
    r = _correr(tmp_path, _flujo_sano(), """
      /* Se rompe algo que SOLO usa pintarNodo (y que nodoRoto no toca), para
         medir la red de seguridad del nodo y no la de pintar() entera. */
      var viejo = iconoDe;
      iconoDe = function(t){ if(t === "resumir") throw new Error("boom de prueba"); return viejo(t); };
      pintar();
      hecho({
        nodos: buscar(".nodo").length,
        rotos: buscar(".roto").length,
        aviso: document.querySelector("#aviso-txt").textContent,
        errores: ERRORES.length
      });
    """)
    assert r["arranque"] == "ok", r
    assert r["nodos"] == 2, r          # el sano + la caja rota
    assert r["rotos"] == 1, r
    assert "no se pudo pintar el nodo" in r["aviso"], r["aviso"]
    assert r["errores"] >= 1, r        # y queda en consola para depurar


# ---------------------------------------------------------------------------
# ROJO A: el doble clic
# ---------------------------------------------------------------------------
_DOBLE = """
  var svgEl = document.querySelector("#svg");
  function golpe(id, extra){
    var g = nodoDom(id);
    if(!g) throw new Error("no existe el nodo " + id);
    var e = evento("pointerdown", extra || {});
    e.target = g;
    g.dispatchEvent(e);
    var u = evento("pointerup", extra || {});
    u.target = g;
    svgEl.dispatchEvent(u);
  }
"""


@sin_node
def test_doble_clic_abre_el_panel_de_propiedades(tmp_path):
    """EL ROJO A. Dos pointerdown seguidos sobre el mismo nodo -> propiedades.

    Se re-busca el elemento del nodo entre los dos golpes A PROPOSITO: es lo
    que hace el navegador (vuelve a acertar bajo el cursor) y es justo lo que
    mataba el atajo antes, porque `pintar()` reconstruia el nodo dentro del
    primer pointerdown y el segundo caia sobre otro elemento.
    """
    r = _correr(tmp_path, _flujo_sano(), _DOBLE + """
      var antes = S.propsId;
      golpe("b");
      var trasUno = S.propsId;
      var abiertoUno = document.querySelector("#props").classList.contains("abierto");
      golpe("b");
      hecho({
        antes: antes, trasUno: trasUno, abiertoUno: abiertoUno,
        trasDos: S.propsId,
        abiertoDos: document.querySelector("#props").classList.contains("abierto"),
        campos: buscar("#props .campo").length,
        idEnPanel: (document.querySelector("#campo-id") || {}).value
      });
    """)
    assert r["arranque"] == "ok", r
    assert r["antes"] is None
    # Un solo clic NO abre nada: seria un panel saltando en cada seleccion.
    assert r["trasUno"] is None, r
    assert r["abiertoUno"] is False, r
    # El segundo, dentro de la ventana, SI.
    assert r["trasDos"] == "b", r
    assert r["abiertoDos"] is True, r
    assert r["campos"] >= 3, r
    assert r["idEnPanel"] == "b", r


@sin_node
def test_dos_clics_lentos_o_en_nodos_distintos_no_son_doble_clic(tmp_path):
    """Los dos contrafactuales del arreglo: tiempo y sujeto.

    Sin ellos "arreglar el doble clic" podria ser un `abrirProps` en cada
    clic, que es peor que no tenerlo.
    """
    r = _correr(tmp_path, _flujo_sano(), _DOBLE + """
      golpe("a");
      S.ultimoDown.t -= 5000;          /* el segundo clic llega 5 s tarde */
      golpe("a");
      var lento = S.propsId;

      S.ultimoDown = null;             /* se empieza de cero */
      golpe("a");
      golpe("b");                      /* dos clics seguidos, nodos distintos */
      var distinto = S.propsId;

      golpe("b");                      /* y este si es un doble clic sobre b */
      hecho({lento: lento, distinto: distinto, mismo: S.propsId});
    """)
    assert r["arranque"] == "ok", r
    assert r["lento"] is None, r
    assert r["distinto"] is None, r
    assert r["mismo"] == "b", r


@sin_node
def test_doble_clic_sobrevive_al_repintado_y_a_un_target_hijo(tmp_path):
    """Las DOS causas medidas en Chromium, cada una con su prueba.

    1. Entre golpe y golpe se repinta el lienzo entero (lo que hacia el
       `pointerdown` de antes): el atajo tiene que seguir funcionando.
    2. El evento llega apuntando a un HIJO del nodo (el texto del id), que es
       lo mas parecido a lo que hace un raton de verdad; y el segundo golpe
       llega apuntando al `<svg>`, que es lo que provocaba
       `e.target.closest('.nodo') === null` con el puntero capturado.
    """
    r = _correr(tmp_path, _flujo_sano(), """
      var svgEl = document.querySelector("#svg");
      function golpeEnHijo(id){
        var g = nodoDom(id);
        /* El PRIMER hijo (la caja): el ultimo suele ser el puerto de salida
           y ahi el pointerdown significa "empezar a conectar", no "clic". */
        var hijo = g.children[0] || g;
        var e = evento("pointerdown");
        e.target = hijo;
        hijo.dispatchEvent(e);
      }
      golpeEnHijo("a");
      pintar();                       /* CAUSA 1: el nodo se reconstruye */
      golpeEnHijo("a");
      var conRepintado = S.propsId;

      cerrarProps();
      S.ultimoDown = null;
      /* CAUSA 2: el dblclick nativo con el target secuestrado por el <svg> */
      var centro = posDe("b");
      var pant = aPantalla(centro.x + 48, centro.y + 48);   /* el centro de b */
      var d = evento("dblclick", {clientX: pant.x, clientY: pant.y});
      d.target = svgEl;
      svgEl.dispatchEvent(d);
      hecho({conRepintado: conRepintado, porCoordenada: S.propsId});
    """)
    assert r["arranque"] == "ok", r
    assert r["conRepintado"] == "a", r
    # El dblclick nativo cae sobre el <svg> (puntero capturado) y aun asi
    # resuelve el nodo por coordenada: "b" vive en (300,0) y mide 96x96.
    assert r["porCoordenada"] == "b", r


@sin_node
def test_doble_clic_tambien_en_solo_lectura(tmp_path):
    """Sin servidor la pagina es solo-lectura, pero MIRAR es legitimo."""
    r = _correr(tmp_path, _flujo_sano(), _DOBLE + """
      degradar();
      golpe("a"); golpe("a");
      hecho({soloLectura: S.soloLectura, props: S.propsId});
    """, base="")
    assert r["arranque"] == "ok", r
    assert r["soloLectura"] is True
    assert r["props"] == "a", r


@sin_node
def test_un_clic_en_nodo_ya_seleccionado_no_repinta(tmp_path):
    """La causa 1, arreglada en su raiz y medida como AHORRO.

    El repintado dentro del pointerdown es lo que destruia el elemento entre
    los dos clics. Se mide contando reconstrucciones del `<g>` del nodo.
    """
    r = _correr(tmp_path, _flujo_sano(), _DOBLE + """
      var n = 0, viejo = pintarNodos;
      pintarNodos = function(p){ n++; return viejo(p); };
      golpe("a");                      /* selecciona: repinta una vez */
      var trasPrimero = n;
      S.ultimoDown = null;             /* clic suelto, no doble */
      golpe("a");                      /* ya seleccionado: NO debe repintar */
      hecho({trasPrimero: trasPrimero, trasSegundo: n});
    """)
    assert r["arranque"] == "ok", r
    assert r["trasPrimero"] == 1, r
    assert r["trasSegundo"] == 1, r


# ---------------------------------------------------------------------------
# Las funciones puras del normalizador
# ---------------------------------------------------------------------------
@sin_node
def test_aTexto_y_normalizarFlujo(tmp_path):
    r = _correr(tmp_path, _flujo_sano(), """
      var casos = {
        nulo: aTexto(null), indef: aTexto(undefined), txt: aTexto("x"),
        num: aTexto(3), cero: aTexto(0), bool: aTexto(false),
        dict: aTexto({a: 1}), lista: aTexto(["a", 2])
      };
      var r = normalizarFlujo({nombre: "n", nodos: [
        {id: "a", args: {x: 1}},
        "esto no es un nodo",
        {id: "a", tool: "listar"},
        {id: 3, wires: "z"}
      ]});
      hecho({
        casos: casos,
        n: r.nodos.length,
        avisos: r.avisos.length,
        textoAvisos: r.avisos.join(" || "),
        args0: r.nodos[0].args,
        wires2: JSON.stringify(r.nodos[2].wires),
        id2: r.nodos[2].id,
        listaVacia: JSON.stringify(aLista(null)) + JSON.stringify(aLista("x"))
      });
    """)
    assert r["arranque"] == "ok", r
    assert r["casos"] == {"nulo": "", "indef": "", "txt": "x", "num": "3",
                          "cero": "0", "bool": "false", "dict": '{"a":1}',
                          "lista": '["a",2]'}
    assert r["n"] == 3          # el que no era objeto se descarta
    assert r["args0"] == '{"x":1}'
    assert r["wires2"] == '["z"]'
    assert r["id2"] == "3"
    assert "repetido" in r["textoAvisos"], r["textoAvisos"]
    assert "no un objeto" in r["textoAvisos"], r["textoAvisos"]
    assert r["listaVacia"] == '[]["x"]'


# ---------------------------------------------------------------------------
# Los dos menores del informe
# ---------------------------------------------------------------------------
@sin_node
def test_al_cambiar_de_flujo_cambia_tambien_el_titulo_de_la_pestana(tmp_path):
    r = _correr(tmp_path, _flujo_sano(), """
      RESPUESTAS["/api/flujo"] = {ok: true, nombre: "otro", version: 3,
        flujo: {nombre: "otro", nodos: [{id: "z", tool: "listar", args: "", wires: []}]},
        ui: {pos: {}}, versiones: []};
      var antes = document.title;
      cargarFlujo("otro", null);
      setTimeout(function(){
        hecho({antes: antes, despues: document.title,
               h1: document.querySelector("#titulo").textContent,
               nodos: buscar(".nodo").length});
      }, 30);
    """)
    assert r["arranque"] == "ok", r
    assert r["antes"] == "Cognia - sano"
    assert r["despues"] == "Cognia - otro", r
    assert r["h1"] == "otro"
    assert r["nodos"] == 1


@sin_node
def test_tras_guardar_se_refresca_la_lista_de_flujos(tmp_path):
    """El selector decia "informe semanal (6)" con 7 nodos ya en disco."""
    r = _correr(tmp_path, _flujo_sano(), """
      RESPUESTAS["/api/flujos"] = {ok: true, flujos: [{nombre: "sano", n_nodos: 9}]};
      LLAMADAS.length = 0;
      recargarVersiones();
      setTimeout(function(){
        var rutas = LLAMADAS.map(function(l){ return l.url.split("?")[0]; });
        hecho({rutas: rutas,
               opcion: (document.querySelector("#sel-flujo").children[0] || {textContent: ""}).textContent});
      }, 30);
    """)
    assert r["arranque"] == "ok", r
    assert any(u.endswith("/api/flujos") for u in r["rutas"]), r["rutas"]
    assert r["opcion"] == "sano (9)", r


# ---------------------------------------------------------------------------
# E2E de verdad, opt-in: navegador real contra el servidor real
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.environ.get("COGNIA_EDITOR_E2E") != "1",
                    reason="e2e lento con navegador: COGNIA_EDITOR_E2E=1 para correrlo")
def test_e2e_navegador_real(tmp_path, monkeypatch):
    """Lo que el DOM de mentira NO puede probar: un Chromium de verdad.

    Opt-in a proposito (arranca un servidor y un navegador: ~10 s). Es la
    misma via por la que se midieron los dos rojos.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    from cognia.agent import flujoteca, flujoteca_editor

    # guardar() toma el flujo como UNICO posicional; el nombre va por
    # keyword (flujoteca.py:142). Pasarlo como dos posicionales reventaba
    # en la primera linea, antes de abrir el navegador, y como el test es
    # opt-in (COGNIA_EDITOR_E2E) el fallo salia como 's' en la suite.
    flujoteca.guardar({"nombre": "e2e", "nodos": [
        {"id": "a", "tool": "listar", "args": ".", "wires": ["b"]},
        {"id": "b", "tool": "resumir", "args": "{{a}}", "wires": []},
    ]}, nombre="e2e", nota="siembra e2e")

    import threading
    srv = flujoteca_editor.crear_server(puerto=0)
    srv.nombre = "e2e"
    puerto = srv.server_address[1]
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    time.sleep(0.2)
    try:
        with playwright.sync_playwright() as p:
            nav = p.chromium.launch()
            pag = nav.new_page()
            errores = []
            pag.on("pageerror", lambda e: errores.append(str(e)))
            pag.goto("http://127.0.0.1:%d/?t=%s" % (puerto, srv.token))
            pag.wait_for_selector(".nodo")
            caja = pag.locator("g.nodo").first.bounding_box()
            pag.mouse.dblclick(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2)
            pag.wait_for_selector("#props.abierto", timeout=3000)
            assert pag.locator("#campo-id").input_value()
            assert errores == [], errores
            nav.close()
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# EL NODO DE ENTRADA: que el editor lo sepa PINTAR (PLAN2, PEDIDO 3)
# ---------------------------------------------------------------------------
# Un cajon nuevo en `catalogo_nodos.CATEGORIAS` y dos tools nuevas en el
# registro NO bastan: la paleta la dibuja JavaScript, `icono()` cae en
# silencio a `ICONOS.box` con cualquier nombre que no conozca (asi llevaban
# `pantalla` y `escena` desde que se escribio la tabla), y la forma del nodo
# no sale del catalogo sino del GRAFO. Nada de eso lo ve un test de Python que
# mire cadenas del HTML. Estos dos EJECUTAN la pagina con la paleta REAL.

_RX_ICONOS = re.compile(r"var ICONOS = \{(.*?)\n\};", re.S)


def _iconos_del_modulo():
    """{nombre: [d, ...]} del mapa JS ICONOS, leido del propio editor_html."""
    m = _RX_ICONOS.search(editor_html.HTML)
    assert m, "no encuentro el mapa ICONOS en editor_html.HTML"
    fuera = {}
    for nombre, cuerpo in re.findall(r"^  ([a-z_]+):\s*\[(.*?)\],?$",
                                     m.group(1), re.S | re.M):
        fuera[nombre] = re.findall(r'"([^"]+)"', cuerpo)
    return fuera


def _datos_con_catalogo_real(nodos):
    """Los datos de la pagina con la PALETA REAL (`catalogo_nodos.paleta()`).

    Con un catalogo de mentira esto no mediria nada: lo que se comprueba es
    que la tabla de verdad y el JS de verdad encajan.
    """
    from cognia.agent import catalogo_nodos as cn

    pal = cn.paleta()
    cats = [{k: v for k, v in c.items() if k != "nodos"}
            for c in pal["categorias"]]
    return {
        "nombre": "entrada",
        "version": 1,
        "flujo": {"nombre": "entrada", "nodos": nodos},
        "ui": {"pos": {}},
        "versiones": [{"v": 1, "ts": "2026-08-29T10:00:00", "nota": "inicial",
                       "n_nodos": len(nodos), "actual": True, "existe": True}],
        "flujos": [{"nombre": "entrada", "n_nodos": len(nodos)}],
        "catalogo": {"categorias": cats, "nodos": pal["nodos"]},
    }


@sin_node
def test_la_paleta_pinta_el_cajon_de_entrada_con_su_icono(tmp_path):
    """El cajon "Entrada del flujo" sale el PRIMERO, con sus dos tools
    arrastrables y con el icono que declara la tabla -- no con el de respaldo,
    que se ve igual que "Otros" y no deja ni un error en consola."""
    from cognia.agent import catalogo_nodos as cn

    datos = _datos_con_catalogo_real([
        {"id": "prompt", "tool": "prompt", "args": "tema", "wires": []}])
    r = _correr(tmp_path, datos, """
      abrirPaleta();
      var cajones = buscar("#lista-paleta .cat").map(function(c){
        var cab = c.querySelector(".cab");
        var svg = cab.querySelector("svg");
        return {texto: cab.textContent,
                paths: svg.querySelectorAll("path").map(function(p){
                  return p.getAttribute("d"); }),
                items: c.querySelectorAll(".pt").length};
      });
      hecho({cajones: cajones});
    """)

    assert r["arranque"] == "ok", r
    assert r["errores"] == [], r["errores"]
    textos = [c["texto"] for c in r["cajones"]]
    cajon = [c for c in r["cajones"] if "Entrada del flujo" in c["texto"]]
    assert cajon, textos
    cajon = cajon[0]
    # Es EL PRIMERO: es por donde empieza un flujo.
    assert "Entrada del flujo" in textos[0], textos
    # Las dos tools de entrada, arrastrables desde la paleta.
    assert "(2)" in cajon["texto"], cajon["texto"]
    assert cajon["items"] == 2, cajon
    # Y el icono es EL DE LA TABLA, no el gris de respaldo.
    iconos = _iconos_del_modulo()
    esperado = iconos[cn._cat("entrada")["icono"]]
    assert esperado, iconos.keys()
    assert cajon["paths"] == esperado, (cajon["paths"], esperado)
    assert cajon["paths"] != iconos["box"]


@sin_node
def test_un_nodo_prompt_se_pinta_como_TRIGGER_y_sin_puerto_de_entrada(tmp_path):
    """La forma sale del GRAFO, no del catalogo: un nodo sin padres se pinta
    como disparador. El nodo de entrada no tiene padres nunca, asi que sale
    con la caja redondeada y sin puerto de entrada, que es exactamente lo
    correcto para "por aqui entra tu objetivo".

    El contrafactual va en el mismo test: el nodo de escritura, que SI tiene
    padre, se pinta con `rect` y con su puerto de entrada.
    """
    datos = _datos_con_catalogo_real([
        {"id": "prompt", "tool": "prompt", "args": "un informe de IA",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md | {{prompt}}", "wires": []},
    ])
    r = _correr(tmp_path, datos, """
      function conClase(g, tag, clase){
        return g.querySelectorAll(tag).filter(function(e){
          return e.classList.contains(clase); }).length;
      }
      function mirar(id){
        var g = nodoDom(id);
        if(!g) return null;
        return {caja_path: conClase(g, "path", "caja"),
                caja_rect: conClase(g, "rect", "caja"),
                puerto_entrada: conClase(g, "circle", "entrada"),
                puerto_salida: conClase(g, "circle", "salida"),
                texto: g.textContent};
      }
      hecho({pintados: buscar(".nodo").length,
             prompt: mirar("prompt"), escribir: mirar("escribir")});
    """)

    assert r["arranque"] == "ok", r
    assert r["errores"] == [], r["errores"]
    assert r["pintados"] == 2, r
    # El de entrada: TRIGGER -- caja de `path` y SIN puerto de entrada.
    assert r["prompt"]["caja_path"] == 1, r["prompt"]
    assert r["prompt"]["caja_rect"] == 0, r["prompt"]
    assert r["prompt"]["puerto_entrada"] == 0, r["prompt"]
    assert r["prompt"]["puerto_salida"] == 1, r["prompt"]
    assert "prompt" in r["prompt"]["texto"], r["prompt"]
    # El contrafactual: el que tiene padre NO es trigger.
    assert r["escribir"]["caja_rect"] == 1, r["escribir"]
    assert r["escribir"]["caja_path"] == 0, r["escribir"]
    assert r["escribir"]["puerto_entrada"] == 1, r["escribir"]
