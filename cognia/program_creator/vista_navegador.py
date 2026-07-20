"""
vista_navegador.py — Cognia mira lo que acaba de escribir.

POR QUE EXISTE: revisar_html() inspecciona el texto de la pagina, y eso no
alcanza. Medido el 2026-07-19: una pagina generada paso la revision estatica
con 8.7/10 y en Chrome salia ENTERA EN NEGRO. El CSS decia `.quote.up span`
pero el JS ponia la clase 'up' en el <span> interior, no en el `.quote`: el
selector no casaba jamas. HTML valido, pagina rota. Ningun analisis del texto
distingue esos dos casos; solo renderizar lo hace.

COMO FUNCIONA: se abre la pagina en el Chrome del sistema en headless y se le
inyecta una sonda que muestrea el DOM dos veces separadas en el tiempo. La
sonda devuelve lo que de verdad importa y no se puede saber leyendo el codigo:

  - si los valores CAMBIAN solos (la pagina se anima de verdad)
  - los colores COMPUTADOS (si el verde y el rojo llegan a pintar)
  - errores de JavaScript en tiempo de ejecucion

Dos clases de imagenes, con los nombres que puso el dueno:

  input images  — capturas temporales durante el razonamiento. Son evidencia
                  para que Cognia valide su propio trabajo y, si algo falla,
                  se corrija antes de dar la pagina por buena.
  output images — capturas del resultado ya aceptado.

Sin dependencias nuevas: usa el Chrome (o Edge) ya instalado y solo stdlib,
igual que llm_local.py. Instalar Playwright para esto seria traer 150 MB de
navegador cuando ya hay uno en la maquina.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Rutas habituales del navegador en Windows. Se prueba en orden.
_CANDIDATOS_NAVEGADOR = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "chrome", "chromium", "google-chrome", "msedge",
)

# Cuanto tiempo virtual se deja correr antes de mirar. Es tiempo VIRTUAL: el
# navegador adelanta los timers, asi que no cuesta esa espera en pared.
# Se muestrea varias veces y se toma la union: una sola lectura cae por azar
# en el hueco anterior al primer tick de la pagina y da un falso negativo.
_N_MUESTRAS   = 6
_MS_MUESTREO  = 700     # separacion entre lecturas
_MS_ASENTAR   = _MS_MUESTREO * (_N_MUESTRAS + 3)
_TIMEOUT_SEC  = 60

_ANCHO, _ALTO = 1280, 900


@dataclass
class InformeVisual:
    """Lo que Cognia ve al mirar su propia pagina."""
    ok:            bool = False
    se_mueve:      bool = False
    colores:       List[str] = field(default_factory=list)
    errores_js:    List[str] = field(default_factory=list)
    input_images:  List[str] = field(default_factory=list)
    output_images: List[str] = field(default_factory=list)
    defectos:      List[str] = field(default_factory=list)
    nota:          str  = ""

    def resumen(self) -> str:
        if self.nota:
            return self.nota
        partes = [
            "se mueve sola" if self.se_mueve else "NO se mueve",
            f"{len(self.colores)} colores distintos",
        ]
        if self.errores_js:
            partes.append(f"{len(self.errores_js)} errores JS")
        return "; ".join(partes)


DIR_INPUT  = "input_images"
DIR_OUTPUT = "output_images"


@dataclass
class LoteImagenes:
    """Las imagenes de un programa concreto."""
    programa: str
    ruta:     Path
    entrada:  List[Path] = field(default_factory=list)
    salida:   List[Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.entrada) + len(self.salida)

    @property
    def bytes(self) -> int:
        return sum(p.stat().st_size for p in self.entrada + self.salida
                   if p.exists())


def listar_imagenes(storage_dir: Path = None) -> List[LoteImagenes]:
    """Recorre la biblioteca y junta las imagenes de cada programa."""
    from .storage import DEFAULT_STORAGE_DIR
    base = Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR
    if not base.exists():
        return []

    lotes = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        lote = LoteImagenes(programa=d.name, ruta=d)
        for sub, destino in ((DIR_INPUT, lote.entrada), (DIR_OUTPUT, lote.salida)):
            carpeta = d / sub
            if carpeta.is_dir():
                destino.extend(sorted(carpeta.glob("*.png")))
        if lote.total:
            lotes.append(lote)
    return lotes


def _borrar_rutas(rutas: List[Path]) -> tuple[int, int]:
    """Borra los ficheros dados. Devuelve (cuantos, cuantos bytes)."""
    n = liberado = 0
    for p in rutas:
        try:
            if p.exists():
                liberado += p.stat().st_size
                p.unlink()
                n += 1
        except OSError:
            continue
    return n, liberado


def borrar_imagenes(storage_dir: Path = None, programa: str = None,
                    solo: str = "todo") -> tuple[int, int]:
    """
    Borra imagenes generadas.

    Args:
        programa: nombre del directorio a limpiar. None = todos.
        solo:     "input" | "output" | "todo"

    Returns:
        (imagenes borradas, bytes liberados)
    """
    borradas = liberados = 0
    for lote in listar_imagenes(storage_dir):
        if programa and lote.programa != programa:
            continue

        rutas = []
        if solo in ("input", "todo"):
            rutas += lote.entrada
        if solo in ("output", "todo"):
            rutas += lote.salida

        n, b = _borrar_rutas(rutas)
        borradas  += n
        liberados += b

        # Carpeta vacia = ruido. Se quita.
        for sub in (DIR_INPUT, DIR_OUTPUT):
            carpeta = lote.ruta / sub
            if carpeta.is_dir() and not any(carpeta.iterdir()):
                try:
                    carpeta.rmdir()
                except OSError:
                    pass

    return borradas, liberados


def _humano(n_bytes: int) -> str:
    if n_bytes >= 1024 * 1024:
        return f"{n_bytes / (1024*1024):.1f} MB"
    return f"{n_bytes / 1024:.0f} KB"


def formatear_imagenes(storage_dir: Path = None) -> str:
    """Listado para el comando /imagenes."""
    lotes = listar_imagenes(storage_dir)
    if not lotes:
        return "No hay imagenes guardadas."

    n_in  = sum(len(l.entrada) for l in lotes)
    n_out = sum(len(l.salida)  for l in lotes)
    total = sum(l.bytes for l in lotes)

    lineas = [
        f"Imagenes de {len(lotes)} programa(s) — {n_in + n_out} en total, {_humano(total)}",
        "",
    ]
    for i, l in enumerate(lotes, 1):
        lineas.append(f"{i:>3}. {l.programa}")
        lineas.append(f"     input: {len(l.entrada):<3} output: {len(l.salida):<3} "
                      f"({_humano(l.bytes)})")

    lineas += [
        "",
        f"Las de input son temporales: son la evidencia que Cognia miro para",
        f"validarse ({n_in} archivos, {_humano(sum(sum(p.stat().st_size for p in l.entrada if p.exists()) for l in lotes))}).",
        "",
        "  /imagenes borrar input     — solo las temporales de validacion",
        "  /imagenes borrar output    — solo los resultados",
        "  /imagenes borrar todo      — todas",
        "  /imagenes borrar <n>       — todas las del programa n de la lista",
    ]
    return "\n".join(lineas)


def encontrar_navegador() -> Optional[str]:
    """Devuelve la ruta a un Chrome/Edge usable, o None."""
    for cand in _CANDIDATOS_NAVEGADOR:
        if os.path.isabs(cand):
            if os.path.exists(cand):
                return cand
        else:
            hallado = shutil.which(cand)
            if hallado:
                return hallado
    return None


# La sonda se inyecta al final del <body>. Mira dos veces separadas en el
# tiempo y deja el veredicto en un <div> que luego se lee con --dump-dom.
_SONDA = """
<script>
(function () {
  var errores = [];
  window.addEventListener('error', function (e) {
    errores.push(String(e.message).slice(0, 200));
  });

  function leer() {
    var vistos = [];
    var todos = document.querySelectorAll('body *');
    for (var i = 0; i < todos.length; i++) {
      var el = todos[i];
      if (el.children.length !== 0) continue;
      var txt = (el.textContent || '').trim();
      if (!txt || txt.length > 40) continue;
      vistos.push({ t: txt, c: getComputedStyle(el).color });
    }
    return vistos;
  }

  // Se muestrea VARIAS veces, no dos. Medido el 2026-07-19: con una sola
  // lectura a los 2000 ms, una pagina cuyo setInterval tambien era de 2000 ms
  // se leia en el instante previo a la primera actualizacion, cuando los
  // elementos aun no tienen su clase de estado. La sonda reportaba "todo
  // negro" sobre una pagina que en realidad pintaba verde y rojo, y eso
  // disparaba reparaciones inutiles. Se toma la UNION de lo observado.
  var muestras = [];
  var colores  = {};

  function muestrear() {
    var v = leer();
    v.forEach(function (x) { colores[x.c] = 1; });
    muestras.push(v.map(function (x) { return x.t; }).join('|'));
  }

  muestrear();
  var pendientes = __N_MUESTRAS__;
  var timer = setInterval(function () {
    muestrear();
    if (--pendientes > 0) return;
    clearInterval(timer);

    var distintas = {};
    muestras.forEach(function (m) { distintas[m] = 1; });

    var d = document.createElement('div');
    d.id = '__cognia_sonda__';
    d.textContent = JSON.stringify({
      se_mueve: Object.keys(distintas).length > 1,
      colores:  Object.keys(colores),
      errores:  errores,
      muestras: muestras.length
    });
    document.body.appendChild(d);
  }, __MS_MUESTREO__);
})();
</script>
"""


def _preparar_pagina(code: str, destino: Path) -> Path:
    """Escribe la pagina con la sonda inyectada antes de cerrar el body."""
    sonda = (_SONDA.replace("__MS_MUESTREO__", str(_MS_MUESTREO))
                   .replace("__N_MUESTRAS__", str(_N_MUESTRAS)))
    bajo  = code.lower()
    corte = bajo.rfind("</body>")
    if corte == -1:
        html = code + sonda
    else:
        html = code[:corte] + sonda + code[corte:]

    ruta = destino / "pagina_sondeada.html"
    ruta.write_text(html, encoding="utf-8")
    return ruta


def _correr_navegador(navegador: str, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [navegador, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--hide-scrollbars", "--disable-extensions"] + args,
        capture_output=True, text=True, timeout=_TIMEOUT_SEC,
        encoding="utf-8", errors="replace",
    )


def _leer_sonda(navegador: str, url: str) -> Optional[dict]:
    """Renderiza y extrae el veredicto que dejo la sonda en el DOM."""
    try:
        r = _correr_navegador(navegador, [
            "--dump-dom", f"--virtual-time-budget={_MS_ASENTAR}", url])
    except subprocess.TimeoutExpired:
        return None

    m = re.search(r'id="__cognia_sonda__">(.*?)</div>', r.stdout, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _capturar(navegador: str, url: str, salida: Path, ms: int) -> Optional[str]:
    """Una captura al cabo de `ms` de tiempo virtual."""
    try:
        _correr_navegador(navegador, [
            f"--screenshot={salida}", f"--window-size={_ANCHO},{_ALTO}",
            f"--virtual-time-budget={ms}", url])
    except subprocess.TimeoutExpired:
        return None
    return str(salida) if salida.exists() else None


def revisar_en_navegador(code: str, dir_programa: Path = None,
                         momentos_ms: List[int] = None) -> InformeVisual:
    """
    Abre la pagina de verdad y devuelve lo que se ve.

    Args:
        code:         el HTML generado
        dir_programa: donde dejar input_images/ y output_images/. Si es None,
                      las capturas se hacen en un temporal y se descartan: sirve
                      para validar sin ensuciar el disco.
        momentos_ms:  instantes (tiempo virtual) de las capturas de validacion.

    Returns:
        InformeVisual. Si no hay navegador, ok=True y nota explicandolo: la
        ausencia de Chrome no puede tumbar la generacion, solo dejarla sin
        esta comprobacion.
    """
    navegador = encontrar_navegador()
    if not navegador:
        return InformeVisual(
            ok=True, nota="Sin navegador instalado: no se pudo mirar la pagina.")

    momentos_ms = momentos_ms or [1200, 4000]
    informe = InformeVisual()

    with tempfile.TemporaryDirectory(prefix="cognia_vista_") as tmp:
        tmp_dir = Path(tmp)
        pagina  = _preparar_pagina(code, tmp_dir)
        url     = pagina.as_uri()

        # -- input images: evidencia mientras valida --------------------
        if dir_programa is not None:
            dir_in = Path(dir_programa) / "input_images"
            dir_in.mkdir(parents=True, exist_ok=True)
        else:
            dir_in = tmp_dir

        for i, ms in enumerate(momentos_ms, 1):
            ruta = _capturar(navegador, url, dir_in / f"validacion_{i}_{ms}ms.png", ms)
            if ruta and dir_programa is not None:
                informe.input_images.append(ruta)

        # -- la sonda: lo que no se puede saber leyendo el codigo --------
        datos = _leer_sonda(navegador, url)
        if datos is None:
            informe.ok = True
            informe.nota = "La sonda no respondio; no se pudo verificar en navegador."
            return informe

        informe.se_mueve   = bool(datos.get("se_mueve"))
        informe.colores    = list(datos.get("colores") or [])
        informe.errores_js = list(datos.get("errores") or [])

        if not informe.se_mueve:
            informe.defectos.append(
                "la pagina no cambia sola: los valores siguen identicos en "
                f"{_N_MUESTRAS} lecturas separadas {_MS_MUESTREO} ms")
        if informe.errores_js:
            informe.defectos.append(
                "errores de JavaScript: " + "; ".join(informe.errores_js[:3]))
        if len(informe.colores) <= 1:
            informe.defectos.append(
                "todo el texto sale del mismo color "
                f"({', '.join(informe.colores) or 'ninguno'}): las clases de "
                "estado no estan pintando")

        informe.ok = not informe.defectos

        # -- output images: solo si la pagina se acepta -----------------
        if informe.ok and dir_programa is not None:
            dir_out = Path(dir_programa) / "output_images"
            dir_out.mkdir(parents=True, exist_ok=True)
            final = _capturar(navegador, url, dir_out / "resultado.png",
                              max(momentos_ms))
            if final:
                informe.output_images.append(final)

    return informe
