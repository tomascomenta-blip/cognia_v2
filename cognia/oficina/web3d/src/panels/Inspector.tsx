// Inspector: panel lateral derecho (slide-in) con TODO lo real de la
// seleccion del store (tarea o sala fija) + controles remotos. Solo lee el
// store y pega a sus acciones HTTP; cero logica del sistema.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useOficina } from '../state/store'
import { contarColas, derivarActividad, derivarSalas, msDesde } from '../lib/derivar'
import type { Sala } from '../lib/derivar'
import type { Rol, Snapshot, Tarea } from '../state/tipos'
import { COLOR_ESTADO, PillEstado } from './Tooltip'

export interface InspectorProps {
  /** La escena centra la camara en la sala `id` al navegar por links. */
  onEnfocar?: (id: string) => void
}

// ── helpers ────────────────────────────────────────────────────────────────

function tareaDe(snap: Snapshot, id: string | null | undefined): Tarea | null {
  if (!id) return null
  return (snap.tareas[id] as Tarea | undefined) ?? null
}

function fmtDur(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(r).padStart(2, '0')}s`
  if (m > 0) return `${m}m ${String(r).padStart(2, '0')}s`
  return `${r}s`
}

const ACTIVAS: ReadonlyArray<string> = ['pendiente', 'en_curso', 'pausada']

// ── piezas de UI ───────────────────────────────────────────────────────────

function Seccion({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="border-b border-rosa/40 px-4 py-3 dark:border-piso/60">
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-mueble/50 dark:text-neutral-500">
        {titulo}
      </h3>
      {children}
    </section>
  )
}

function Dato({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-mueble/50 dark:text-neutral-500">{k}</dt>
      <dd className="text-right font-mono">{v}</dd>
    </>
  )
}

/** Boton de control: deshabilitado muestra el motivo en el title (tooltip). */
function BotonCtl({
  activo,
  motivo,
  onClick,
  peligro,
  children,
}: {
  activo: boolean
  motivo?: string
  onClick: () => void
  peligro?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      disabled={!activo}
      title={activo ? undefined : (motivo ?? 'no aplica')}
      onClick={onClick}
      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35 ${
        peligro
          ? 'bg-magenta/15 text-magenta enabled:hover:bg-magenta/25'
          : 'bg-piso/10 text-piso enabled:hover:bg-piso/20 dark:bg-piso/40 dark:text-rosa dark:enabled:hover:bg-piso/60'
      }`}
    >
      {children}
    </button>
  )
}

function LinkTarea({ t, irA }: { t: Tarea; irA: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => irA(t.id)}
      title={`${t.id} · ${t.estado}`}
      className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-pared px-1.5 py-0.5 text-left hover:bg-rosa/40 dark:bg-neutral-800 dark:hover:bg-piso/50"
    >
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: COLOR_ESTADO[t.estado] }}
      />
      <span className="truncate">{t.titulo}</span>
      <span className="shrink-0 font-mono text-[10px] text-mueble/40 dark:text-neutral-500">
        {t.id}
      </span>
    </button>
  )
}

// ── cuerpo: tarea (jefe/director/trabajador) ───────────────────────────────

