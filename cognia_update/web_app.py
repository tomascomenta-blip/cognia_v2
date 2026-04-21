"""
web_app_improved.py -- Cognia v3 Mejorado
==========================================
Mejoras implementadas:
  1. Fix del sistema de envio de prompts (ruta /api/chat estabilizada)
  2. Sistema autonomo de busqueda cuando idle
  3. Modulo de creacion de juegos mejorado (sin duplicados, mejora iterativa)
  4. Validacion y correccion de codigo generado
  5. Estabilidad general del sistema
"""

from flask import Flask, request, jsonify, render_template_string, session
import os, sys, json, threading, time
from datetime import datetime

# -- Config -------------------------------------------------------------------
try:
    from config import TUTOR_PASSWORD, SESSION_TOKEN, HOST, PORT, DEBUG
except ImportError:
    TUTOR_PASSWORD = os.environ.get("COGNIA_PASSWORD", "cognia-v3")
    SESSION_TOKEN  = os.urandom(16).hex()
    HOST  = "0.0.0.0"
    PORT  = int(os.environ.get("PORT", 5000))
    DEBUG = False

from cognia import Cognia

app = Flask(__name__)
app.secret_key = SESSION_TOKEN

_cognia = None
_cognia_lock = threading.Lock()

def get_cognia():
    global _cognia
    if _cognia is None:
        with _cognia_lock:
            if _cognia is None:
                _cognia = Cognia()
    return _cognia


