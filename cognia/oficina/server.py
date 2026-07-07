"""Server localhost de la oficina: dashboard + API JSON (stdlib puro).

GET  /                     dashboard (HTML inline, poll cada 2 s)
GET  /api/estado           snapshot completo del estado
POST /api/meta             {"texto": ...}            -> nueva meta
POST /api/tarea/accion     {"id","accion"}           -> detener|pausar|reanudar
POST /api/tarea/editar     {"id","detalle"}          -> editar tarea pendiente/pausada
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Oficina Cognia</title><style>
body{font-family:Consolas,monospace;background:#111418;color:#d7dde4;margin:0;padding:16px}
h1{font-size:18px;margin:0 0 4px}
small{color:#7c8896}
#cols{display:flex;gap:16px;margin-top:12px;align-items:flex-start}
#arbol{flex:1.4;min-width:0}
#panel{flex:1;background:#171b21;border:1px solid #2a313b;border-radius:8px;padding:12px;max-height:80vh;overflow:auto}
.tarea{border:1px solid #2a313b;border-radius:8px;padding:8px 10px;margin:6px 0;cursor:pointer;background:#171b21}
.tarea:hover{border-color:#4a5563}
.tarea.sel{border-color:#7aa2f7}
.nivel-jefe{margin-left:0}.nivel-director{margin-left:26px}.nivel-trabajador{margin-left:52px}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;margin-right:8px}
.pendiente{background:#3b4252}.en_curso{background:#1f6feb}.pausada{background:#9e6a03}
.detenida{background:#6e2i30;background:#6e2630}.hecha{background:#1a7f37}.fallida{background:#a40e26}
button{background:#21262d;color:#d7dde4;border:1px solid #3a434e;border-radius:6px;padding:4px 10px;cursor:pointer;margin-right:6px}
button:hover{border-color:#7aa2f7}
textarea,input{width:100%;box-sizing:border-box;background:#0d1117;color:#d7dde4;border:1px solid #3a434e;border-radius:6px;padding:6px}
#eventos{font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.evt-t{color:#7c8896}
#meta-form{margin-top:10px;display:flex;gap:8px}
.rol{color:#e3b341;font-size:11px}
</style></head><body>
<h1>Oficina Cognia <small id="reloj"></small></h1>
<small>jefe &rarr; directores &rarr; trabajadores &mdash; clic en una tarea para ver su flujo y controlarla</small>
<div id="meta-form"><input id="meta-texto" placeholder="Nueva meta para la oficina...">
<button onclick="nuevaMeta()">Encargar</button></div>
<div id="cols"><div id="arbol"></div>
<div id="panel"><em>Seleccioná una tarea.</em></div></div>
<script>
let SEL=null, DATA=null;
async function carga(){
  DATA = await (await fetch('/api/estado')).json();
  document.getElementById('reloj').textContent = new Date().toLocaleTimeString();
  render();
}
function tareasOrdenadas(){
  return (DATA.orden||[]).map(id=>DATA.tareas[id]).filter(Boolean);
}
function render(){
  const a = document.getElementById('arbol'); a.innerHTML='';
  for(const m of (DATA.metas||[])){
    const d = document.createElement('div');
    d.innerHTML = `<small>meta ${m.id} — <b>${m.estado}</b>: ${esc(m.texto).slice(0,110)}</small>`;
    a.appendChild(d);
  }
  for(const t of tareasOrdenadas()){
    const d = document.createElement('div');
    d.className = `tarea nivel-${t.nivel}` + (SEL===t.id?' sel':'');
    d.onclick = ()=>{SEL=t.id; render();};
    d.innerHTML = `<span class="pill ${t.estado}">${t.estado}</span>`+
      `<b>${t.nivel}</b> ${t.rol?`<span class="rol">[${t.rol}]</span>`:''} ${esc(t.titulo)}`;
    a.appendChild(d);
  }
  renderPanel();
}
function renderPanel(){
  const p = document.getElementById('panel');
  const t = SEL && DATA.tareas[SEL];
  if(!t){p.innerHTML='<em>Seleccioná una tarea.</em>';return;}
  const editable = (t.estado==='pendiente'||t.estado==='pausada');
  p.innerHTML =
   `<b>${t.id}</b> <span class="pill ${t.estado}">${t.estado}</span> ${t.rol||''}<br>`+
   `<div style="margin:8px 0"><textarea id="detalle" rows="3" ${editable?'':'disabled'}>${esc(t.detalle)}</textarea></div>`+
   `<div style="margin-bottom:8px">`+
   (editable?`<button onclick="editar()">Guardar edicion</button>`:'')+
   `<button onclick="accion('pausar')">Pausar</button>`+
   `<button onclick="accion('reanudar')">Reanudar</button>`+
   `<button onclick="accion('detener')" style="border-color:#a40e26">DETENER</button></div>`+
   (t.resultado?`<div><b>resultado:</b><br><small>${esc(t.resultado)}</small></div>`:'')+
   `<hr style="border-color:#2a313b"><div id="eventos">`+
   (t.eventos||[]).slice(-60).map(e=>`<span class="evt-t">${e.t}</span> ${esc(e.msg)}`).join('\\n')+
   `</div>`;
}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function accion(acc){
  await fetch('/api/tarea/accion',{method:'POST',body:JSON.stringify({id:SEL,accion:acc})});
  carga();
}
async function editar(){
  await fetch('/api/tarea/editar',{method:'POST',body:JSON.stringify(
    {id:SEL,detalle:document.getElementById('detalle').value})});
  carga();
}
async function nuevaMeta(){
  const x = document.getElementById('meta-texto');
  if(!x.value.trim())return;
  await fetch('/api/meta',{method:'POST',body:JSON.stringify({texto:x.value})});
  x.value=''; carga();
}
// deep-link: /?sel=<id> abre esa tarea directo (compartible)
const _q = new URLSearchParams(location.search).get('sel');
if(_q) SEL = _q;
carga(); setInterval(carga, 2000);
</script></body></html>"""


def crear_server(oficina, host: str = "127.0.0.1", puerto: int = 8765):
    """ThreadingHTTPServer listo para serve_forever(). El motor va aparte."""

    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, code=200):
            cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            ruta = self.path.split("?", 1)[0]   # ignora el query (?sel=<id>)
            if ruta == "/" or ruta.startswith("/index"):
                cuerpo = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
            elif ruta == "/api/estado":
                self._json(oficina.snapshot())
            else:
                self._json({"error": "no existe"}, 404)

        def do_POST(self):
            b = self._body()
            if self.path == "/api/meta":
                texto = (b.get("texto") or "").strip()
                if not texto:
                    return self._json({"ok": False, "error": "texto vacío"}, 400)
                return self._json({"ok": True, "id": oficina.nueva_meta(texto)})
            if self.path == "/api/tarea/accion":
                ok = oficina.solicitar(b.get("id", ""), b.get("accion", ""))
                return self._json({"ok": ok}, 200 if ok else 400)
            if self.path == "/api/tarea/editar":
                ok = oficina.editar(b.get("id", ""), b.get("detalle", ""))
                return self._json({"ok": ok}, 200 if ok else 400)
            self._json({"error": "no existe"}, 404)

        def log_message(self, *a):  # silencio: el dashboard pollea cada 2 s
            pass

    return ThreadingHTTPServer((host, puerto), Handler)
