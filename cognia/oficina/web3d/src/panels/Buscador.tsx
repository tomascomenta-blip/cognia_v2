// Buscador: overlay de resultados bajo el header. La query es store.filtro
// (el input vive en el header de App). Filtra salas fijas y tareas por
// id/titulo/rol/estado, resalta el match y al click selecciona + centra
// (onEnfocar: la escena decide como mover la camara).
import { useEffect, useMemo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useOficina } from '../state/store'
import { derivarSalas } from '../lib/derivar'
import type { EstadoTarea, Nivel, Rol } from '../state/tipos'
import { PillEstado } from './Tooltip'

export interface BuscadorProps {
  /** La escena centra la camara en la sala `id` (contrato de integracion). */
  onEnfocar?: (id: string) => void
}

interface Resultado {
  id: string
  nombre: string
  tipo: 'sala' | Nivel
  estado: EstadoTarea | null
  rol: Rol | null
}

const MAX_RESULTADOS = 20

function Resaltar({ texto, q }: { texto: string; q: string }) {
  const i = texto.toLowerCase().indexOf(q)
  if (i < 0) return <>{texto}</>
  return (
    <>
      {texto.slice(0, i)}
      <mark className="rounded-sm bg-lima/60 px-0.5 text-inherit dark:bg-lima/40">
        {texto.slice(i, i + q.length)}
      </mark>
      {texto.slice(i + q.length)}
    </>
  )
}

export function Buscador({ onEnfocar }: BuscadorProps) {
  const snapshot = useOficina((s) => s.snapshot)
  const filtro = useOficina((s) => s.filtro)
  const setFiltro = useOficina((s) => s.setFiltro)
  const setSeleccion = useOficina((s) => s.setSeleccion)

  const q = filtro.trim().toLowerCase()

  const resultados = useMemo(() => {
    if (!q) return []
    const candidatos: Resultado[] = []
    // salas fijas (modulos + jefe + mega_jefe)
    for (const s of derivarSalas(snapshot)) {
      if (s.tipo !== 'fija') continue
      candidatos.push({ id: s.id, nombre: s.nombre, tipo: 'sala', estado: null, rol: null })
    }
    // tareas reales (jefe/directores/trabajadores)
    for (const tid of snapshot.orden) {
      const t = snapshot.tareas[tid]
      if (!t) continue
      candidatos.push({ id: t.id, nombre: t.titulo, tipo: t.nivel, estado: t.estado, rol: t.rol })
    }
    return candidatos
      .filter(
        (c) =>
          c.id.toLowerCase().includes(q) ||
          c.nombre.toLowerCase().includes(q) ||
          (c.rol ?? '').includes(q) ||
          (c.estado ?? '').includes(q),
      )
      .slice(0, MAX_RESULTADOS)
  }, [snapshot, q])

  const elegir = (id: string) => {
    setSeleccion(id)
    onEnfocar?.(id) // la escena centra la camara
    setFiltro('') // cerrar el overlay
  }

  // Escape cierra; Enter (fuera de textarea/select) elige el primer resultado
  useEffect(() => {
    if (!q) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setFiltro('')
      } else if (e.key === 'Enter' && resultados.length > 0) {
        const tag = (e.target as HTMLElement | null)?.tagName ?? ''
        if (tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return
        elegir(resultados[0].id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, resultados])

  return (
    <AnimatePresence>
      {q !== '' && (
        <motion.div
          key="buscador"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.15 }}
          className="absolute left-1/2 top-3 z-40 w-md max-w-[92vw] -translate-x-1/2 overflow-hidden rounded-lg border border-rosa/70 bg-white/95 text-mueble shadow-2xl backdrop-blur dark:border-piso dark:bg-neutral-900/95 dark:text-neutral-200"
        >
          <div className="flex items-center justify-between border-b border-rosa/40 px-3 py-1.5 text-[11px] text-mueble/50 dark:border-piso/60 dark:text-neutral-500">
            <span>
              {resultados.length} resultado{resultados.length === 1 ? '' : 's'} para “{filtro.trim()}”
            </span>
            <span>Enter = primero · Esc = cerrar</span>
          </div>
          {resultados.length === 0 ? (
            <p className="px-3 py-3 text-xs text-mueble/40 dark:text-neutral-600">
              nada matchea por id, título, rol ni estado
            </p>
          ) : (
            <ul className="max-h-72 overflow-y-auto">
              {resultados.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => elegir(r.id)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-rosa/30 dark:hover:bg-piso/40"
                  >
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        r.tipo === 'sala'
                          ? 'bg-piso/10 text-piso dark:bg-piso/40 dark:text-rosa'
                          : 'bg-magenta/10 text-magenta'
                      }`}
                    >
                      {r.tipo}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium">
                      <Resaltar texto={r.nombre} q={q} />
                    </span>
                    {r.rol && (
                      <span className="shrink-0 text-mueble/50 dark:text-neutral-500">
                        <Resaltar texto={r.rol} q={q} />
                      </span>
                    )}
                    {r.estado && <PillEstado estado={r.estado} />}
                    <span className="shrink-0 font-mono text-[10px] text-mueble/40 dark:text-neutral-500">
                      <Resaltar texto={r.id} q={q} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default Buscador
