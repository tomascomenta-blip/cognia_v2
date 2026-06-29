# M0 — Ejecución de los gates G1 y G2 (cerrar el GO-CONDICIONADO → GO-LIMPIO sobre la arquitectura)

> **Para qué.** El veredicto de readiness (`00_READINESS.md`) es GO **CONDICIONADO** por una sola
> incógnita load-bearing: **¿el backbone v1 es la RAMA A (híbrido lineal+SWA) o la RAMA B (Transformer
> GQA denso)?** G1 y G2 la cierran con número. Este doc te da los comandos exactos: **G1 corre local en
> tu i3** (es una pregunta de CPU), **G2 corre en Google Colab GPU gratis** (es entrenamiento).
>
> Cuando corras cada uno, **pegame el output** (G1 imprime una tabla + veredicto; G2 imprime un JSON al
> final) y yo actualizo `00_READINESS.md` hacia GO-LIMPIO con la rama elegida.

Scripts (en este repo): `cognia_x/construccion/m0_g1_bandwidth.py` y `m0_g2_recall_colab.py`.
Ambos verificados que corren (smoke local) antes de entregártelos.

---

## GATE G1 — ¿la atención SLIDING-WINDOW (SWA) ahorra banda en CPU? (LOCAL, tu i3)

**Qué decide:** si la SWA conserva la velocidad de decode al crecer el contexto L (y acota la RAM de
KV) **en los kernels CPU reales de llama.cpp**, la RAMA A (híbrido) es viable. Si no, RAMA B (GQA denso).
Precedente de que el ahorro teórico NO se materializa solo: exp007 (int8 naïve fue 8-10× más lento sin
kernel). Por eso se MIDE.

**Por qué local y no Colab:** A-018 pregunta por los kernels de **tu CPU**. Medir en GPU respondería otra
cosa. Esto NO necesita GPU.

### Paso 1 — Descargar UN modelo SWA-nativo (~1.6 GB)

Los 6 GGUF que ya tenés son todos Qwen2.5 = **atención FULL**. Falta un modelo con SWA. El mejor chico es
**Gemma-2-2B** (SWA ventana 4096, contexto 8192, rápido en el i3). Opciones (elegí UNA):

**Opción A — descarga directa sin login (quant comunitario):**
```bash
# en la raíz del repo (D:\Movido_desde_C\Downloads\cognia\cognia_v2), en una terminal con curl:
mkdir -p model_shards/gemma2-2b
curl -L -o model_shards/gemma2-2b/gemma-2-2b-it-Q4_K_M.gguf \
  https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf
```
Si esa URL pide auth o da 404, probá `lmstudio-community/gemma-2-2b-it-GGUF` (mismo nombre de archivo) o
la **Opción B**.

**Opción B — alternativa sin gating (Mistral-7B v0.1, SWA ventana 4096):** más pesado (~4 GB, ~4 tok/s en
el i3) pero cero login:
```bash
mkdir -p model_shards/mistral7b-swa
curl -L -o model_shards/mistral7b-swa/mistral-7b-instruct-v0.1-Q4_K_M.gguf \
  https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF/resolve/main/mistral-7b-instruct-v0.1.Q4_K_M.gguf
```

### Paso 2 — Medir (full ya presente + el SWA que bajaste)

```powershell
# 1) modelo FULL (Qwen-3B, ya en el repo):
.\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py `
  --gguf model_shards\qwen-coder-3b-q4\Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf --label qwen3b_full

# 2) modelo SWA (el que bajaste; la etiqueta DEBE contener 'gemma' o 'swa' o 'mistral'):
.\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py `
  --gguf model_shards\gemma2-2b\gemma-2-2b-it-Q4_K_M.gguf --label gemma2_swa
```
Cada uno barre L ∈ {512, 2048, 4096, 8192} arrancando el server, midiendo decode tok/s + RAM. En el i3
tarda ~10-25 min por modelo (el prefill de 8192 es lo lento). Es CPU puro, `n_gpu_layers=0`.

### Paso 3 — Veredicto

```powershell
.\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py --compare
```
Imprime la tabla (decode tok/s + RAM por L) y el veredicto:
- **RAMA A VIABLE** si el SWA conserva ≥70% de su decode de 2048→8192 **Y** lo conserva mejor que el full
  (la ventana aplana la caída en CPU). → el híbrido vale la pena.
