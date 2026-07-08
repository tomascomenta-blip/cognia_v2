// Tooltip 2D reusable: la escena lo monta dentro de <Html> de drei al hacer
// hover sobre una sala/trabajador. Tambien exporta la paleta de estados que
// comparten todos los paneles 2D (pills, minimapa, links).
import type { EstadoTarea } from '../state/tipos'

/** Color solido por estado (canvas del minimapa, puntos de links). */
export const COLOR_ESTADO: Record<EstadoTarea, string> = {
  pendiente: '#9aa0a6',
  en_curso: '#c6d62f',
  pausada: '#f8bbd9',
  detenida: '#b3125f',
  fallida: '#e91e8c',
  hecha: '#5e2249',
}

/** Clases tailwind de la pill por estado (fondo suave + texto legible). */
export const PILL_ESTADO: Record<EstadoTarea, string> = {
  pendiente: 'bg-neutral-400/25 text-neutral-600 dark:text-neutral-300',
  en_curso: 'bg-lima/30 text-mueble dark:text-lima',
  pausada: 'bg-rosa/50 text-piso dark:bg-rosa/20 dark:text-rosa',
  detenida: 'bg-magenta/15 text-magenta',
  fallida: 'bg-magenta/25 text-magenta',
  hecha: 'bg-piso/15 text-piso dark:bg-piso/50 dark:text-rosa',
}

export function PillEstado({ estado }: { estado: EstadoTarea }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${PILL_ESTADO[estado]}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: COLOR_ESTADO[estado] }}
      />
      {estado.replace('_', ' ')}
    </span>
  )
}

export interface TooltipProps {
  nombre: string
  estado?: EstadoTarea | null
  /** detalle/prompt de la tarea; se trunca a 1 linea */
  tarea?: string | null
}

/** Tooltip de hover en 1 linea: nombre · estado · tarea. */
export function Tooltip({ nombre, estado, tarea }: TooltipProps) {
  return (
    <div className="pointer-events-none flex max-w-xs items-center gap-2 whitespace-nowrap rounded-md border border-rosa/70 bg-white/95 px-2.5 py-1 text-xs text-mueble shadow-lg backdrop-blur dark:border-piso dark:bg-neutral-900/95 dark:text-neutral-200">
      <span className="font-semibold">{nombre}</span>
      {estado && <PillEstado estado={estado} />}
      {tarea && (
        <span className="max-w-40 truncate text-mueble/60 dark:text-neutral-400">
          {tarea}
        </span>
      )}
    </div>
  )
}

export default Tooltip
