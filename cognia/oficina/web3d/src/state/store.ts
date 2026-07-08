// Store zustand + cliente SSE con fallback a poll. Solo fetch: cero logica del sistema.
import { create } from 'zustand'
import type { Rol, Sistema, Snapshot } from './tipos'
import { SNAPSHOT_VACIO } from './tipos'

export type Vista = '3d' | 'clasica-abierta'

interface OficinaStore {
  snapshot: Snapshot
  sistema: Sistema | null
  conectado: boolean
  seleccion: string | null // id de sala/tarea seleccionada en la escena
  /** pedido de "centrar la camara en <id>"; `n` crece para re-disparar el
   *  mismo id dos veces (la escena lo consume en un useEffect) */
  enfoque: { id: string; n: number } | null
  vista: Vista
  modoNoche: boolean
  filtro: string

  setSeleccion: (id: string | null) => void
  enfocar: (id: string) => void
  toggleVista: () => void
  toggleNoche: () => void
  setFiltro: (f: string) => void

  // control remoto: cada accion es UN fetch al backend, nada mas
  accion: (id: string, accion: 'detener' | 'pausar' | 'reanudar') => Promise<boolean>
  editar: (id: string, detalle: string) => Promise<boolean>
  prioridad: (id: string, delta: -1 | 1) => Promise<boolean>
  reasignar: (id: string, rol: Rol) => Promise<boolean>
  reiniciar: (id: string) => Promise<string | null>
  mensaje: (de: string, para: string, texto: string) => Promise<boolean>
  nuevaMeta: (texto: string) => Promise<boolean>
}

async function post(url: string, body: unknown): Promise<Record<string, unknown> | null> {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return (await r.json()) as Record<string, unknown>
  } catch {
    return null // backend caido: el indicador conectado/desconectado ya lo muestra
  }
}

export const useOficina = create<OficinaStore>()((set) => ({
  snapshot: SNAPSHOT_VACIO,
  sistema: null,
  conectado: false,
  seleccion: null,
  enfoque: null,
  vista: '3d',
  modoNoche: false,
  filtro: '',

  setSeleccion: (id) => set({ seleccion: id }),
  enfocar: (id) => set((s) => ({ enfoque: { id, n: (s.enfoque?.n ?? 0) + 1 } })),
  toggleVista: () =>
    set((s) => ({ vista: s.vista === '3d' ? 'clasica-abierta' : '3d' })),
  toggleNoche: () => set((s) => ({ modoNoche: !s.modoNoche })),
  setFiltro: (f) => set({ filtro: f }),

  accion: async (id, accion) =>
    (await post('/api/tarea/accion', { id, accion }))?.ok === true,
  editar: async (id, detalle) =>
    (await post('/api/tarea/editar', { id, detalle }))?.ok === true,
  prioridad: async (id, delta) =>
    (await post('/api/tarea/prioridad', { id, delta }))?.ok === true,
  reasignar: async (id, rol) =>
    (await post('/api/tarea/reasignar', { id, rol }))?.ok === true,
  reiniciar: async (id) => {
    const r = await post('/api/agente/reiniciar', { id })
    return r?.ok === true ? String(r.nuevo_id) : null
  },
  mensaje: async (de, para, texto) =>
    (await post('/api/mensaje', { de, para, texto }))?.ok === true,
  nuevaMeta: async (texto) => (await post('/api/meta', { texto }))?.ok === true,
}))

// ── cliente SSE con reconexion + fallback a poll cada 2s ──────────────────
// EventSource reintenta solo mientras este CONNECTING; si queda CLOSED lo
// recreamos a mano. Mientras no haya SSE vivo, el poll mantiene los datos.

const POLL_MS = 2000
const RETRY_SSE_MS = 5000

let es: EventSource | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let arrancado = false

function pararPoll() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function arrancarPoll() {
  if (pollTimer !== null) return
  const tick = async () => {
    try {
      const [re, rs] = await Promise.all([fetch('/api/estado'), fetch('/api/sistema')])
      const snapshot = (await re.json()) as Snapshot
      const sistema = rs.ok ? ((await rs.json()) as Sistema) : null
      useOficina.setState({ snapshot, ...(sistema ? { sistema } : {}), conectado: true })
    } catch {
      useOficina.setState({ conectado: false })
    }
  }
  void tick()
  pollTimer = setInterval(tick, POLL_MS)
}

function conectarSSE() {
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  es?.close()
  es = new EventSource('/api/sse')

  es.onopen = () => {
    useOficina.setState({ conectado: true })
    pararPoll()
  }
  es.addEventListener('estado', (e) => {
    useOficina.setState({ snapshot: JSON.parse(e.data) as Snapshot, conectado: true })
  })
  es.addEventListener('sistema', (e) => {
    useOficina.setState({ sistema: JSON.parse(e.data) as Sistema, conectado: true })
  })
  es.onerror = () => {
    useOficina.setState({ conectado: false })
    arrancarPoll() // fallback mientras el SSE no vuelve
    if (es?.readyState === EventSource.CLOSED && retryTimer === null) {
      retryTimer = setTimeout(conectarSSE, RETRY_SSE_MS)
    }
  }
}

/** Arranca SSE + fallback. Idempotente: llamar una vez desde main/App. */
export function conectar() {
  if (arrancado) return
  arrancado = true
  conectarSSE()
}