- **RAMA B** si el SWA cae igual que el full (la ventana NO ayuda en los kernels CPU) → backbone = GQA
  denso, maduro HOY.

**Pegame la salida de `--compare`** y fijo la rama en `00_READINESS.md` / `02_backbone_modelo.md`.

---

## GATE G2 — ¿el híbrido recupera recall a escala, con cuánta atención? (GOOGLE COLAB, GPU T4 gratis)

**Qué decide:** a la escala objetivo (no el toy d=24), la **mínima cuota de atención** que cruza el recall
asociativo, **el arreglo** (lineal-primero vs atención-primero) y **la ventana** (SWA local vs global).
Si el híbrido cruza con minoría de atención (≤1/3) → RAMA A respira. Si necesita atención-mayoritaria →
acerca a RAMA B. Si el recall exige atención GLOBAL → las pocas capas de atención del híbrido deben ser
globales (no SWA).

**Por qué Colab GPU:** es entrenamiento (12 configs × ~6000 pasos a d=256/12 capas). En tu i3 serían
horas; en una T4 gratis son ~30-60 min.

### Paso 1 — Abrir Colab con GPU
1. Andá a https://colab.research.google.com → **New notebook**.
2. **Runtime → Change runtime type → Hardware accelerator → T4 GPU → Save.** (gratis)

### Paso 2 — Subir el script y correrlo

El archivo `m0_g2_recall_colab.py` es **self-contained** (no clona el repo, no instala nada; torch ya está
en Colab). Pegá esto en una celda y ejecutá (Shift+Enter):

```python
# Celda 1 — subí el archivo m0_g2_recall_colab.py (está en cognia_x/construccion/ de tu repo)
from google.colab import files
print("Elegí cognia_x/construccion/m0_g2_recall_colab.py de tu compu:")
files.upload()
```
```python
# Celda 2 — confirmá que hay GPU y corré el sweep (~30-60 min)
import torch; print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO GPU - revisá Runtime!")
!python m0_g2_recall_colab.py
```

**Alternativa sin subir archivo** (si tu repo en GitHub es público): reemplazá la Celda 1 por
```python
!wget -q https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/cognia-x/cognia_x/construccion/m0_g2_recall_colab.py
```
Si da 404 (repo privado), usá la subida manual de arriba.

### Paso 3 — Devolveme el resultado
Al terminar, el script imprime una tabla **recall por config** + un **VEREDICTO G2** + una línea
`>>> COPIÁ Y DEVOLVÉ ESTE JSON ...`. **Pegame ese JSON** (o la tabla entera). Con eso fijo el ratio/arreglo/
ventana del backbone en `02_backbone_modelo.md` y actualizo `00_READINESS.md`.

> Nota: el free tier de Colab puede desconectar tras inactividad/uso. El script **guarda
> `g2_recall_results.json` incrementalmente** (cada config), así que si se corta, descargá ese archivo
> (panel de archivos de Colab) y pegámelo igual — tendré los configs que alcanzaron a correr.
> Si querés acortar: `!python m0_g2_recall_colab.py --steps 4000`.

---

## Qué pasa después (cómo cierra el GO-LIMPIO)

| Resultado | Decisión de arquitectura |
|---|---|
| G1: SWA aplana decode en CPU **+** G2: híbrido cruza recall con ≤1/3 de atención | **RAMA A (híbrido)** confirmada → backbone v1 = mayoría lineal/SSM + minoría SWA. **GO-LIMPIO.** |
| G1: SWA NO aplana en CPU **o** G2: recall exige atención-mayoritaria | **RAMA B (GQA denso)** → backbone v1 = Transformer denso GQA + KV-4bit (maduro HOY). **GO-LIMPIO** igual: el resto del sistema (verificador, lazo, RAG, expertos) es agnóstico al backbone. |
| G2: recall exige atención GLOBAL (la SWA local no basta) | Las pocas capas de atención del híbrido deben ser **globales** (no SWA) → ajusta `02_backbone_modelo.md` §3.3. |

En cualquier caso, **ningún resultado bloquea el build** — sólo fija qué caja 02 se construye. Con G1+G2
cerrados, el GO deja de ser condicionado: pasa a **LIMPIO sobre la arquitectura** (la única incógnita que
queda es SCALE, inherente a rediseñar desde cero, que se mitiga construyendo, no esperando).