function CuerpoTarea({ tarea, irA }: { tarea: Tarea; irA: (id: string) => void }) {
  const snapshot = useOficina((s) => s.snapshot)
  const accion = useOficina((s) => s.accion)
  const editar = useOficina((s) => s.editar)
  const prioridad = useOficina((s) => s.prioridad)
  const reasignar = useOficina((s) => s.reasignar)
  const reiniciar = useOficina((s) => s.reiniciar)
  const mensaje = useOficina((s) => s.mensaje)

  const [ocupado, setOcupado] = useState(false)
  const [editando, setEditando] = useState(false)
  const [borrador, setBorrador] = useState('')
  const [para, setPara] = useState('')
  const [texto, setTexto] = useState('')

  // tick 1s: "tiempo trabajando" en vivo
  const [ahoraMs, setAhoraMs] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setAhoraMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  // auto-scroll del log cuando llegan eventos o cambia la tarea
  const logRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [tarea.id, tarea.eventos.length])

  // al cambiar de tarea, cerrar el editor y limpiar el mensaje a medias
  useEffect(() => {
    setEditando(false)
    setPara('')
    setTexto('')
  }, [tarea.id])

  const padre = tareaDe(snapshot, tarea.padre)
  const hijos = useMemo(
    () =>
      snapshot.orden
        .map((id) => tareaDe(snapshot, id))
        .filter((t): t is Tarea => t !== null && t.padre === tarea.id),
    [snapshot, tarea.id],
  )
  // hermanas pendientes que vienen DESPUES en la cola: esperan a que esta termine
  const esperan = useMemo(() => {
    const idx = snapshot.orden.indexOf(tarea.id)
    if (idx < 0) return []
    return snapshot.orden
      .slice(idx + 1)
      .map((id) => tareaDe(snapshot, id))
      .filter(
        (t): t is Tarea =>
          t !== null && t.padre === tarea.padre && t.estado === 'pendiente',
      )
  }, [snapshot, tarea.id, tarea.padre])

  const destinos = useMemo(
    () =>
      snapshot.orden
        .map((id) => tareaDe(snapshot, id))
        .filter(
          (t): t is Tarea =>
            t !== null && t.id !== tarea.id && ACTIVAS.includes(t.estado),
        ),
    [snapshot, tarea.id],
  )

  const correr = (fn: () => Promise<unknown>) => {
    setOcupado(true)
    void fn().finally(() => setOcupado(false))
  }

  const puedePausar = tarea.estado === 'en_curso'
  const puedeReanudar = tarea.estado === 'pausada'
  const puedeDetener = ACTIVAS.includes(tarea.estado)
  const puedeEditar = tarea.estado === 'pendiente' || tarea.estado === 'pausada'
  const puedePrio = tarea.estado === 'pendiente'
  const puedeReasignar =
    tarea.nivel === 'trabajador' &&
    (tarea.estado === 'pendiente' || tarea.estado === 'pausada')
  const puedeReiniciar = tarea.estado === 'fallida' || tarea.estado === 'detenida'
  const noAplica = `no aplica: estado ${tarea.estado}`

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Seccion titulo="tarea actual (prompt)">
        {editando ? (
          <>
            <textarea
              value={borrador}
              onChange={(e) => setBorrador(e.target.value)}
              rows={5}
              className="w-full resize-y rounded-md border border-rosa/70 bg-white p-2 text-xs outline-none focus:border-magenta dark:border-piso dark:bg-neutral-800"
            />
            <div className="mt-1.5 flex gap-1.5">
              <BotonCtl
                activo={!ocupado && borrador.trim() !== ''}
                motivo="el prompt no puede quedar vacío"
                onClick={() =>
                  correr(async () => {
                    if (await editar(tarea.id, borrador)) setEditando(false)
                  })
                }
              >
                Guardar
              </BotonCtl>
              <BotonCtl activo={!ocupado} onClick={() => setEditando(false)}>
                Cancelar
              </BotonCtl>
            </div>
          </>
        ) : (
          <>
            <p className="max-h-28 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-pared p-2 text-xs dark:bg-neutral-950/60">
              {tarea.detalle || '—'}
            </p>
            {tarea.solicitud && tarea.solicitud !== tarea.detalle && (
              <p className="mt-1 truncate text-[11px] text-mueble/50 dark:text-neutral-500" title={tarea.solicitud}>
                solicitud original: {tarea.solicitud}
              </p>
            )}
            <div className="mt-1.5">
              <BotonCtl
                activo={puedeEditar && !ocupado}
                motivo={noAplica + ' (solo pendiente/pausada)'}
                onClick={() => {
                  setBorrador(tarea.detalle)
                  setEditando(true)
                }}
              >
                ✎ Editar prompt
              </BotonCtl>
            </div>
          </>
        )}
      </Seccion>

      {tarea.resultado && (
        <Seccion titulo="resultado">
          <p className="max-h-36 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-lima/10 p-2 text-xs dark:bg-lima/5">
            {tarea.resultado}
          </p>
        </Seccion>
      )}

      <Seccion titulo="tiempo">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <Dato k="creada" v={tarea.creada} />
          <Dato
            k={tarea.estado === 'en_curso' ? 'trabajando hace' : 'desde creación'}
            v={fmtDur(msDesde(tarea.creada, new Date(ahoraMs)))}
          />
          {tarea.eventos.length > 0 && (
            <Dato k="último evento" v={tarea.eventos[tarea.eventos.length - 1].t} />
          )}
        </dl>
        <p className="mt-1 text-[10px] text-mueble/40 dark:text-neutral-600">
          medido desde la creación (el backend no expone ts de inicio real)
        </p>
      </Seccion>

      <Seccion titulo={`log · ${tarea.eventos.length} eventos`}>
        <div
          ref={logRef}
          className="max-h-40 overflow-y-auto rounded-md bg-pared p-2 font-mono text-[11px] leading-relaxed dark:bg-neutral-950/60"
        >
          {tarea.eventos.length === 0 && (
            <p className="text-mueble/40 dark:text-neutral-600">sin eventos</p>
          )}
          {tarea.eventos.map((ev, i) => (
            <p key={i} className="whitespace-pre-wrap break-words">
              <span className="text-magenta/70">{ev.t}</span> {ev.msg}
            </p>
          ))}
        </div>
      </Seccion>

      <Seccion titulo="dependencias">
        <div className="flex flex-col gap-1.5 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="shrink-0 text-mueble/50 dark:text-neutral-500">padre:</span>
            {padre ? <LinkTarea t={padre} irA={irA} /> : <span>— (raíz)</span>}
          </div>
          <div>
            <span className="text-mueble/50 dark:text-neutral-500">
              hijos ({hijos.length}):
            </span>
            {hijos.length > 0 ? (
              <div className="mt-1 flex flex-col items-start gap-1">
                {hijos.map((h) => (
                  <LinkTarea key={h.id} t={h} irA={irA} />
                ))}
              </div>
            ) : (
              <span> —</span>
            )}
          </div>
          {esperan.length > 0 && (
            <div>
              <span className="text-mueble/50 dark:text-neutral-500">
                esperan por él ({esperan.length} pendientes del mismo padre):
              </span>
              <div className="mt-1 flex flex-col items-start gap-1">
                {esperan.map((h) => (
                  <LinkTarea key={h.id} t={h} irA={irA} />
                ))}
              </div>
            </div>
          )}
        </div>
      </Seccion>

      <Seccion titulo="cpu / ram">
        <p className="text-xs text-mueble/60 dark:text-neutral-400">
          n/a (proceso compartido) — la única medición real es global y vive en el
          Mega Jefe
        </p>
      </Seccion>

      <Seccion titulo="controles">
        <div className="flex flex-wrap gap-1.5">
          <BotonCtl
            activo={puedePausar && !ocupado}
            motivo={noAplica + ' (solo en_curso)'}
            onClick={() => correr(() => accion(tarea.id, 'pausar'))}
          >
            ⏸ Pausar
          </BotonCtl>
          <BotonCtl
            activo={puedeReanudar && !ocupado}
            motivo={noAplica + ' (solo pausada)'}
            onClick={() => correr(() => accion(tarea.id, 'reanudar'))}
          >
            ▶ Reanudar
          </BotonCtl>
          <BotonCtl
            peligro
            activo={puedeDetener && !ocupado}
            motivo={noAplica + ' (ya terminó)'}
            onClick={() => correr(() => accion(tarea.id, 'detener'))}
          >
            ■ Cancelar
          </BotonCtl>
          <BotonCtl
            activo={puedePrio && !ocupado}
            motivo={noAplica + ' (prioridad: solo pendientes)'}
            onClick={() => correr(() => prioridad(tarea.id, -1))}
          >
            ▲ Prioridad
          </BotonCtl>
          <BotonCtl
            activo={puedePrio && !ocupado}
            motivo={noAplica + ' (prioridad: solo pendientes)'}
            onClick={() => correr(() => prioridad(tarea.id, 1))}
          >
            ▼ Prioridad
          </BotonCtl>
          <BotonCtl
            activo={puedeReiniciar && !ocupado}
            motivo={noAplica + ' (reiniciar: solo fallida/detenida)'}
            onClick={() =>
              correr(async () => {
                const nuevo = await reiniciar(tarea.id)
                if (nuevo) irA(nuevo) // saltar al clon recién creado
              })
            }
          >
            ↻ Reiniciar agente
          </BotonCtl>
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-mueble/50 dark:text-neutral-500">rol:</span>
          <select
            value={tarea.rol ?? ''}
            disabled={!puedeReasignar || ocupado}
            title={
              puedeReasignar
                ? undefined
                : 'reasignar: solo trabajador pendiente/pausada'
            }
            onChange={(e) => correr(() => reasignar(tarea.id, e.target.value as Rol))}
            className="rounded-md border border-rosa/70 bg-white px-2 py-1 outline-none focus:border-magenta disabled:cursor-not-allowed disabled:opacity-35 dark:border-piso dark:bg-neutral-800"
          >
            {tarea.rol === null && <option value="">sin rol</option>}
            <option value="investigador">investigador</option>
            <option value="implementador">implementador</option>
          </select>
        </div>
      </Seccion>

      <Seccion titulo="mensaje a otro agente">
        {destinos.length === 0 ? (
          <p className="text-xs text-mueble/40 dark:text-neutral-600">
            no hay otros agentes activos
          </p>
        ) : (
          <div className="flex flex-col gap-1.5">
            <select
              value={para}
              onChange={(e) => setPara(e.target.value)}
              className="rounded-md border border-rosa/70 bg-white px-2 py-1 text-xs outline-none focus:border-magenta dark:border-piso dark:bg-neutral-800"
            >
              <option value="">destino…</option>
              {destinos.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.titulo} ({d.id})
                </option>
              ))}
            </select>
            <div className="flex gap-1.5">
              <input
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                placeholder="texto del mensaje…"
                className="min-w-0 flex-1 rounded-md border border-rosa/70 bg-white px-2 py-1 text-xs outline-none focus:border-magenta dark:border-piso dark:bg-neutral-800"
              />
              <BotonCtl
                activo={para !== '' && texto.trim() !== '' && !ocupado}
                motivo="elegí destino y escribí el texto"
                onClick={() =>
                  correr(async () => {
                    if (await mensaje(tarea.id, para, texto.trim())) setTexto('')
                  })
                }
              >
                Enviar
              </BotonCtl>
            </div>
          </div>
        )}
      </Seccion>
    </div>
  )
}

