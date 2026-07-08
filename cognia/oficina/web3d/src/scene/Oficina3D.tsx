// Escena raiz de la oficina isometrica. Se monta DENTRO del <Canvas> de App:
//   <Canvas><Oficina3D /></Canvas>
// Camara ortografica isometrica + MapControls limitados (zoom 0.5x-3x, pan,
// azimutal ±30 grados, polar casi fijo), piso purpura con grid sutil, salas
// fijas + dinamicas derivadas del snapshot, mobiliario instanciado, un
// Trabajador por sala, paquetes viajando entre salas (diff de snapshots),
// tooltip de hover y lerp de camara hacia store.enfoque.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Grid, Html, MapControls, OrthographicCamera } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import * as THREE from 'three'
import type { MapControls as MapControlsImpl } from 'three-stdlib'
import { useOficina } from '../state/store'
import { derivarEscena, derivarPaquetes, derivarSalas, msDesde } from '../lib/derivar'
import type { EstadoTrabajador, Sala as SalaDatos } from '../lib/derivar'
import type { Snapshot } from '../state/tipos'
import { Sala } from './Sala'
import type { TamanoSala } from './Sala'
import { asientoDeSala, MobiliarioOficina } from './Mobiliario'
import type { SalaMueblada } from './Mobiliario'
import { Trabajador } from './Trabajador'
import type { RolVisual } from './Trabajador'
import { Paquete, tipoDePaqueteId } from './Paquete'
import type { TipoPaquete } from './Paquete'
import { Luces } from './Luces'
import { Tooltip } from '../panels/Tooltip'

// el grid logico de derivar.ts va de [0,0] a ~[37,15]; este offset lo centra
// alrededor del origen del mundo (donde apunta la camara)
const OFFSET_X = -19
const OFFSET_Z = -9

const ZOOM0 = 26
const AZIMUT_BASE = Math.PI / 4 // camara en [12,12,12] mirando al origen

function tamanoDe(def: SalaDatos): TamanoSala {
  const area = def.tamano[0] * def.tamano[1]
  return area >= 30 ? 'grande' : area >= 12 ? 'mediana' : 'chica'
}

function colorPisoDe(def: SalaDatos): string {
  if (def.id === 'mega_jefe') return '#ece4e8'
  if (def.tipo === 'director') return '#f6dde9'
  if (def.tipo === 'trabajador') return '#edf0d8'
  return '#efe9e4'
}

function rolVisualDe(def: SalaDatos, rol: 'investigador' | 'implementador' | null): RolVisual {
  if (def.id === 'mega_jefe') return 'mega_jefe'
  if (def.id === 'jefe' || def.tipo === 'director') return 'jefe'
  if (def.tipo === 'trabajador') return rol ?? 'implementador'
  // salas de modulo: alterna deterministico para variar el color
  return def.id.length % 2 === 0 ? 'investigador' : 'implementador'
}

function mismoSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false
  for (const x of a) if (!b.has(x)) return false
  return true
}

// paquete listo para animar (salas ya resueltas a coordenadas de mundo)
interface PaqueteVivo {
  id: string
  tipo: TipoPaquete
  de: [number, number, number]
  a: [number, number, number]
}

function centroDeSala(s: SalaDatos): [number, number, number] {
  return [
    s.posicion[0] + OFFSET_X + s.tamano[0] / 2,
    1.2,
    s.posicion[1] + OFFSET_Z + s.tamano[1] / 2,
  ]
}

const V_DELTA = new THREE.Vector3() // scratch del lerp de camara

