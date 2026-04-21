# REGLAS: HTML Templates embebidos en Python (Flask)

## Contexto
Cuando Flask sirve HTML directamente como string Python (`HTML_TEMPLATE = """..."""`),
hay reglas críticas que se deben seguir para evitar errores de JavaScript en el browser.

---

## REGLA 1 — Escapes de \n en strings JS dentro del template

**PROBLEMA:** Dentro de un `"""..."""` en Python, `\n` es un newline REAL (U+000A).
Si ese `\n` está dentro de un string JavaScript, el browser recibe el string partido
en dos líneas → `SyntaxError: Invalid or unexpected token`.

**MAL (rompe JS):**
```python
HTML_TEMPLATE = """
<script>
  addMessage('Juego generado:\n' + titulo, 'game');
  return '--- Archivo: ' + f.name + ' ---\n' + preview;
  }).join('\n\n');
</script>
"""
```

**BIEN (correcto):**
```python
HTML_TEMPLATE = """
<script>
  addMessage('Juego generado:\\n' + titulo, 'game');
  return '--- Archivo: ' + f.name + ' ---\\n' + preview;
  }).join('\\n\\n');
</script>
"""
```

**REGLA:** Todo `\n` que deba ser un escape JavaScript literal dentro de un string JS
debe escribirse como `\\n` en el source Python. El doble backslash `\\` produce un
backslash literal en el valor del string, que el browser interpreta como `\n` de JS.

---

## REGLA 2 — Caracteres no-ASCII en el bloque `<script>`

**PROBLEMA:** Caracteres Unicode como `─` (U+2500), `—` (U+2014), `ó`, `ú`, `📄`, `✕`
dentro del bloque `<script>` pueden causar `SyntaxError` si el browser no recibe el
`Content-Type` con `charset=utf-8` explícito, o si el archivo se transfiere con
encoding incorrecto (ej: Windows CP1252).

**REGLA:** El bloque `<script>` debe contener ÚNICAMENTE caracteres ASCII (0x00–0x7F).

- Comentarios JS: usar `--` en vez de `──`, `---` en vez de `—`
- Emojis en JS strings: usar entidades o texto ASCII (`[doc]` en vez de `📄`)
- Tildes/acentos en JS: evitarlos (`algun` en vez de `algún`)

**BIEN:**
```javascript
// -- Estado global --------------------------------------------------
var _currentMode = 'normal';
dot.title = 'Ollama OK -- ' + count + ' modelos';
```

**MAL:**
```javascript
// ── Estado global ──────────────────────────────────────────────────
dot.title = 'Ollama OK — ' + count + ' modelos';
```

---

## REGLA 3 — Caracteres no-ASCII en el HTML del template (fuera del script)

**PROBLEMA:** Caracteres como `ó`, `📎` en el HTML visible también pueden corromperse.

**REGLA:** Usar entidades HTML para caracteres especiales en el template:
- `ó` → `&oacute;`
- `á` → `&aacute;`
- `é` → `&eacute;`
- `ú` → `&uacute;`
- `ñ` → `&ntilde;`
- `📎` → `&#x1F4CE;`
- `—` → `&mdash;` o `--`

---

## REGLA 4 — Content-Type con charset explícito

**PROBLEMA:** `Response(HTML_TEMPLATE, mimetype='text/html')` no declara charset.
El browser puede asumir latin-1 y corromper caracteres UTF-8.

**REGLA:** Siempre declarar charset en el mimetype:
```python
@app.route("/")
def index():
    from flask import Response
    html_bytes = HTML_TEMPLATE.encode('utf-8')
    return Response(html_bytes,
                    mimetype='text/html; charset=utf-8',
                    headers={'Content-Type': 'text/html; charset=utf-8'})
```

---

## REGLA 5 — Declaración de encoding al inicio del archivo Python

**REGLA:** Agregar la declaración de encoding en la primera o segunda línea del `.py`:
```python
# -*- coding: utf-8 -*-
```
Esto garantiza que Python y editores de texto lean el archivo correctamente en
cualquier sistema operativo, especialmente Windows.

---

## REGLA 6 — setInterval con funciones de actualización de UI

**PROBLEMA:** Llamar `setInterval(function() { updateUI({}); }, 8000)` pasa un
objeto vacío a una función que espera datos reales. Si la función llama `.toFixed()`
sobre `undefined`, lanza un error que puede silenciosamente romper otros listeners.

**REGLA:** El setInterval debe llamar la función que hace el fetch real, no la función
que actualiza el DOM:
```javascript
// MAL:
setInterval(function() { updateFatigueUI({}); }, 8000);

// BIEN:
setInterval(getStats, 8000);  // getStats hace fetch y llama updateFatigueUI con datos reales
```

