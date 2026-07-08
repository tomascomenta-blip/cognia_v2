// Timeline: franja inferior colapsable con los ultimos ~50 eventos globales
// (merge de los eventos de TODAS las tareas, ordenados por hora) con filtro,
// mas el historial de metas. Click en el origen selecciona la tarea.
import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useOficina } from '../state/store'
import { PILL_ESTADO } from './Tooltip'

export interface TimelineProps {
  /** La escena centra la camara al clickear el origen de un evento. */
  onEnfocar?: (id: string) => void
}

const MAX_EVENTOS = 50

interface EventoGlobal {
  t: string
  msg: string
  tid: string
  titulo: string
  key: string
}

// Meta.estado es string libre en el contrato: pill conocida o neutra
function pillMeta(estado: string): string {
  return (
    (PILL_ESTADO as Record<string, string>)[estado] ??
    'bg-neutral-400/25 text-neutral-600 dark:text-neutral-300'
  )
}

export function Timeline({ onEnfocar }: TimelineProps) {
  const snapshot = useOficina((s) => s.snapshot)
  const setSeleccion = useOficina((s) => s.setSeleccion)
  const [abierta, setAbierta] = useState(false)
  const [tab, setTab] = useState<'eventos' | 'metas'>('eventos')
  const [q, setQ] = useState('')

  const eventos = useMemo(() => {
    const todos: EventoGlobal[] = []
    for (const tid of snapshot.orden) {
      const t = snapshot.tareas[tid]
      if (!t) continue
      t.eventos.forEach((ev, i) =>
        todos.push({ t: ev.t, msg: ev.msg, tid, titulo: t.titulo, key: `${tid}:${i}` }),
      )
    }
    // "HH:MM:SS" ordena lexicograficamente; sort estable conserva empates
    todos.sort((a, b) => a.t.localeCompare(b.t))
    return todos.slice(-MAX_EVENTOS).reverse() // mas nuevo primero
  }, [snapshot])

  const filtrados = useMemo(() => {
    const f = q.trim().toLowerCase()
    if (!f) return eventos
    return eventos.filter(
      (e) =>
        e.msg.toLowerCase().includes(f) ||
        e.titulo.toLowerCase().includes(f) ||
        e.tid.toLowerCase().includes(f),
    )
  }, [eventos, q])

  const irA = (tid: string) => {
    setSeleccion(tid)
    onEnfocar?.(tid)
  }

  return (
    <div className="absolute inset-x-0 bottom-0 z-20 border-t border-rosa/70 bg-white/90 text-mueble backdrop-blur dark:border-piso dark:bg-neutral-900/90 dark:text-neutral-200">
      {/* barra siempre visible */}
      <div className="flex items-center gap-2 px-3 py-1.5">
        <button
          type="button"
          onClick={() => setAbierta((a) => !a)}
          className="flex shrink-0 items-center gap-1.5 text-xs font-semibold text-piso dark:text-rosa"
        >
          <span
            className={`inline-block text-[10px] transition-transform ${abierta ? 'rotate-180' : ''}`}
          >
            ▲
          </span>
          Timeline
          <span className="font-normal text-mueble/50 dark:text-neutral-500">
            · {eventos.length} eventos · {snapshot.metas.length} metas
          </span>
        </button>

        {abierta ? (
          <>
            <div className="ml-2 flex shrink-0 overflow-hidden rounded-md border border-rosa/70 text-xs dark:border-piso">
              <button
                type="button"
                onClick={() => setTab('eventos')}
                className={
                  tab === 'eventos'
                    ? 'bg-magenta px-2 py-0.5 font-medium text-white'
                    : 'px-2 py-0.5 hover:bg-rosa/30 dark:hover:bg-piso/40'
                }
              >
                eventos
              </button>
              <button
                type="button"
                onClick={() => setTab('metas')}
                className={
                  tab === 'metas'
                    ? 'bg-magenta px-2 py-0.5 font-medium text-white'
                    : 'px-2 py-0.5 hover:bg-rosa/30 dark:hover:bg-piso/40'
                }
              >
                metas
              </button>
            </div>
            {tab === 'eventos' && (
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="filtrar eventos…"
                className="w-56 max-w-[40vw] rounded-md border border-rosa/70 bg-white px-2 py-0.5 text-xs outline-none placeholder:text-mueble/40 focus:border-magenta dark:border-piso dark:bg-neutral-800 dark:placeholder:text-neutral-500"
              />
            )}
          </>
        ) : (
          eventos[0] && (
            <span className="min-w-0 flex-1 truncate text-[11px] text-mueble/60 dark:text-neutral-400">
              <span className="font-mono text-magenta/70">{eventos[0].t}</span>{' '}
              [{eventos[0].titulo}] {eventos[0].msg}
            </span>
          )
        )}
      </div>

      <AnimatePresence initial={false}>
        {abierta && (
          <motion.div
            key="cuerpo"
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div className="max-h-44 overflow-y-auto px-3 pb-2">
              {tab === 'eventos' ? (
                filtrados.length === 0 ? (
                  <p className="py-2 text-xs text-mueble/40 dark:text-neutral-600">
                    sin eventos{q.trim() ? ' que matcheen el filtro' : ' todavía'}
                  </p>
                ) : (
                  <ul className="flex flex-col gap-0.5">
                    {filtrados.map((e) => (
                      <li key={e.key} className="flex items-baseline gap-2 text-[11px]">
                        <span className="shrink-0 font-mono text-magenta/70">{e.t}</span>
                        <button
                          type="button"
                          onClick={() => irA(e.tid)}
                          title={`${e.titulo} (${e.tid})`}
                          className="max-w-40 shrink-0 truncate font-medium text-piso underline-offset-2 hover:underline dark:text-rosa"
                        >
                          {e.titulo}
                        </button>
                        <span
                          className="min-w-0 truncate text-mueble/80 dark:text-neutral-300"
                          title={e.msg}
                        >
                          {e.msg}
                        </span>
                      </li>
                    ))}
                  </ul>
                )
              ) : snapshot.metas.length === 0 ? (
                <p className="py-2 text-xs text-mueble/40 dark:text-neutral-600">
                  sin metas todavía
                </p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {[...snapshot.metas].reverse().map((m) => (
                    <li key={m.id} className="flex items-baseline gap-2 text-[11px]">
                      <span className="shrink-0 font-mono text-magenta/70">{m.creada}</span>
                      <span
                        className={`shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium ${pillMeta(m.estado)}`}
                      >
                        {m.estado}
                      </span>
                      <span className="min-w-0 flex-1 truncate" title={m.texto}>
                        {m.texto}
                      </span>
                      {m.resultado && (
                        <span
                          className="min-w-0 truncate text-mueble/50 dark:text-neutral-500"
                          title={m.resultado}
                        >
                          → {m.resultado}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default Timeline