export function Oficina3D() {
  const snapshot = useOficina((s) => s.snapshot)
  const seleccion = useOficina((s) => s.seleccion)
  const setSeleccion = useOficina((s) => s.setSeleccion)
  const enfoque = useOficina((s) => s.enfoque)
  const enfocar = useOficina((s) => s.enfocar)
  const filtro = useOficina((s) => s.filtro)

  const escena = useMemo(() => derivarEscena(snapshot, null), [snapshot])

  // salas de modulo iluminadas por actividad reciente (<4 s), refresco 500 ms
  const [modulosVivos, setModulosVivos] = useState<ReadonlySet<string>>(new Set())
  useEffect(() => {
    const calcular = () => {
      const vivos = new Set<string>()
      for (const a of escena.actividades) if (msDesde(a.t) < 4000) vivos.add(a.sala)
      setModulosVivos((prev) => (mismoSet(prev, vivos) ? prev : vivos))
    }
    calcular()
    const timer = setInterval(calcular, 500)
    return () => clearInterval(timer)
  }, [escena])

  const filtroNorm = filtro.trim().toLowerCase()

  const vistas = useMemo(
    () =>
      escena.salas.map((def) => {
        const idSel = def.tid ?? def.id
        const trabajando =
          def.trabajador?.estado === 'trabajando' ||
          modulosVivos.has(def.id) ||
          (def.id === 'mega_jefe' && escena.colas.enCurso > 0)
        return {
          def,
          idSel,
          pos: [def.posicion[0] + OFFSET_X, def.posicion[1] + OFFSET_Z] as [number, number],
          tamano: tamanoDe(def),
          trabajando,
          fallo: def.trabajador?.estado === 'fallo',
          seleccionada: seleccion !== null && (seleccion === def.id || seleccion === idSel),
          atenuada:
            filtroNorm !== '' &&
            !def.nombre.toLowerCase().includes(filtroNorm) &&
            !def.id.toLowerCase().includes(filtroNorm),
        }
      }),
    [escena, modulosVivos, seleccion, filtroNorm],
  )

  const muebladas = useMemo<SalaMueblada[]>(
    () =>
      vistas.map((v) => ({
        id: v.def.id,
        posicion: v.pos,
        ancho: v.def.tamano[0],
        prof: v.def.tamano[1],
        tamano: v.tamano,
        trabajando: v.trabajando,
      })),
    [vistas],
  )

  // un Trabajador por sala, sentado en la silla que dibuja Mobiliario
  const trabajadores = useMemo(
    () =>
      vistas.map((v, i) => {
        const tarea = v.def.tid ? snapshot.tareas[v.def.tid] : undefined
        const estado: EstadoTrabajador = v.def.trabajador
          ? v.def.trabajador.estado
          : v.trabajando
            ? 'trabajando'
            : 'esperando'
        const asiento = asientoDeSala(muebladas[i])
        return {
          key: v.def.id,
          estado,
          rol: rolVisualDe(v.def, tarea?.rol ?? null),
          posicion: asiento.pos,
          rotacionY: asiento.rotY,
          escala: v.def.id === 'mega_jefe' ? 1 : 0.88,
        }
      }),
    [vistas, muebladas, snapshot],
  )

  // ── paquetes: diff snapshot anterior -> actual, resueltos a mundo ──────────
  const [paquetes, setPaquetes] = useState<PaqueteVivo[]>([])
  const prevSnap = useRef<Snapshot | null>(null)
  useEffect(() => {
    const prev = prevSnap.current
    prevSnap.current = snapshot
    if (!prev || prev === snapshot) return
    const nuevos = derivarPaquetes(prev, snapshot)
    if (nuevos.length === 0) return
    // centros con las salas de AMBOS snapshots: el origen de un 'hecha:<tid>'
    // acaba de desaparecer del snapshot actual pero vivia en el anterior
    const centros = new Map<string, [number, number, number]>()
    for (const s of derivarSalas(prev)) centros.set(s.id, centroDeSala(s))
    for (const s of derivarSalas(snapshot)) centros.set(s.id, centroDeSala(s))
    setPaquetes((act) => {
      const vivos = new Map(act.map((p) => [p.id, p]))
      for (const p of nuevos) {
        if (vivos.has(p.id)) continue
        const de = centros.get(p.de)
        const a = centros.get(p.a)
        if (!de || !a) continue
        vivos.set(p.id, { id: p.id, tipo: tipoDePaqueteId(p.id), de, a })
      }
      return [...vivos.values()].slice(-24) // tope defensivo
    })
  }, [snapshot])
  const sacarPaquete = useCallback((id: string) => {
    setPaquetes((act) => act.filter((p) => p.id !== id))
  }, [])

  // ── tooltip de hover (id = idSel de la sala) ───────────────────────────────
  const [hover, setHover] = useState<string | null>(null)
  const vistaHover = hover
    ? (vistas.find((v) => v.idSel === hover || v.def.id === hover) ?? null)
    : null
  const tareaHover = vistaHover?.def.tid ? (snapshot.tareas[vistaHover.def.tid] ?? null) : null

  // ── lerp de camara hacia store.enfoque (buscador/inspector/doble-click) ────
  const controles = useRef<MapControlsImpl | null>(null)
  const objetivo = useRef<THREE.Vector3 | null>(null)
  const vistasRef = useRef(vistas)
  vistasRef.current = vistas
  useEffect(() => {
    if (!enfoque) return
    const v = vistasRef.current.find(
      (x) => x.idSel === enfoque.id || x.def.id === enfoque.id,
    )
    if (!v) return // la tarea ya no tiene sala (p.ej. hecha): no mover
    objetivo.current = new THREE.Vector3(
      v.pos[0] + v.def.tamano[0] / 2,
      0,
      v.pos[1] + v.def.tamano[1] / 2,
    )
  }, [enfoque])
  useFrame((_, dt) => {
    const o = objetivo.current
    const c = controles.current
    if (!o || !c) return
    V_DELTA.copy(o).sub(c.target)
    if (V_DELTA.lengthSq() < 0.002) {
      objetivo.current = null
      return
    }
    // pan puro: mover target y camara por el mismo delta (mantiene el angulo)
    V_DELTA.multiplyScalar(1 - Math.exp(-6 * Math.min(dt, 0.1)))
    c.target.add(V_DELTA)
    c.object.position.add(V_DELTA)
    c.update()
  })

  const limpiarSeleccion = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    setSeleccion(null)
  }

  // luces calidas nocturnas: mega_jefe primero, despues las salas trabajando
  const puntosNoche = useMemo<Array<[number, number, number]>>(() => {
    const centro = (v: (typeof vistas)[number]): [number, number, number] => [
      v.pos[0] + v.def.tamano[0] / 2,
      2.3,
      v.pos[1] + v.def.tamano[1] / 2,
    ]
    return [
      ...vistas.filter((v) => v.def.id === 'mega_jefe'),
      ...vistas.filter((v) => v.def.id !== 'mega_jefe' && v.trabajando),
      ...vistas.filter((v) => v.def.id !== 'mega_jefe' && !v.trabajando),
    ]
      .slice(0, 6)
      .map(centro)
  }, [vistas])

  return (
    <>
      <OrthographicCamera makeDefault position={[12, 12, 12]} zoom={ZOOM0} near={-100} far={200} />
      <MapControls
        ref={controles}
        makeDefault
        target={[0, 0, 0]}
        enableDamping
        dampingFactor={0.08}
        screenSpacePanning={false}
        minZoom={ZOOM0 * 0.5}
        maxZoom={ZOOM0 * 3}
        minAzimuthAngle={AZIMUT_BASE - Math.PI / 6}
        maxAzimuthAngle={AZIMUT_BASE + Math.PI / 6}
        minPolarAngle={0.92}
        maxPolarAngle={1.04}
      />

      <Luces puntos={puntosNoche} />

      {/* piso purpura con borde y grid sutil; click en el vacio deselecciona */}
      <mesh position={[0, -0.14, 0]} receiveShadow onClick={limpiarSeleccion}>
        <boxGeometry args={[42, 0.28, 22]} />
        <meshStandardMaterial color="#5e2249" roughness={0.95} />
      </mesh>
      <mesh position={[0, -0.32, 0]}>
        <boxGeometry args={[43.4, 0.3, 23.4]} />
        <meshStandardMaterial color="#3d1530" roughness={1} />
      </mesh>
      <Grid
        position={[0, 0.02, 0]}
        args={[42, 22]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#7a3a63"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#8d4573"
        fadeDistance={90}
        followCamera={false}
        infiniteGrid={false}
      />

      {vistas.map((v) => (
        <Sala
          key={v.def.id}
          id={v.idSel}
          nombre={v.def.nombre}
          tamano={v.tamano}
          ancho={v.def.tamano[0]}
          prof={v.def.tamano[1]}
          posicion={v.pos}
          activa={v.trabajando}
          fallo={v.fallo}
          seleccionada={v.seleccionada}
          atenuada={v.atenuada}
          megaJefe={v.def.id === 'mega_jefe'}
          colorPiso={colorPisoDe(v.def)}
          onSeleccionar={(id) => setSeleccion(seleccion === id ? null : id)}
          onDobleClick={(id) => {
            setSeleccion(id)
            enfocar(id)
          }}
          onHover={setHover}
        />
      ))}

      {trabajadores.map((t) => (
        <Trabajador
          key={t.key}
          estado={t.estado}
          rol={t.rol}
          posicion={t.posicion}
          rotacionY={t.rotacionY}
          escala={t.escala}
        />
      ))}

      {paquetes.map((p) => (
        <Paquete key={p.id} id={p.id} tipo={p.tipo} de={p.de} a={p.a} onLlegada={sacarPaquete} />
      ))}

      <MobiliarioOficina salas={muebladas} />

      {vistaHover && (
        <Html
          position={[
            vistaHover.pos[0] + vistaHover.def.tamano[0] / 2,
            3.9,
            vistaHover.pos[1] + vistaHover.def.tamano[1] / 2,
          ]}
          center
          zIndexRange={[40, 30]}
          style={{ pointerEvents: 'none' }}
        >
          <Tooltip
            nombre={vistaHover.def.nombre}
            estado={tareaHover?.estado ?? null}
            tarea={tareaHover?.detalle ?? null}
          />
        </Html>
      )}
    </>
  )
}