# =============================================================================
#  HTML TEMPLATE
# =============================================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cognia v3</title>
<style>
  :root {
    --bg:#0d0d10;--surface:#16161a;--surface2:#1e1e24;--border:#2a2a35;
    --accent:#6c63ff;--accent2:#00d4aa;--text:#e8e8f0;--text2:#8888aa;
    --warn:#ff6b6b;--ok:#51cf66;--mono:'JetBrains Mono','Fira Code',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:14px;min-height:100vh}
  header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 20px;
         display:flex;align-items:center;gap:12px}
  header h1{font-size:18px;color:var(--accent);letter-spacing:1px}
  .version{background:var(--accent);color:#fff;font-size:10px;padding:2px 8px;border-radius:10px}
  .status-badge{margin-left:auto;font-size:12px;display:flex;gap:10px;align-items:center}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}
  .dot.warn{background:var(--warn);animation:pulse 1.2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .container{display:grid;grid-template-columns:1fr 340px;height:calc(100vh - 49px)}
  .chat-panel{display:flex;flex-direction:column;border-right:1px solid var(--border)}
  .messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
  .msg{padding:10px 14px;border-radius:8px;max-width:92%;white-space:pre-wrap;line-height:1.6;font-size:13px}
  .msg.user{background:var(--accent);color:#fff;align-self:flex-end}
  .msg.bot{background:var(--surface2);border:1px solid var(--border);align-self:flex-start}
  .msg.system{background:transparent;border:1px dashed var(--border);color:var(--text2);
              align-self:center;font-size:11px;text-align:center}
  .msg.error{background:#200;border:1px solid var(--warn);color:var(--warn);align-self:flex-start}
  .msg.game{background:#0a1a0a;border:1px solid var(--ok);align-self:flex-start}
  .input-row{padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px;align-items:center}
  #mainInput{flex:1;background:var(--surface2);border:1px solid var(--border);color:var(--text);
             padding:10px 14px;border-radius:6px;font-family:var(--mono);font-size:13px;outline:none}
  #mainInput:focus{border-color:var(--accent)}
  #mainInput:disabled{opacity:.5;cursor:not-allowed}
  .btn{background:var(--accent);color:#fff;border:none;padding:10px 18px;border-radius:6px;
       cursor:pointer;font-family:var(--mono);font-size:13px;transition:opacity .2s}
  .btn:hover{opacity:.85}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .btn.sm{padding:5px 10px;font-size:11px}
  .btn.green{background:var(--accent2);color:#000}
  .btn.red{background:#500}
  .side-panel{background:var(--surface);overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:14px}
  .side-section h3{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text2);margin-bottom:8px}
  .cmd-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}
  .cmd-btn{background:var(--surface2);border:1px solid var(--border);color:var(--text);
           padding:6px 8px;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:11px;text-align:left}
  .cmd-btn:hover{border-color:var(--accent);color:var(--accent)}
  .stats-grid{display:grid;gap:4px}
  .stat-row{display:flex;justify-content:space-between;font-size:12px;padding:3px 0;border-bottom:1px solid var(--border)}
  .stat-row .val{color:var(--accent2)}
  .quick-learn{display:flex;gap:6px}
  .quick-learn input{flex:1;background:var(--surface2);border:1px solid var(--border);
                     color:var(--text);padding:5px 8px;border-radius:4px;font-family:var(--mono);font-size:11px}
  .fatigue-bar-wrap{background:var(--surface2);border:1px solid var(--border);border-radius:4px;
                    height:8px;overflow:hidden;margin:6px 0 2px}
  .fatigue-bar{height:100%;border-radius:4px;transition:width .6s ease,background .6s ease}
  .fatigue-label{display:flex;justify-content:space-between;font-size:11px;color:var(--text2)}
  .fatigue-badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:bold}
  .fatigue-baja{background:#1a3a1a;color:#51cf66;border:1px solid #51cf66}
  .fatigue-moderada{background:#3a2e00;color:#ffd700;border:1px solid #ffd700}
  .fatigue-alta{background:#3a1a00;color:#ff9500;border:1px solid #ff9500}
  .fatigue-critica{background:#3a0000;color:#ff6b6b;border:1px solid #ff6b6b;animation:pulse 1.2s infinite}
  .idle-indicator{font-size:11px;color:var(--text2);padding:4px 8px;background:var(--surface2);
                  border-radius:4px;border:1px solid var(--border)}
  .idle-indicator.active{border-color:var(--accent2);color:var(--accent2)}
  .game-card{background:var(--surface2);border:1px solid var(--border);border-radius:6px;
             padding:8px;margin-bottom:4px;font-size:11px}
  .game-card .score{color:var(--accent2);font-size:13px;font-weight:bold}
  .game-card .title{color:var(--text);margin-bottom:2px}
  .game-card .meta{color:var(--text2);font-size:10px}
  .progress{height:4px;background:var(--surface2);border-radius:2px;overflow:hidden;margin-top:4px}
  .progress-bar{height:100%;background:var(--accent);border-radius:2px;transition:width .5s}
  textarea.fact-input{background:var(--surface2);border:1px solid var(--border);color:var(--text);
                      padding:6px;border-radius:4px;font-family:var(--mono);font-size:11px;
                      width:100%;resize:vertical;min-height:60px}
  ::-webkit-scrollbar{width:4px}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
</style>
</head>
<body>
<header>
  <h1>COGNIA</h1>
  <span class="version">v3+</span>
  <div class="status-badge">
    <span class="idle-indicator" id="idleIndicator">Activo</span>
    <span id="ollama-dot" class="dot warn" title="Verificando Ollama..."></span>
    <span id="statusLine" style="color:var(--text2)">Listo</span>
  </div>
</header>

<div class="container">
  <div class="chat-panel">
    <div class="messages" id="messages">
      <div class="msg system">COGNIA v3+ Sistema mejorado con auto-correccion de codigo, juegos iterativos y modo autonomo</div>
    </div>
    <div class="input-row">
      <input type="text" id="mainInput"
             placeholder="Escribe un mensaje, o usa los comandos del panel"
             autofocus>
      <button class="btn" id="sendBtn">Enviar</button>
    </div>
  </div>

  <div class="side-panel">

    <div class="side-section">
      <h3>Aprender</h3>
      <div class="quick-learn">
        <input id="learnText" placeholder="texto a aprender">
        <input id="learnLabel" placeholder="etiqueta" style="max-width:90px">
        <button class="btn sm green" onclick="quickLearn()">+</button>
      </div>
    </div>

    <div class="side-section">
      <h3>Fatiga Cognitiva</h3>
      <div class="fatigue-bar-wrap">
        <div class="fatigue-bar" id="fatigueBar" style="width:0%;background:#51cf66"></div>
      </div>
      <div class="fatigue-label">
        <span id="fatigueScore">-</span>
        <span id="fatigueBadge" class="fatigue-badge fatigue-baja">BAJA</span>
      </div>
      <div class="stats-grid" style="margin-top:6px">
        <div class="stat-row"><span>CPU</span><span class="val" id="f-cpu">-</span></div>
        <div class="stat-row"><span>Memoria RSS</span><span class="val" id="f-mem">-</span></div>
        <div class="stat-row"><span>Ciclo avg</span><span class="val" id="f-cycle">-</span></div>
        <div class="stat-row"><span>Modo</span><span class="val" id="f-mode">normal</span></div>
      </div>
    </div>

    <div class="side-section">
      <h3>Modo Autonomo</h3>
      <div class="stats-grid">
        <div class="stat-row"><span>Estado</span><span class="val" id="auto-status">esperando</span></div>
        <div class="stat-row"><span>Ultima accion</span><span class="val" id="auto-last">-</span></div>
        <div class="stat-row"><span>Inactivo hace</span><span class="val" id="auto-idle">0s</span></div>
        <div class="stat-row"><span>Busquedas realizadas</span><span class="val" id="auto-searches">0</span></div>
      </div>
      <div style="display:flex;gap:4px;margin-top:6px">
        <button class="btn sm" onclick="triggerAutonomous()">Forzar ciclo</button>
        <button class="btn sm red" onclick="pauseAutonomous()">Pausar</button>
      </div>
    </div>

    <div class="side-section">
      <h3>Biblioteca de Juegos</h3>
      <div id="gameLibrary">
        <div style="font-size:11px;color:var(--text2)">Cargando...</div>
      </div>
      <div style="display:flex;gap:4px;margin-top:6px">
        <button class="btn sm green" onclick="generateGame()">Generar juego</button>
        <button class="btn sm" onclick="improveGames()">Mejorar</button>
      </div>
      <div class="progress" id="gameProgress" style="display:none">
        <div class="progress-bar" id="gameProgressBar" style="width:0%"></div>
      </div>
    </div>

    <div class="side-section">
      <h3>Comandos Rapidos</h3>
      <div class="cmd-grid">
        <button class="cmd-btn" onclick="cmd('yo')">Introspeccion</button>
        <button class="cmd-btn" onclick="cmd('conceptos')">Conceptos</button>
        <button class="cmd-btn" onclick="cmd('dormir')">Dormir</button>
        <button class="cmd-btn" onclick="cmd('repasar')">Repasar</button>
        <button class="cmd-btn" onclick="cmd('contradicciones')">Contradiccion</button>
        <button class="cmd-btn" onclick="cmd('objetivos')">Objetivos</button>
        <button class="cmd-btn" onclick="cmd('olvido')">Olvido</button>
        <button class="cmd-btn" onclick="cmd('fatiga')">Fatiga</button>
        <button class="cmd-btn" onclick="promptGraph()">Grafo</button>
        <button class="cmd-btn" onclick="promptInfer()">Inferir</button>
        <button class="cmd-btn" onclick="promptPredict()">Predecir</button>
        <button class="cmd-btn" onclick="cmd('biblioteca')">Biblioteca</button>
        <button class="cmd-btn" onclick="promptHipotesis()"
                style="grid-column:span 2;border-color:var(--accent2);color:var(--accent2)">
          Hipotesis Creativa
        </button>
      </div>
    </div>

    <div class="side-section">
      <h3>Estado Cognitivo</h3>
      <div class="stats-grid" id="statsGrid">
        <div class="stat-row"><span>Memorias activas</span><span class="val" id="s-active">-</span></div>
        <div class="stat-row"><span>Conceptos</span><span class="val" id="s-concepts">-</span></div>
        <div class="stat-row"><span>Aristas KG</span><span class="val" id="s-kg">-</span></div>
        <div class="stat-row"><span>Contradicciones</span><span class="val" id="s-contr">-</span></div>
        <div class="stat-row"><span>Programas guardados</span><span class="val" id="s-programs">-</span></div>
      </div>
    </div>

    <div class="side-section">
      <h3>Agregar Hecho al Grafo</h3>
      <div style="display:flex;flex-direction:column;gap:4px">
        <input class="cmd-btn" id="factSubj" placeholder="sujeto" style="cursor:text">
        <input class="cmd-btn" id="factPred" placeholder="relacion (is_a, part_of...)" style="cursor:text">
        <input class="cmd-btn" id="factObj"  placeholder="objeto"  style="cursor:text">
        <button class="btn sm" onclick="addFact()" style="width:100%;text-align:center">
          Agregar al grafo
        </button>
      </div>
    </div>

  </div>
</div>

<script>
var $ = function(id) { return document.getElementById(id); };

function api(endpoint, data, method) {
  data = data || {};
  method = method || 'POST';
  var opts = {
    method: method,
    headers: {'Content-Type': 'application/json'}
  };
  if (method !== 'GET') opts.body = JSON.stringify(data);
  return fetch(endpoint, opts).then(function(r) {
    if (!r.ok) {
      return r.text().then(function(txt) {
        throw new Error('HTTP ' + r.status + ': ' + txt.slice(0, 200));
      });
    }
    return r.json();
  }).catch(function(e) {
    console.error('[api]', endpoint, e);
    return {error: e.message || 'Error de red'};
  });
}

var _lastQuestion = '';
var _idleTimer = 0;
var _idleInterval = null;
var _autonomousPaused = false;

function addMessage(text, type, extras) {
  type = type || 'bot';
  extras = extras || null;
  var msgs = $('messages');
  var div = document.createElement('div');
  div.className = 'msg ' + type;
  div.textContent = text;

  if (type === 'bot' && extras && extras.fatigue) {
    var f = extras.fatigue;
    var colors = {baja:'#51cf66', moderada:'#ffd700', alta:'#ff9500', critica:'#ff6b6b'};
    var col = colors[f.level] || '#888';
    var tag = document.createElement('span');
    tag.style.cssText = 'font-size:10px;padding:1px 6px;border-radius:8px;margin-left:8px;'
                      + 'color:' + col + ';border:1px solid ' + col;
    tag.textContent = f.score + ' ' + f.level;
    div.appendChild(tag);

    var fb = document.createElement('div');
    fb.style.cssText = 'display:flex;gap:6px;margin-top:6px';
    var q = _lastQuestion;
    ['+1', '-1'].forEach(function(em, i) {
      var b = document.createElement('button');
      b.textContent = em;
      var c = i ? 'var(--warn)' : 'var(--ok)';
      b.style.cssText = 'background:transparent;border:1px solid ' + c
                      + ';color:' + c + ';padding:2px 10px;border-radius:4px;cursor:pointer;font-size:12px';
      b.onclick = (function(pos, qq, row) {
        return function() { sendFeedback(pos, qq, row); };
      })(!i, q, fb);
      fb.appendChild(b);
    });
    div.appendChild(fb);
  }

  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function sendFeedback(positive, pregunta, fbRow) {
  fbRow.style.opacity = '0.4';
  fbRow.style.pointerEvents = 'none';
  api('/api/feedback', {positive: positive, pregunta: pregunta}).then(function() {
    var t = document.createElement('span');
    t.textContent = positive ? ' ok gracias' : ' ok anotado';
    t.style.cssText = 'font-size:11px;color:var(--text2)';
    fbRow.appendChild(t);
  });
}

function sendMsg() {
  _markActivity()
  var inp = $('mainInput');
  var text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  inp.disabled = true;
  $('sendBtn').disabled = true;
  addMessage(text, 'user');
  _lastQuestion = text;
  $('statusLine').textContent = 'Procesando...';
  resetIdleTimer();

  var controller = new AbortController();
  var tout = setTimeout(function() { controller.abort(); }, 180000);

  fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: text}),
    signal: controller.signal
  }).then(function(resp) {
    clearTimeout(tout);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    return resp.json();
  }).then(function(r) {
    if (r.error) {
      addMessage('Error: ' + r.error, 'error');
    } else {
      if (r._architect && r._architect.proposals > 0) {
        addMessage('SelfArchitect: ' + r._architect.proposals + ' propuesta(s) nueva(s).', 'system');
      }
      addMessage(r.response || '(sin respuesta)', 'bot', {fatigue: r.fatigue});
    }
  }).catch(function(e) {
    clearTimeout(tout);
    if (e.name === 'AbortError') {
      addMessage('Timeout: el servidor no respondio en 60s.', 'error');
    } else {
      addMessage('Error: ' + e.message, 'error');
    }
  }).then(function() {
    inp.disabled = false;
    $('sendBtn').disabled = false;
    inp.focus();
    $('statusLine').textContent = 'Listo';
    getStats();
  });
}

$('mainInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
});

function resetIdleTimer() {
  _idleTimer = 0;
  $('idleIndicator').textContent = 'Activo';
  $('idleIndicator').className = 'idle-indicator';
  $('auto-idle').textContent = '0s';
}

function startIdleTracking() {
  _idleInterval = setInterval(function() {
    _idleTimer++;
    $('auto-idle').textContent = _idleTimer + 's';
    if (_idleTimer === 60 && !_autonomousPaused) {
      $('idleIndicator').textContent = 'Modo autonomo';
      $('idleIndicator').className = 'idle-indicator active';
      triggerAutonomousBackground();
    }
  }, 1000);
}

function triggerAutonomousBackground() {
  if (_autonomousPaused) return;
  $('auto-status').textContent = 'ejecutando...';
  api('/api/autonomous/cycle', {}).then(function(r) {
    if (r.action) {
      $('auto-status').textContent = 'OK ' + r.action;
      $('auto-last').textContent = r.action.slice(0, 20) + '...';
      $('auto-searches').textContent = r.searches_done || 0;
      if (r.message) addMessage('[Autonomo] ' + r.message, 'system');
    }
  }).catch(function() {
    $('auto-status').textContent = 'error';
  });
}

function triggerAutonomous() {
  resetIdleTimer();
  addMessage('Forzando ciclo autonomo...', 'system');
  triggerAutonomousBackground();
}

function pauseAutonomous() {
  _autonomousPaused = !_autonomousPaused;
  $('auto-status').textContent = _autonomousPaused ? 'pausado' : 'esperando';
  addMessage('Modo autonomo: ' + (_autonomousPaused ? 'pausado' : 'activado'), 'system');
}

function loadGameLibrary() {
  api('/api/games/library', {}, 'GET').then(function(r) {
    var lib = $('gameLibrary');
    if (!r.games || r.games.length === 0) {
      lib.innerHTML = '<div style="font-size:11px;color:var(--text2)">Sin juegos aun -- usa Generar</div>';
      return;
    }
    lib.innerHTML = r.games.slice(0, 5).map(function(g) {
      var sc = g.total_score ? g.total_score.toFixed(1) : '?';
      var imp = g.improved ? '<div style="color:var(--accent2);font-size:10px">Mejorado</div>' : '';
      var card = '<div class="game-card">';
      card += '<div class="title">' + (g.title || '') + '</div>';
      card += '<div class="meta">' + (g.category || '') + ' v' + (g.version || 1);
      card += ' <span class="score">' + sc + '/10</span></div>';
      card += imp + '</div>';
      return card;
    }).join('');
    $('s-programs').textContent = r.total || 0;
  }).catch(function() {});
}

function generateGame() {
  addMessage('Generando juego... esto puede tomar 30-60s', 'system');
  var prog = $('gameProgress');
  var bar  = $('gameProgressBar');
  prog.style.display = 'block';

  var pct = 0;
  var anim = setInterval(function() {
    pct = Math.min(pct + Math.random() * 8, 90);
    bar.style.width = pct + '%';
  }, 800);

  api('/api/games/generate', {max_attempts: 2}).then(function(r) {
    clearInterval(anim);
    bar.style.width = '100%';
    setTimeout(function() { prog.style.display = 'none'; bar.style.width = '0%'; }, 1000);

    if (r.error) {
      addMessage('Error generando juego: ' + r.error, 'error');
    } else if (r.stored > 0) {
      var title = (r.programs && r.programs[0]) ? r.programs[0].title : '?';
      var score = (r.programs && r.programs[0] && r.programs[0].total_score)
                  ? r.programs[0].total_score.toFixed(1) : '?';
      var tipo  = r.is_improvement ? 'Mejora de version anterior' : 'Nuevo juego';
      addMessage('Juego generado: "' + title + '" (score: ' + score + '/10)\\n' + tipo, 'game');
      loadGameLibrary();
    } else {
      addMessage('No se pudo generar un juego que pase el evaluador. Intenta de nuevo.', 'system');
    }
  }).catch(function(e) {
    clearInterval(anim);
    prog.style.display = 'none';
    addMessage('Error: ' + e.message, 'error');
  });
}

function improveGames() {
  addMessage('Mejorando juegos existentes...', 'system');
  api('/api/games/improve', {}).then(function(r) {
    if (r.improved > 0) {
      var detalles = (r.details && r.details.length) ? r.details.join('\\n') : '';
      addMessage(r.improved + ' juego(s) mejorado(s):\\n' + detalles, 'game');
      loadGameLibrary();
    } else {
      addMessage(r.message || 'No hay juegos para mejorar', 'system');
    }
  }).catch(function(e) {
    addMessage('Error: ' + e.message, 'error');
  });
}

function getStats() {
  fetch('/api/stats').then(function(r) { return r.json(); }).then(function(d) {
    $('s-active').textContent   = (d.active_memories   !== undefined) ? d.active_memories   : '-';
    $('s-concepts').textContent = (d.concepts           !== undefined) ? d.concepts           : '-';
    $('s-kg').textContent       = (d.kg_edges            !== undefined) ? d.kg_edges            : '-';
    $('s-contr').textContent    = (d.contradictions_pending !== undefined) ? d.contradictions_pending : '-';
  }).catch(function() {});

  fetch('/api/fatiga').then(function(f) { return f.json(); }).then(function(d) {
    if (!d.error) updateFatigueUI(d);
  }).catch(function() {});
}

function updateFatigueUI(d) {
  var score  = d.fatigue_score || 0;
  var level  = d.fatigue_level || 'baja';
  var colors = {baja:'#51cf66', moderada:'#ffd700', alta:'#ff9500', critica:'#ff6b6b'};
  $('fatigueBar').style.width       = score + '%';
  $('fatigueBar').style.background  = colors[level] || '#51cf66';
  $('fatigueScore').textContent     = score.toFixed(1) + ' / 100';
  $('fatigueBadge').textContent     = level.toUpperCase();
  $('fatigueBadge').className       = 'fatigue-badge fatigue-' + level;
  $('f-cpu').textContent            = (d.current_cpu_pct  || 0).toFixed(1) + '%';
  $('f-mem').textContent            = (d.current_mem_mb   || 0).toFixed(0) + ' MB';
  $('f-cycle').textContent          = (d.avg_cycle_ms     || 0).toFixed(0) + ' ms';
  var strats = d.active_strategies || [];
  $('f-mode').textContent = strats.length ? strats[0].replace(/_/g, ' ') : 'normal';
}

function checkOllama() {
  fetch('/api/ollama_status').then(function(r) { return r.json(); }).then(function(d) {
    var dot = $('ollama-dot');
    if (d.ok) {
      dot.style.background = 'var(--ok)';
      dot.style.animation  = 'none';
      dot.title = 'Ollama OK';
    } else {
      dot.style.background = 'var(--warn)';
      dot.style.animation  = 'pulse 1.2s infinite';
      dot.title = 'Ollama offline';
    }
  }).catch(function() {
    $('ollama-dot').style.background = 'var(--warn)';
  });
}

function cmd(command) {
  _markActivity()
  addMessage(command, 'user');
  resetIdleTimer();
  $('statusLine').textContent = 'Procesando...';
  api('/api/command', {command: command}).then(function(r) {
    addMessage(r.response || r.error || 'Error', 'bot');
    $('statusLine').textContent = 'Listo';
    getStats();
  });
}

function quickLearn() {
  var text  = $('learnText').value.trim();
  var label = $('learnLabel').value.trim();
  if (!text || !label) return;
  addMessage('aprender: "' + text + '" | ' + label, 'user');
  resetIdleTimer();
  api('/api/learn', {text: text, label: label}).then(function(r) {
    addMessage(r.response || r.error, 'bot');
    $('learnText').value  = '';
    $('learnLabel').value = '';
    getStats();
  });
}

function addFact() {
  var s = $('factSubj').value.trim();
  var p = $('factPred').value.trim();
  var o = $('factObj').value.trim();
  if (!s || !p || !o) return;
  addMessage('hecho: ' + s + ' | ' + p + ' | ' + o, 'user');
  resetIdleTimer();
  api('/api/add_fact', {subject: s, predicate: p, object: o}).then(function(r) {
    addMessage(r.response || r.error, 'bot');
    ['factSubj', 'factPred', 'factObj'].forEach(function(id) { $(id).value = ''; });
    getStats();
  });
}

function promptHipotesis() {
  var ca = prompt('Concepto A (vacio = automatico):') || '';
  var cb = prompt('Concepto B (vacio = automatico):') || '';
  addMessage('hipotesis: ' + (ca || '?') + ' <-> ' + (cb || '?'), 'user');
  resetIdleTimer();
  $('statusLine').textContent = 'Generando hipotesis...';
  api('/api/hipotesis', {concepto_a: ca || 'inteligencia_artificial', concepto_b: cb || ''}).then(function(r) {
    var msg = r.response
      ? '[' + r.concepto_a + ' <-> ' + r.concepto_b + ']:\\n' + r.response
      : (r.error || 'Error');
    addMessage(msg, 'bot');
    $('statusLine').textContent = 'Listo';
    getStats();
  });
}

function promptGraph()   { var c = prompt('Concepto para el grafo:');   if (c) cmd('grafo '    + c); }
function promptInfer()   { var c = prompt('Concepto para inferir:');    if (c) cmd('inferir '  + c); }
function promptPredict() { var c = prompt('Concepto para predecir:');   if (c) cmd('predecir ' + c); }

$('sendBtn').addEventListener('click', sendMsg);
getStats();
checkOllama();
loadGameLibrary();
startIdleTracking();

setTimeout(function() {
  fetch('/api/ollama_status')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.ok) addMessage('Ollama offline - el chat funciona en modo fallback.', 'system');
    }).catch(function() {});
}, 1500);

