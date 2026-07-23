# cognia/vision — Cognia ve la pantalla y actúa en tiempo real

Servicio lateral (NO tocamos el loop del agente) que le da a Cognia percepción de
pantalla en tiempo real y un lazo de acción **seguro por defecto**. Compone piezas
del repo que estaban desconectadas (`cognia/pantalla`, `cognia/control`) y les añade
la seguridad que faltaba.

## Qué hay hoy (verificado)
- **`percepcion.py` — los ojos (read-only, modo sombra).** `ServicioPercepcion`:
  captura (mss) + detección de cambios (dHash) + árbol UIA (controles y ventana) →
  `Percepcion`. `instantanea()` y `percibir()` (stream real-time, event-driven por
  cambio). `describir()` la rinde como texto que el cerebro de TEXTO consume ya, sin
  VLM (el árbol UIA da percepción determinista sin VRAM).
  Seguridad: sobre ventana **sensible** (gestor de contraseñas, banca, incógnito, UAC)
  NO captura ni lee el árbol — percepción redactada.
- **`agente_pantalla.py` — las manos (gateadas).** `AgentePantalla` cierra el lazo
  percibir → *política* decide → **gate de permisos** → actuar. **DRY-RUN por defecto**
  (`ejecutar=False`): decide y registra, no ejecuta. Acciones que modifican exigen
  confirmación; ventana sensible = prohibido. Verificado en dry-run sobre la máquina.

## Ideas / arquitecturas (propuesta) y estado
1. **Captura rápida + bucle percepción-acción** (mss, event-driven por cambio). ✅ hecho.
2. **Grounding semántico por UI Automation** (leer el árbol de controles, clic por
   nombre, no por píxel) — robusto y sin VRAM. ✅ hecho (read) / ✅ acción gateada.
3. **Grounding visual con VLM** (screenshot → modelo multimodal) como *fallback* para
   lo que UIA no ve (juegos, canvas). ⏳ pendiente: el binario `node/mtmd.dll` ya está;
   falta el binding a `LlamaBackend.generate` (imagen) o un experto de visión aparte
   (estilo `minicpm_expert.py`) que lea el PNG que ya produce el capturador.
4. **Detección de cambios (event-driven)** para no malgastar cómputo. ✅ hecho (dHash).

## Modelo de seguridad ("sin romper nada")
- Percepción **read-only**: no mueve mouse/teclado, no requiere `COGNIA_SCREEN`.
- Ventanas sensibles: ni se capturan ni se accionan (patrones en `control/permisos.py`).
- Acción **dry-run por defecto**; ejecutar es explícito y pasa por `GestorPermisos`
  (LIBRE / CONFIRMAR / PROHIBIDO) evaluando (acción, ventana).
- Servicio lateral: no se registra como tool default-ON (respeta el techo de nº de
  tools del modelo chico).

## Próximos pasos
- Binding VLM (mtmd) para "ver" de verdad la imagen cuando el árbol UIA no basta.
- Política guiada por el cerebro (hoy la política es inyectable/determinista).
- Pausa por ventana sensible dentro de `cognia/pantalla/vigia.py` (hoy se cubre en
  `percepcion.py`; conviene bajarla también a la fuente).