Y la función de UI debe tener guardias:
```javascript
function updateFatigueUI(d) {
  if (!d || typeof d !== 'object' || d.error) return;
  var score = (typeof d.fatigue_score === 'number') ? d.fatigue_score : 0;
  var strats = Array.isArray(d.active_strategies) ? d.active_strategies : [];
  // ...
}
```

---

## REGLA 7 — Garantizar que el input se desbloquea después de fetch

**PROBLEMA:** Si la cadena de promesas `.then().catch().then()` falla en el `.catch()`,
el `.then()` final (que rehabilita el input) no se ejecuta. El input queda bloqueado
y el usuario no puede enviar más mensajes.

**REGLA:** Llamar el unlock explícitamente en AMBAS ramas (éxito y error):
```javascript
function sendMsg() {
  inp.disabled = true;
  sendBtn.disabled = true;

  function _unlock() {
    inp.disabled = false;
    sendBtn.disabled = false;
    inp.focus();
    statusLine.textContent = 'Listo';
  }

  fetch('/api/chat', { ... })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      // procesar respuesta
      _unlock();  // <- unlock en éxito
    })
    .catch(function(e) {
      addMessage('Error: ' + e.message, 'error');
      _unlock();  // <- unlock en error también
    });
}
```

---

## REGLA 8 — No borrar el `<select>` de modelos al actualizar desde API

**PROBLEMA:** Si `checkOllama()` hace `sel.innerHTML = ''` y repuebla el selector
con los modelos de Ollama, las opciones hardcodeadas desaparecen. Cuando `setMode()`
intenta seleccionar un modelo que ya no existe en el select, falla silenciosamente
y `_currentModel` queda desincronizado.

**REGLA:** Solo AGREGAR opciones nuevas, nunca borrar las existentes:
```javascript
var existingVals = Array.from(sel.options).map(function(o) { return o.value; });
d.models.forEach(function(m) {
  if (existingVals.indexOf(m) === -1) {
    var opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + ' (ollama)';
    sel.appendChild(opt);
  }
});
```

---

## REGLA 9 — El endpoint `/api/chat` no debe retornar HTTP 400

**PROBLEMA:** Un HTTP 400 hace que el fetch entre al `.catch()` en vez del `.then()`.
Si el `.catch()` tiene bugs, el input puede quedar bloqueado.

**REGLA:** Para errores de validación del usuario (texto vacío, etc.), retornar HTTP 200
con un campo `error` en el JSON. Solo retornar 4xx/5xx para errores del servidor:
```python
if not text:
    return jsonify({
        "error": "Texto vacio",
        "response": "Por favor escribe un mensaje."
    })  # 200 OK, el frontend maneja el error
```

---

## CHECKLIST antes de hacer deploy

- [ ] ¿Todos los `\n` dentro de strings JS en el template son `\\n`?
- [ ] ¿El bloque `<script>` tiene 0 caracteres no-ASCII?
- [ ] ¿Los caracteres especiales del HTML usan entidades (`&oacute;`, etc.)?
- [ ] ¿El `Response()` incluye `charset=utf-8` en el mimetype?
- [ ] ¿El archivo `.py` tiene `# -*- coding: utf-8 -*-` al inicio?
- [ ] ¿Todos los `setInterval` llaman funciones que hacen fetch, no las de UI directamente?
- [ ] ¿El unlock del input se llama en `.then()` Y en `.catch()`?
- [ ] ¿El selector de modelos nunca se borra con `innerHTML = ''`?

## Cómo verificar antes de hacer push

```python
# Ejecutar esto para validar el template:
import ast, subprocess

with open('web_app.py', 'r', encoding='utf-8') as f:
    src = f.read()

# 1. Syntax Python
ast.parse(src)

# 2. Evaluar template como Flask lo haría y validar JS con Node
html_s = src.find('HTML_TEMPLATE = """') + len('HTML_TEMPLATE = """')
html_e = src.find('"""\n\n\n# ===', html_s)
local_ns = {}
exec(f'_html = """{src[html_s:html_e]}"""', local_ns)
html = local_ns['_html']

js = html[html.find('<script>\n')+9 : html.find('\n</script>')]
with open('/tmp/check.js', 'w') as f:
    f.write(js)

r = subprocess.run(['node', '--check', '/tmp/check.js'], capture_output=True, text=True)
print('JS:', 'OK' if r.returncode == 0 else r.stderr)

# 3. Verificar 0 no-ASCII en el JS
bad = [(i,ch) for i,ch in enumerate(js) if ord(ch) > 127]
print(f'No-ASCII en JS: {len(bad)}')
```
