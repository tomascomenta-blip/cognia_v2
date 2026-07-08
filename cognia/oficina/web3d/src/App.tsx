// Composicion raiz: header (SSE, buscador, dia/noche, vista clasica) +
// Canvas 3D (Oficina3D) + paneles 2D (Buscador, Minimapa, Timeline,
// Inspector). Todos los paneles enfocan la camara via store.enfocar; la
// escena consume store.enfoque y lerpea. Solo visualiza/controla via HTTP.
import { useEffect, useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import { AnimatePresence, motion } from 'framer-motion'
import { useOficina, conectar } from './state/store'
import { derivarEscena } from './lib/derivar'
import { Oficina3D } from './scene/Oficina3D'
import { Inspector } from './panels/Inspector'
import { Buscador } from './panels/Buscador'
import { Minimapa } from './panels/Minimapa'
import { Timeline } from './panels/Timeline'

function App() {
  const snapshot = useOficina((s) => s.snapshot)
  const conectado = useOficina((s) => s.conectado)
  const vista = useOficina((s) => s.vista)
  const modoNoche = useOficina((s) => s.modoNoche)
  const filtro = useOficina((s) => s.filtro)
  const toggleVista = useOficina((s) => s.toggleVista)
  const toggleNoche = useOficina((s) => s.toggleNoche)
  const setFiltro = useOficina((s) => s.setFiltro)
  const enfocar = useOficina((s) => s.enfocar)

  useEffect(() => {
    conectar()
  }, [])

  // modo noche: clase .dark en <html> (ver @custom-variant en index.css)
  useEffect(() => {
    document.documentElement.classList.toggle('dark', modoNoche)
  }, [modoNoche])

  const escena = useMemo(() => derivarEscena(snapshot, null), [snapshot])
  const clasicaAbierta = vista === 'clasica-abierta'

  return (
    <div className="flex h-full flex-col bg-pared text-mueble dark:bg-neutral-950 dark:text-neutral-200">
      {/* ── header ── */}
      <header className="flex items-center gap-3 border-b border-rosa/60 bg-white/80 px-4 py-2 backdrop-blur dark:border-piso dark:bg-neutral-900/80">
        <h1 className="text-sm font-semibold tracking-wide">
          <span className="text-magenta">Cognia</span> · Oficina 3D
        </h1>

        <span
          className={`ml-1 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${
            conectado
              ? 'bg-lima/25 text-mueble dark:text-lima'
              : 'bg-magenta/15 text-magenta'
          }`}
          title={conectado ? 'SSE/poll activo' : 'sin conexión con el backend'}
        >
          <span
            className={`h-2 w-2 rounded-full ${
              conectado ? 'bg-lima' : 'animate-pulse bg-magenta'
            }`}
          />
          {conectado ? 'conectado' : 'desconectado'}
        </span>

        <input
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          placeholder="Buscar sala o tarea…"
          className="mx-auto w-72 max-w-[40vw] rounded-md border border-rosa/70 bg-white px-3 py-1 text-sm outline-none placeholder:text-mueble/40 focus:border-magenta dark:border-piso dark:bg-neutral-800 dark:placeholder:text-neutral-500"
        />

        <span className="rounded-full bg-piso/10 px-2 py-0.5 text-xs dark:bg-piso/40">
          {escena.salas.length} salas · {escena.colas.enCurso} en curso
        </span>

        <button
          type="button"
          onClick={toggleNoche}
          className="rounded-md border border-rosa/70 bg-white px-2.5 py-1 text-sm hover:border-magenta dark:border-piso dark:bg-neutral-800"
          title="alternar día/noche"
        >
          {modoNoche ? '☀ día' : '☾ noche'}
        </button>

        <button
          type="button"
          onClick={toggleVista}
          className={`rounded-md px-2.5 py-1 text-sm font-medium ${
            clasicaAbierta
              ? 'bg-magenta text-white'
              : 'border border-rosa/70 bg-white hover:border-magenta dark:border-piso dark:bg-neutral-800'
          }`}
        >
          Vista Clásica
        </button>
      </header>

      {/* ── cuerpo: canvas 3D + paneles 2D + panel clásico desplegable ── */}
      <main className="relative flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <Canvas shadows dpr={[1, 2]}>
            <Oficina3D />
          </Canvas>

          {/* paneles 2D superpuestos (todos enfocan via store.enfocar) */}
          <Buscador onEnfocar={enfocar} />
          <Minimapa onEnfocar={enfocar} />
          <Timeline onEnfocar={enfocar} />
          <Inspector onEnfocar={enfocar} />
        </div>

        <AnimatePresence>
          {clasicaAbierta && (
            <motion.aside
              key="clasica"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'tween', duration: 0.25, ease: 'easeOut' }}
              className="absolute inset-y-0 right-0 z-40 w-[45%] border-l border-rosa/70 bg-white shadow-xl dark:border-piso dark:bg-neutral-900"
            >
              <iframe
                src="/"
                title="Dashboard clásico"
                className="h-full w-full border-0"
              />
            </motion.aside>
          )}
        </AnimatePresence>
      </main>
    </div>
  )
}

export default App