// ── cuerpo: mega_jefe (métricas globales + colas + metas) ──────────────────

function CuerpoMegaJefe() {
  const sistema = useOficina((s) => s.sistema)
  const snapshot = useOficina((s) => s.snapshot)
  const colas = useMemo(() => contarColas(snapshot), [snapshot])

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Seccion titulo="sistema (proceso global)">
        {sistema ? (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <Dato
              k="cpu"
              v={sistema.cpu_pct !== null ? `${sistema.cpu_pct.toFixed(0)} %` : 'n/a (sin psutil)'}
            />
            <Dato
              k="ram"
              v={
                sistema.ram_mb !== null
                  ? `${sistema.ram_mb.toFixed(0)} MB${
                      sistema.ram_pct !== null ? ` (${sistema.ram_pct.toFixed(0)} %)` : ''
                    }`
                  : 'n/a (sin psutil)'
              }
            />
            <Dato
              k="threads"
              v={sistema.n_threads !== null ? String(sistema.n_threads) : 'n/a'}
            />
            <Dato k="uptime" v={fmtDur(sistema.uptime_s * 1000)} />
            <Dato k="agentes activos" v={String(sistema.agentes_activos)} />
            <Dato
              k="en curso / pend."
              v={`${sistema.tareas_en_curso} / ${sistema.tareas_pendientes}`}
            />
          </dl>
        ) : (
          <p className="text-xs text-mueble/40 dark:text-neutral-600">
            sin datos de /api/sistema todavía
          </p>
        )}
        <p className="mt-2 text-[10px] text-mueble/40 dark:text-neutral-600">
          única medición real: el proceso completo (no hay CPU/RAM por agente)
        </p>
      </Seccion>

      <Seccion titulo="colas">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <Dato k="pendientes" v={String(colas.pendientes)} />
          <Dato k="en curso" v={String(colas.enCurso)} />
          <Dato k="pausadas" v={String(colas.pausadas)} />
          <Dato k="hechas" v={String(colas.hechas)} />
          <Dato k="fallidas/detenidas" v={String(colas.fallidas)} />
        </dl>
      </Seccion>

      <Seccion titulo={`metas · ${snapshot.metas.length}`}>
        {snapshot.metas.length === 0 ? (
          <p className="text-xs text-mueble/40 dark:text-neutral-600">sin metas</p>
        ) : (
          <ul className="flex flex-col gap-1 text-xs">
            {[...snapshot.metas].reverse().map((m) => (
              <li key={m.id} className="flex items-baseline gap-2">
                <span className="shrink-0 font-mono text-magenta/70">{m.creada}</span>
                <span className="min-w-0 flex-1 truncate" title={m.texto}>
                  {m.texto}
                </span>
                <span className="shrink-0 text-mueble/50 dark:text-neutral-500">
                  [{m.estado}]
                </span>
              </li>
            ))}
          </ul>
        )}
      </Seccion>
    </div>
  )
}