// ── Polling adaptativo: se ralentiza cuando el usuario está inactivo ──────
var _lastActivity = Date.now();

function _markActivity() { _lastActivity = Date.now(); }

function adaptiveStats() {
    var idleSec = (Date.now() - _lastActivity) / 1000;
    getStats();
    setTimeout(adaptiveStats, idleSec > 120 ? 60000 : 20000);
}
function adaptiveGames() {
    var idleSec = (Date.now() - _lastActivity) / 1000;
    loadGameLibrary();
    setTimeout(adaptiveGames, idleSec > 120 ? 120000 : 30000);
}

setTimeout(adaptiveStats,  20000);
setTimeout(adaptiveGames,  30000);
setInterval(checkOllama,   60000);
setInterval(function() { updateFatigueUI({}); }, 8000);
</script>
</body>
</html>
"""


# =============================================================================
#  RUTAS PRINCIPALES
# =============================================================================

@app.route("/")
def index():
    from flask import Response
    return Response(HTML_TEMPLATE, mimetype='text/html')


@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or data.get("prompt") or "").strip()

        if not text:
            return jsonify({"error": "Texto vacio -- escribe algo y presiona Enviar"}), 400

        ai = get_cognia()

        try:
            from respuestas_articuladas import responder_articulado
            result = responder_articulado(ai, text)
        except Exception as e:
            print("[api/chat] Fallback por error en responder_articulado: " + str(e))
            result = _fallback_response(ai, text)

        try:
            # Paso 4: usar self.architect de Cognia (singleton, ya inicializado)
            architect = getattr(ai, "architect", None)
            if architect is None:
                # Fallback: instancia local si Cognia no lo tiene
                from self_architect import SelfArchitect
                if not hasattr(api_chat, "_architect"):
                    api_chat._architect = SelfArchitect(cognia_instance=ai)
                architect = api_chat._architect
            eval_result = architect.tick(ai.interaction_count)
            if eval_result and eval_result.get("proposals_generated", 0) > 0:
                result["_architect"] = {
                    "score":     eval_result["score"],
                    "proposals": eval_result["proposals_generated"],
                    "critical":  eval_result.get("has_critical", False),
                }
        except Exception:
            pass

        try:
            if hasattr(ai, "fatigue") and ai.fatigue:
                fs = ai.fatigue.get_state()
                result["fatigue"] = {
                    "score": fs["fatigue_score"],
                    "level": fs["fatigue_level"],
                    "energy_watts": fs.get("energy_watts", 0),
                }
        except Exception:
            pass

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Error interno: " + str(e),
            "response": "Lo siento, ocurrio un error interno. Revisa los logs del servidor."
        }), 500


def _fallback_response(ai, text):
    try:
        from cognia.vectors import text_to_vector
        vec = text_to_vector(text)
        similares = ai.episodic.retrieve_similar(vec, top_k=3)
        if similares and similares[0]["similarity"] > 0.3:
            obs = similares[0]["observation"][:200]
            return {"response": "[Sin Ollama] Recuerdo algo relacionado: " + obs}
    except Exception:
        pass
    return {"response": "[Sin Ollama] Recibi tu mensaje: '" + text + "'. "
                        "Ollama no esta disponible. Inicia Ollama y prueba de nuevo."}


@app.route("/api/learn", methods=["POST"])
def api_learn():
    data   = request.get_json(silent=True) or {}
    text   = (data.get("text")  or "").strip()
    label  = (data.get("label") or "").strip()
    source = (data.get("source") or "api").strip()
    if not text or not label:
        return jsonify({"error": "text y label son requeridos"})
    ai = get_cognia()

    # Paso 3+4: pasar por TeacherInterface (guard + corrector + observe)
    teacher = getattr(ai, "teacher", None)
    if teacher:
        result = teacher.correct(text, label, source=source)
        return jsonify(result)

    # Fallback al comportamiento original
    return jsonify({"response": ai.learn(text, label)})


@app.route("/api/command", methods=["POST"])
def api_command():
    data    = request.get_json(silent=True) or {}
    command = (data.get("command") or "").strip()
    ai = get_cognia()

    dispatch = {
        "yo":              lambda: ai.introspect(),
        "conceptos":       lambda: ai.list_concepts(),
        "dormir":          lambda: ai.sleep(),
        "repasar":         lambda: ai.review_due(),
        "contradicciones": lambda: ai.show_contradictions(),
        "objetivos":       lambda: ai.show_goals(),
        "olvido":          lambda: ai.forget_cycle(),
        "fatiga":          lambda: ai.fatigue_status() if hasattr(ai, "fatigue_status") else "Monitor no disponible",
        "biblioteca":      lambda: _library_summary(),
    }

    if command in dispatch:
        return jsonify({"response": dispatch[command]()})

    for prefix, handler in [
        ("grafo ",    lambda t: ai.show_graph(t)),
        ("inferir ",  lambda t: ai.infer_about(t)),
        ("predecir ", lambda t: ai.predict_next(t)),
        ("explicar ", lambda t: ai.explain(t)),
    ]:
        if command.startswith(prefix):
            topic = command[len(prefix):].strip()
            return jsonify({"response": handler(topic)})

    return jsonify({"error": "Comando desconocido: " + command})


def _library_summary():
    try:
        from game_manager import get_game_manager
        gm = get_game_manager()
        return gm.format_library_summary()
    except Exception:
        try:
            from program_creator import show_library
            return show_library()
        except Exception as e:
            return "No se pudo cargar la biblioteca: " + str(e)


@app.route("/api/add_fact", methods=["POST"])
def api_add_fact():
    data = request.get_json(silent=True) or {}
    s = (data.get("subject") or "").strip()
    p = (data.get("predicate") or "").strip()
    o = (data.get("object") or "").strip()
    if not s or not p or not o:
        return jsonify({"error": "subject, predicate, object son requeridos"})
    return jsonify({"response": get_cognia().add_fact(s, p, o)})


@app.route("/api/stats")
def api_stats():
    ai = get_cognia()
    stats = ai.metacog.introspect()
    try:
        from game_manager import get_game_manager
        stats["programs_count"] = get_game_manager().get_total_count()
    except Exception:
        pass
    return jsonify(stats)


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data        = request.get_json(silent=True) or {}
    correct     = data.get("correct")
    positive    = data.get("positive")
    correction  = data.get("correction", "")
    response_id = data.get("response_id", "")

    if correct is None and positive is not None:
        correct = bool(positive)

    if not response_id:
        try:
            import sqlite3
            ai = get_cognia()
            db = getattr(ai.episodic, "db", "cognia_memory.db")
            conn = sqlite3.connect(db)
            conn.text_factory = str
            c = conn.cursor()
            c.execute("SELECT response_id FROM chat_history WHERE role='assistant' "
                      "AND response_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            if row:
                response_id = row[0]
        except Exception:
            pass

    if not response_id:
        return jsonify({"ok": True, "message": "Feedback registrado (sin response_id)"})

    try:
        result = get_cognia().apply_feedback(response_id, bool(correct), correction or None)
        return jsonify({"ok": True, "message": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/fatiga")
def api_fatiga():
    ai = get_cognia()
    if hasattr(ai, "fatigue") and ai.fatigue:
        return jsonify(ai.fatigue.get_state())
    return jsonify({"error": "Monitor de fatiga no disponible"})


@app.route("/api/ollama_status")
def api_ollama_status():
    try:
        from respuestas_articuladas import verificar_ollama
        return jsonify(verificar_ollama())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/health")
def api_health():
    return jsonify(get_cognia().get_memory_health())


@app.route("/api/chat_history")
def api_chat_history():
    n = int(request.args.get("n", 20))
    return jsonify(get_cognia().chat_history.get_recent(n))


@app.route("/api/hipotesis", methods=["POST"])
def api_hipotesis():
    import random
    data = request.get_json(silent=True) or {}
    ca = (data.get("concepto_a") or "").strip().lower()
    cb = (data.get("concepto_b") or "").strip().lower()

    if not ca:
        return jsonify({"error": "concepto_a requerido"})

    ai = get_cognia()

    if not cb:
        conceptos = ai.semantic.list_all()
        buenos = [c for c in conceptos
                  if c.get("confidence", 0) >= 0.4 and c["concept"] != ca and len(c["concept"]) > 3]
        if buenos:
            cb = random.choice(buenos)["concept"]

    if not cb:
        return jsonify({"error": "No tengo suficientes conceptos aun"})

    result = ai.generate_hypothesis(ca, cb)
    return jsonify({
        "response":   result if isinstance(result, str) else str(result),
        "concepto_a": ca,
        "concepto_b": cb
    })


@app.route("/api/graph/<concept>")
def api_graph(concept):
    ai = get_cognia()
    facts = ai.kg.get_facts(concept, predicate=None)
    if not facts:
        return jsonify({"nodes": [], "links": [], "concept": concept})
    nodes_set, links = set(), []
    for f in facts[:50]:
        nodes_set.add(f["subject"])
        nodes_set.add(f["object"])
        links.append({"source": f["subject"], "target": f["object"],
                      "relation": f["predicate"], "weight": round(f["weight"], 2)})
    nodes = [{"id": n, "group": 1 if n == concept else 2} for n in nodes_set]
    return jsonify({"nodes": nodes, "links": links, "concept": concept})


# =============================================================================
#  SISTEMA AUTONOMO + JUEGOS
# =============================================================================

@app.route("/api/autonomous/cycle", methods=["POST"])
def api_autonomous_cycle():
    try:
        from autonomous_manager import AutonomousManager
        am = AutonomousManager.get_instance(get_cognia())
        result = am.run_cycle()
        return jsonify(result)
    except ImportError:
        return jsonify(_basic_autonomous_cycle())
    except Exception as e:
        return jsonify({"action": "error", "message": str(e)})


def _basic_autonomous_cycle():
    ai = get_cognia()
    try:
        if hasattr(ai, "curiosity_engine") and ai.curiosity_engine:
            pending = ai.curiosity_engine.get_pending_proposals()
            if pending:
                proposal = pending[0]
                from researcher import research_question
                result = research_question(proposal)
                if result:
                    from knowledge_integrator import integrate_research
                    db = getattr(ai.episodic, "db", "cognia_memory.db")
                    integration = integrate_research(result, ai, db)
                    return {
                        "action":       "research",
                        "message":      "Investigue: " + str(result.topic) + " (+" + str(integration.triples_added) + " triples)",
                        "searches_done": 1
                    }
    except Exception:
        pass

    try:
        ai.sleep()
        return {"action": "sleep_cycle", "message": "Ciclo de consolidacion de memoria", "searches_done": 0}
    except Exception:
        return {"action": "idle", "message": "Sin tareas pendientes", "searches_done": 0}


@app.route("/api/games/library", methods=["GET"])
def api_games_library():
    try:
        from game_manager import get_game_manager
        gm = get_game_manager()
        games = gm.list_games()
        return jsonify({"games": games, "total": len(games)})
    except ImportError:
        from storage import list_programs
        programs = list_programs()
        return jsonify({
            "games": [{"title": p.title, "category": p.category,
                       "total_score": p.total_score, "version": 1, "improved": False}
                      for p in programs],
            "total": len(programs)
        })


@app.route("/api/games/generate", methods=["POST"])
def api_games_generate():
    """
    Genera un juego nuevo o mejora uno existente.
    FIX #3: No crea duplicados -- si existe un juego similar, lo mejora.
    FIX #4: Valida y auto-corrige el codigo antes de guardar.
    """
    data = request.get_json(silent=True) or {}
    max_attempts = min(int(data.get("max_attempts", 2)), 3)

    try:
        from game_manager import get_game_manager
        gm = get_game_manager()
        ai = get_cognia()

        seed_concepts = []
        try:
            concepts = ai.semantic.list_all()
            seed_concepts = [c["concept"] for c in concepts if c.get("confidence", 0) >= 0.5][:5]
        except Exception:
            pass

        result = gm.generate_or_improve(
            seed_concepts=seed_concepts,
            max_attempts=max_attempts,
            force_game_category=True,
        )
        return jsonify(result)

    except ImportError:
        try:
            from program_creator import run_program_hobby
            session_result = run_program_hobby(
                cognia_instance=get_cognia(),
                max_attempts=max_attempts,
                verbose=False,
            )
            return jsonify({
                "stored":         session_result.stored,
                "attempted":      session_result.attempted,
                "programs":       [{"title": p.title, "total_score": p.total_score}
                                   for p in session_result.programs],
                "is_improvement": False,
            })
        except Exception as e:
            return jsonify({"error": str(e), "stored": 0})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "stored": 0})


@app.route("/api/games/improve", methods=["POST"])
def api_games_improve():
    try:
        from game_manager import get_game_manager
        gm = get_game_manager()
        result = gm.improve_all_games()
        return jsonify(result)
    except ImportError:
        return jsonify({"improved": 0, "message": "GameManager no disponible"})
    except Exception as e:
        return jsonify({"error": str(e), "improved": 0})


# =============================================================================
#  INTEGRACIONES ADICIONALES
# =============================================================================

def _register_optional_routes():
    try:
        from auto_editor import register_routes
        register_routes(app)
        print("[web_app] auto_editor cargado")
    except ImportError:
        print("[web_app] auto_editor no disponible")

    try:
        register_routes_llm_safe(app, get_cognia)
        print("[web_app] respuestas_articuladas cargado")
    except Exception as e:
        print("[web_app] respuestas_articuladas: " + str(e))

    try:
        from aprendizaje_profundo import register_routes_aprendizaje
        register_routes_aprendizaje(app, get_cognia)
        print("[web_app] aprendizaje_profundo cargado")
    except ImportError:
        print("[web_app] aprendizaje_profundo no disponible")

    try:
        from curiosidad_pasiva import CuriosidadPasiva, register_routes_curiosidad
        _curiosidad = CuriosidadPasiva(get_cognia)
        _curiosidad.iniciar()
        register_routes_curiosidad(app, _curiosidad)
        print("[web_app] curiosidad_pasiva cargado")
    except ImportError:
        print("[web_app] curiosidad_pasiva no disponible")

    try:
        from self_architect import register_routes_architect
        register_routes_architect(app, get_cognia)
        print("[web_app] self_architect cargado")
    except ImportError:
        print("[web_app] self_architect no disponible")

    # Paso 3+4: endpoints de diagnóstico de aprendizaje
    _register_learning_routes(app, get_cognia)


def _register_learning_routes(app, ai_getter):
    """
    Paso 3+4: endpoints de diagnóstico de aprendizaje y arquitectura.
    Todos son read-only salvo /api/learn/batch.
    """
    from flask import request, jsonify

    @app.route("/api/learning_health")
    def api_learning_health():
        """Estado del sistema de aprendizaje: teacher, collapse guard, engine."""
        ai = ai_getter()
        report = {}

        teacher = getattr(ai, "teacher", None)
        if teacher:
            report["teacher"] = teacher.stats()
            report["recent_corrections"] = teacher.recent_corrections(limit=5)

        guard = getattr(ai, "collapse_guard", None)
        if guard:
            report["collapse"] = guard.get_collapse_report()

        try:
            from language_engine import get_language_engine
            engine = get_language_engine(ai)
            report["engine"] = engine.report_weak_zones()
            report["engine"]["stats"] = engine.stats()
        except Exception:
            pass

        architect = getattr(ai, "architect", None)
        if architect:
            last_eval = architect.log.get_last_evaluation()
            if last_eval:
                report["architect"] = {
                    "score":     last_eval.get("score"),
                    "timestamp": last_eval.get("timestamp"),
                    "diagnoses": last_eval.get("diagnoses", [])[:3],
                }

        return jsonify(report)

    @app.route("/api/learn/batch", methods=["POST"])
    def api_learn_batch():
        """Enseñanza en lote: lista de {text, label}."""
        data  = request.get_json(silent=True) or {}
        pairs_raw = data.get("pairs", [])
        if not pairs_raw or not isinstance(pairs_raw, list):
            return jsonify({"error": "pairs debe ser lista de {text, label}"}), 400
        ai      = ai_getter()
        teacher = getattr(ai, "teacher", None)
        if not teacher:
            return jsonify({"error": "TeacherInterface no disponible"}), 503
        pairs = [(p.get("text",""), p.get("label",""))
                 for p in pairs_raw if p.get("text") and p.get("label")]
        result = teacher.teach_batch(pairs, source="batch_api")
        return jsonify(result)

    @app.route("/api/architect/collapse")
    def api_architect_collapse():
        """Reporte de colapso de modelo del CollapseGuard."""
        ai    = ai_getter()
        guard = getattr(ai, "collapse_guard", None)
        if not guard:
            return jsonify({"error": "ModelCollapseGuard no disponible"}), 503
        return jsonify(guard.get_collapse_report())

    @app.route("/api/architect/engine_zones")
    def api_architect_engine_zones():
        """Zonas débiles del LanguageEngine para diagnóstico."""
        ai = ai_getter()
        try:
            from language_engine import get_language_engine
            engine = get_language_engine(ai)
            return jsonify({
                "weak_zones": engine.report_weak_zones(),
                "full_stats": engine.stats(),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 503

    print("[web_app] learning_health + batch + collapse + engine_zones activos")


def register_routes_llm_safe(app, ai_getter):
    from flask import request, jsonify

    @app.route("/api/ollama_status_v2")
    def api_ollama_status_v2():
        from respuestas_articuladas import verificar_ollama
        return jsonify(verificar_ollama())


# =============================================================================
#  BACKGROUND THREADS
# =============================================================================

def _auto_sleep_loop():
    time.sleep(3600)
    while True:
        try:
            get_cognia().sleep()
            print("[AutoSleep] Ciclo completado")
        except Exception as e:
            print("[AutoSleep] Error: " + str(e))
        time.sleep(4 * 3600)


def _limpiar_ruido_inicial():
    import sqlite3
    from datetime import timedelta
    try:
        ai = get_cognia()
        db_path = getattr(ai.episodic, "db", "cognia_memory.db")
        cutoff  = (datetime.now() - timedelta(days=7)).isoformat()
        conn = sqlite3.connect(db_path)
        conn.text_factory = str
        c = conn.cursor()
        c.execute("""
            UPDATE episodic_memory SET forgotten=1
            WHERE label IS NULL AND importance < 0.35
              AND timestamp < ? AND context_tags LIKE '%chat%' AND forgotten=0
        """, (cutoff,))
        eliminados = c.rowcount
        conn.commit(); conn.close()
        if eliminados > 0:
            print("[Startup] " + str(eliminados) + " episodios de chat antiguos limpiados")
    except Exception as e:
        print("[Startup] Limpieza: " + str(e))


# =============================================================================
#  MAIN
# =============================================================================

_register_optional_routes()
_limpiar_ruido_inicial()

threading.Thread(target=_auto_sleep_loop, name="AutoSleep", daemon=True).start()
print("[AutoSleep] Hilo de sueno automatico iniciado (cada 4h)")

if __name__ == "__main__":
    print("\nCognia v3+ web -- http://" + HOST + ":" + str(PORT))
    print("   Fix /api/chat con fallback robusto")
    print("   Modo autonomo en idle > 60s")
    print("   Sistema de juegos con mejora iterativa")
    print("   Auto-correccion de codigo generado")
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)
