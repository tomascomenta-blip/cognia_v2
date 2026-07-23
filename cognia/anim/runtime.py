# -*- coding: utf-8 -*-
"""Runtime web de la animación (F5): reproduce una tabla horneada por engine.bake().

Autocontenido: Canvas2D puro, sin PixiJS ni CDN (respeta la regla offline del
generator). El runtime NO interpola ni calcula cinemática — solo dibuja el frame que
toca (toda la matemática ya la hizo engine.py, determinista). Los sprites llegan como
data URIs (ASSETS), igual que en el puente F4.

API JS: cogniaAnim.reproducir(canvas, baked, assets, {origen:[x,y], escala:1})
"""
from __future__ import annotations

import json

# Runtime JS (literal). Determinista: frame = floor(elapsed*fps), con loop opcional.
RUNTIME_JS = r"""
(function(g){
  function cargar(assets){
    var imgs={}, keys=Object.keys(assets||{}), pend=keys.length;
    return new Promise(function(res){
      if(!pend) res(imgs);
      keys.forEach(function(k){
        var im=new Image();
        im.onload=im.onerror=function(){ if(--pend===0) res(imgs); };
        im.src=assets[k]; imgs[k]=im;
      });
    });
  }
  function reproducir(canvas, baked, assets, opts){
    opts=opts||{};
    var origen=opts.origen||[canvas.clientWidth/2, canvas.clientHeight/2];
    var escala=opts.escala||1;
    var ctx=canvas.getContext('2d');
    function ajusta(){
      var dpr=g.devicePixelRatio||1;
      canvas.width=canvas.clientWidth*dpr; canvas.height=canvas.clientHeight*dpr;
      canvas._dpr=dpr;
    }
    ajusta(); g.addEventListener('resize', ajusta);
    return cargar(assets).then(function(imgs){
      var fps=baked.fps||30, nf=baked.frames.length, t0=null;
      function frame(ts){
        if(t0===null) t0=ts;
        var el=(ts-t0)/1000, idx=Math.floor(el*fps);
        idx = baked.loop ? (idx % nf) : Math.min(idx, nf-1);
        var dpr=canvas._dpr||1;
        ctx.setTransform(1,0,0,1,0,0);
        ctx.clearRect(0,0,canvas.width,canvas.height);
        var capas=baked.frames[idx];
        for(var i=0;i<capas.length;i++){
          var c=capas[i], im=imgs[c.asset]; if(!im||!im.width) continue;
          var m=c.m;
          // base: dpr + origen + escala global, luego la matriz de la capa
          ctx.setTransform(dpr*escala,0,0,dpr*escala, origen[0]*dpr, origen[1]*dpr);
          ctx.transform(m[0],m[1],m[2],m[3],m[4],m[5]);
          ctx.drawImage(im, -c.ax*c.w, -c.ay*c.h, c.w, c.h);
        }
        g.requestAnimationFrame(frame);
      }
      g.requestAnimationFrame(frame);
    });
  }
  g.cogniaAnim={reproducir:reproducir, cargar:cargar};
})(window);
"""


def pagina_animada(baked: dict, assets: dict, *, titulo: str = "Animación Cognia",
                   fondo: str = "#71c5e8", ancho: int = 640, alto: int = 480,
                   origen=None, escala: float = 1.0) -> str:
    """Construye un HTML autocontenido que reproduce la animación horneada. Los
    sprites (ASSETS) van embebidos como data URIs -> abre offline desde file://."""
    if origen is None:
        origen = [ancho / 2, alto * 0.75]
    cfg = json.dumps({"origen": origen, "escala": escala})
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{titulo}</title>\n<style>\n"
        f"  body{{margin:0;font-family:system-ui,sans-serif;background:{fondo};"
        "display:flex;flex-direction:column;align-items:center;justify-content:center;"
        "min-height:100vh}\n"
        f"  canvas{{width:{ancho}px;max-width:100%;height:{alto}px;"
        "background:transparent}\n"
        "  h1{color:#2b5d34;text-shadow:1px 1px #fff}\n</style>\n</head>\n<body>\n"
        f"<h1>{titulo}</h1>\n<canvas id=\"escena\"></canvas>\n"
        f"<script>window.__BAKED__={json.dumps(baked)};\n"
        f"window.__ASSETS__={json.dumps(assets)};\n</script>\n"
        f"<script>{RUNTIME_JS}</script>\n"
        f"<script>cogniaAnim.reproducir(document.getElementById('escena'),"
        f"window.__BAKED__, window.__ASSETS__, {cfg});</script>\n"
        "</body>\n</html>\n"
    )