// ── cuerpo: sala de módulo (actividad parseada) ────────────────────────────

function CuerpoModulo({ sala, irA }: { sala: Sala; irA: (id: string) => void }) {
  const snapshot = useOficina((s) => s.snapshot)
  const acts = useMemo(
    () =>
      derivarActividad(snapshot)
        .filter((a) => a.sala === sala.id)
        .slice(-12)
        .reverse(),
    [snapshot, sala.id],
  )

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Seccion titulo="actividad reciente (parseada de eventos en curso)">
        {acts.length === 0 ? (
          <p className="text-xs text-mueble/40 dark:text-neutral-600">
            sin actividad reciente de tareas en curso
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {acts.map((a) => {
              const origen = tareaDe(snapshot, a.tid)
              return (
                <li key={a.key} className="text-[11px]">
                  <span className="font-mono text-magenta/70">{a.t}</span>{' '}
                  <span className="break-words">{a.msg}</span>
                  {origen && (
                    <button
                      type="button"
                      onClick={() => irA(a.tid)}
                      className="ml-1 text-piso underline decoration-rosa underline-offset-2 hover:text-magenta dark:text-rosa"
                    >
                      {origen.titulo}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Seccion>
      <Seccion titulo="cpu / ram">
        <p className="text-xs text-mueble/60 dark:text-neutral-400">
          n/a (proceso compartido) — ver Mega Jefe
        </p>
      </Seccion>
    </div>
  )
}

// ── panel ──────────────────────────────────────────────────────────────────

export function Inspector({ onEnfocar }: InspectorProps) {
  const seleccion = useOficina((s) => s.seleccion)
  const setSeleccion = useOficina((s) => s.setSeleccion)
  const snapshot = useOficina((s) => s.snapshot)

  const salas = useMemo(() => derivarSalas(snapshot), [snapshot])
  const sala = seleccion ? (salas.find((x) => x.id === seleccion) ?? null) : null
  // la sala fija 'jefe' apunta a la tarea del jefe via tid
  const tarea = tareaDe(snapshot, seleccion) ?? tareaDe(snapshot, sala?.tid)

  const irA = (id: string) => {
    setSeleccion(id)
    onEnfocar?.(id)
  }

  return (
    <AnimatePresence>
      {seleccion !== null && (
        <motion.aside
          key="inspector"
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'tween', duration: 0.22, ease: 'easeOut' }}
          className="absolute inset-y-0 right-0 z-30 flex w-96 max-w-[92vw] flex-col border-l border-rosa/70 bg-white/95 text-mueble shadow-2xl backdrop-blur dark:border-piso dark:bg-neutral-900/95 dark:text-neutral-200"
        >
          <header className="flex items-start gap-2 border-b border-rosa/60 px-4 py-3 dark:border-piso">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm font-semibold">
                {tarea?.titulo ?? sala?.nombre ?? seleccion}
              </h2>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-mueble/60 dark:text-neutral-400">
                {tarea ? (
                  <>
                    <span className="rounded bg-piso/10 px-1.5 py-0.5 dark:bg-piso/40">
                      {tarea.nivel}
                    </span>
                    {tarea.rol && (
                      <span className="rounded bg-piso/10 px-1.5 py-0.5 dark:bg-piso/40">
                        {tarea.rol}
                      </span>
                    )}
                    <PillEstado estado={tarea.estado} />
                    <span className="font-mono">{tarea.id}</span>
                  </>
                ) : (
                  <span>{sala ? 'sala de módulo' : 'ya no existe en el estado'}</span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSeleccion(null)}
              title="cerrar"
              className="rounded-md px-1.5 py-0.5 text-mueble/50 hover:bg-rosa/40 hover:text-mueble dark:text-neutral-500 dark:hover:bg-piso/50 dark:hover:text-neutral-200"
            >
              ✕
            </button>
          </header>

          {tarea ? (
            <CuerpoTarea tarea={tarea} irA={irA} />
          ) : sala?.id === 'mega_jefe' ? (
            <CuerpoMegaJefe />
          ) : sala ? (
            <CuerpoModulo sala={sala} irA={irA} />
          ) : (
            <p className="px-4 py-3 text-xs text-mueble/40 dark:text-neutral-600">
              la selección ya no existe en el snapshot actual
            </p>
          )}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}

export default Inspector
