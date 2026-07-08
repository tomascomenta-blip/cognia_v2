// Tipos EXACTOS del contrato con el backend (cognia/oficina/estado.py + server.py).
// El frontend SOLO visualiza y controla via HTTP; nunca ejecuta logica del sistema.

export type Nivel = 'jefe' | 'director' | 'trabajador'
export type Rol = 'investigador' | 'implementador'
export type EstadoTarea =
  | 'pendiente'
  | 'en_curso'
  | 'pausada'
  | 'detenida'
  | 'hecha'
  | 'fallida'

export interface Evento {
  t: string // "HH:MM:SS"
  msg: string
}

export interface Meta {
  id: string
  texto: string
  estado: string
  creada: string
  resultado?: string
}

export interface Tarea {
  id: string
  nivel: Nivel
  titulo: string
  detalle: string
  padre: string | null
  rol: Rol | null
  meta: string | null
  estado: EstadoTarea
  solicitud: string | null
  resultado: string | null
  creada: string // "HH:MM:SS"
  /** epoch s (time.time() en estado.py). Opcionales: tareas persistidas
   *  antes de que existieran los campos pueden no traerlos. */
  creada_ts?: number
  inicio_ts?: number // se setea al pasar a en_curso
  fin_ts?: number // se setea al pasar a hecha/fallida/detenida
  eventos: Evento[]
}

/** GET /api/estado y evento SSE "estado". */
export interface Snapshot {
  metas: Meta[]
  tareas: Record<string, Tarea>
  orden: string[]
}

/** GET /api/sistema y evento SSE "sistema". Campos null si psutil no esta. */
export interface Sistema {
  cpu_pct: number | null
  ram_mb: number | null
  ram_pct: number | null
  n_threads: number | null
  agentes_activos: number
  tareas_pendientes: number
  tareas_en_curso: number
  uptime_s: number
}

export const SNAPSHOT_VACIO: Snapshot = { metas: [], tareas: {}, orden: [] }
