// Minimapa 2D (canvas nativo) arriba-izquierda: layout REAL de las salas de
// derivar.ts, color por estado de la tarea, glow lima en modulos con
// actividad reciente, click = seleccionar + centrar, indicador de viewport
// opcional (la escena pasa el centro de camara en coords de grid).
import { useEffect, useMemo, useRef, useState } from 'react'
import { useOficina } from '../state/store'
import { derivarActividad, derivarSalas, msDesde } from '../lib/derivar'
import type { Sala } from '../lib/derivar'
import type { Snapshot } from '../state/tipos'
import { COLOR_ESTADO } from './Tooltip'

export interface MinimapaProps {
  /** Centro visible de la camara en coords de grid (x,z); `medio` = semiancho
   *  del recuadro en celdas (default 7). null/omitido = sin indicador. */
  viewport?: { x: number; z: number; medio?: number } | null
  /** La escena centra la camara en la sala clickeada. */
  onEnfocar?: (id: string) => void
}

const W = 224
const H = 152
const PAD = 8
const GLOW_MS = 4000 // mismo umbral que usa la escena para iluminar modulos

function transformar(salas: Sala[]): { esc: number; ox: number; oz: number } {
  let maxX = 1
  let maxZ = 1
  for (const s of salas) {
    maxX = Math.max(maxX, s.posicion[0] + s.tamano[0])
    maxZ = Math.max(maxZ, s.posicion[1] + s.tamano[1])
  }
  return { esc: Math.min((W - PAD * 2) / maxX, (H - PAD * 2) / maxZ), ox: PAD, oz: PAD }
}

function colorSala(s: Sala, snap: Snapshot, glow: ReadonlySet<string>): string {
  if (s.tid) {
    const t = snap.tareas[s.tid]
    if (t) return COLOR_ESTADO[t.estado]
  }
  if (glow.has(s.id)) return COLOR_ESTADO.en_curso // modulo iluminado
  return '#c9c2ba' // modulo en reposo
}

export function Minimapa({ viewport, onEnfocar }: MinimapaProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const snapshot = useOficina((s) => s.snapshot)
  const seleccion = useOficina((s) => s.seleccion)
  const setSeleccion = useOficina((s) => s.setSeleccion)
  const salas = useMemo(() => derivarSalas(snapshot), [snapshot])

  // tick 1s: apaga el glow de actividad sin esperar otro snapshot
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    void tick // el redibujo depende del tiempo (glow), no solo de los datos
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)

    const glow = new Set(
      derivarActividad(snapshot)
        .filter((a) => msDesde(a.t) < GLOW_MS)
        .map((a) => a.sala),
    )
    const { esc, ox, oz } = transformar(salas)

    for (const s of salas) {
      const x = ox + s.posicion[0] * esc
      const z = oz + s.posicion[1] * esc
      const w = s.tamano[0] * esc
      const h = s.tamano[1] * esc
      ctx.fillStyle = colorSala(s, snapshot, glow)
      ctx.fillRect(x, z, w, h)
      if (s.id === seleccion) {
        ctx.strokeStyle = '#e91e8c'
        ctx.lineWidth = 2
        ctx.strokeRect(x + 1, z + 1, Math.max(w - 2, 1), Math.max(h - 2, 1))
      }
    }

    if (viewport) {
      const medio = viewport.medio ?? 7
      ctx.strokeStyle = '#e91e8c'
      ctx.lineWidth = 1
      ctx.setLineDash([3, 2])
      ctx.strokeRect(
        ox + (viewport.x - medio) * esc,
        oz + (viewport.z - medio) * esc,
        medio * 2 * esc,
        medio * 2 * esc,
      )
      ctx.setLineDash([])
    }
  }, [snapshot, salas, seleccion, viewport, tick])

  return (
    <div className="absolute left-3 top-3 z-20 overflow-hidden rounded-lg border border-rosa/70 bg-white/85 shadow-md backdrop-blur dark:border-piso dark:bg-neutral-900/85">
      <canvas
        ref={canvasRef}
        style={{ width: W, height: H }}
        className="block cursor-pointer"
        title="minimapa · click = seleccionar sala"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          const { esc, ox, oz } = transformar(salas)
          const gx = (e.clientX - rect.left - ox) / esc
          const gz = (e.clientY - rect.top - oz) / esc
          // de atras hacia adelante: las dinamicas (dibujadas ultimas) ganan
          for (let i = salas.length - 1; i >= 0; i--) {
            const s = salas[i]
            if (
              gx >= s.posicion[0] &&
              gx <= s.posicion[0] + s.tamano[0] &&
              gz >= s.posicion[1] &&
              gz <= s.posicion[1] + s.tamano[1]
            ) {
              setSeleccion(s.id)
              onEnfocar?.(s.id)
              return
            }
          }
        }}
      />
    </div>
  )
}

export default Minimapa
