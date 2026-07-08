// Sala isometrica parametrica: piso propio, 2 paredes traseras (norte/oeste,
// estilo referencia) con zocalo magenta, etiqueta flotante, glow cuando esta
// activa y borde rojo pulsante cuando fallo. La sala mega_jefe agrega
// pantallas gigantes en las paredes con metricas REALES del store
// (/api/sistema + colas del snapshot) y un mapa simplificado del sistema.
import { useEffect, useMemo, useRef } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import * as THREE from 'three'
import { useOficina } from '../state/store'
import { contarColas, derivarSalas } from '../lib/derivar'
import type { Sala as SalaDatos } from '../lib/derivar'

export type TamanoSala = 'chica' | 'mediana' | 'grande'

export interface SalaProps {
  /** id que se reporta al seleccionar (tid de la tarea si la sala tiene una) */
  id: string
  nombre: string
  tamano: TamanoSala
  ancho: number // celdas de mundo
  prof: number
  posicion: [number, number] // esquina [x, z] en mundo
  activa: boolean
  fallo: boolean
  seleccionada: boolean
  /** true cuando hay filtro y esta sala NO matchea: se dibuja translucida */
  atenuada?: boolean
  /** dibuja las pantallas gigantes de pared (solo la sala mega_jefe) */
  megaJefe?: boolean
  colorPiso?: string
  onSeleccionar?: (id: string) => void
  /** doble click: la escena centra la camara en esta sala */
  onDobleClick?: (id: string) => void
  /** hover para el tooltip 2D (id al entrar, null al salir) */
  onHover?: (id: string | null) => void
}

const ALTO_PARED = 2.3
const GROSOR = 0.12

export function Sala({
  id,
  nombre,
  ancho,
  prof,
  posicion,
  activa,
  fallo,
  seleccionada,
  atenuada = false,
  megaJefe = false,
  colorPiso = '#efe9e4',
  onSeleccionar,
  onDobleClick,
  onHover,
}: SalaProps) {
  const grupo = useRef<THREE.Group>(null)
  const glowMat = useRef<THREE.MeshBasicMaterial>(null)

  // material compartido por las 4 barras del borde (fallo/seleccion)
  const matBorde = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: '#ffffff',
        transparent: true,
        opacity: 0,
        depthWrite: false,
      }),
    [],
  )
  useEffect(() => () => matBorde.dispose(), [matBorde])

  useFrame((st, dt) => {
    const t = st.clock.elapsedTime
    // pop de aparicion: la sala nace en escala ~0 y crece (salas dinamicas)
    if (grupo.current) {
      grupo.current.scale.setScalar(THREE.MathUtils.damp(grupo.current.scale.x, 1, 6, dt))
    }
    if (glowMat.current) {
      const objetivo = activa ? 0.13 + 0.07 * Math.sin(t * 3.2) : 0
      glowMat.current.opacity = THREE.MathUtils.damp(glowMat.current.opacity, objetivo, 8, dt)
    }
    const objetivoBorde = fallo ? 0.55 + 0.35 * Math.sin(t * 5) : seleccionada ? 0.9 : 0
    matBorde.opacity = THREE.MathUtils.damp(matBorde.opacity, objetivoBorde, 10, dt)
    matBorde.color.set(fallo ? '#ff3b30' : '#ffffff')
  })

  const click = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    onSeleccionar?.(id)
  }

  const opacidad = atenuada ? 0.25 : 1

  return (
    <group
      ref={grupo}
      position={[posicion[0], 0, posicion[1]]}
      scale={0.01}
      onClick={click}
      onDoubleClick={(e) => {
        e.stopPropagation()
        onDobleClick?.(id)
      }}
      onPointerOver={(e) => {
        e.stopPropagation()
        document.body.style.cursor = 'pointer'
        onHover?.(id)
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'auto'
        onHover?.(null)
      }}
    >
      {/* piso propio */}
      <mesh position={[ancho / 2, 0.06, prof / 2]} receiveShadow>
        <boxGeometry args={[ancho, 0.12, prof]} />
        <meshStandardMaterial color={colorPiso} roughness={0.95} transparent opacity={opacidad} />
      </mesh>

      {/* glow aditivo cuando la sala esta activa */}
      <mesh position={[ancho / 2, 0.145, prof / 2]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[ancho - 0.45, prof - 0.45]} />
        <meshBasicMaterial
          ref={glowMat}
          color="#d8e94f"
          transparent
          opacity={0}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* pared norte + zocalo magenta */}
      <mesh position={[ancho / 2, ALTO_PARED / 2 + 0.12, GROSOR / 2]} castShadow receiveShadow>
        <boxGeometry args={[ancho, ALTO_PARED, GROSOR]} />
        <meshStandardMaterial color="#f4f2ef" roughness={0.9} transparent opacity={opacidad} />
      </mesh>
      <mesh position={[ancho / 2, 0.22, GROSOR + 0.03]}>
        <boxGeometry args={[ancho, 0.2, 0.06]} />
        <meshStandardMaterial color="#e91e8c" roughness={0.7} transparent opacity={opacidad} />
      </mesh>

      {/* pared oeste + zocalo magenta */}
      <mesh position={[GROSOR / 2, ALTO_PARED / 2 + 0.12, prof / 2]} castShadow receiveShadow>
        <boxGeometry args={[GROSOR, ALTO_PARED, prof]} />
        <meshStandardMaterial color="#f4f2ef" roughness={0.9} transparent opacity={opacidad} />
      </mesh>
      <mesh position={[GROSOR + 0.03, 0.22, prof / 2]}>
        <boxGeometry args={[0.06, 0.2, prof]} />
        <meshStandardMaterial color="#e91e8c" roughness={0.7} transparent opacity={opacidad} />
      </mesh>

      {/* borde perimetral (rojo pulsante en fallo, blanco fijo en seleccion) */}
      <mesh position={[ancho / 2, 0.14, -0.06]} material={matBorde}>
        <boxGeometry args={[ancho + 0.24, 0.08, 0.12]} />
      </mesh>
      <mesh position={[ancho / 2, 0.14, prof + 0.06]} material={matBorde}>
        <boxGeometry args={[ancho + 0.24, 0.08, 0.12]} />
      </mesh>
      <mesh position={[-0.06, 0.14, prof / 2]} material={matBorde}>
        <boxGeometry args={[0.12, 0.08, prof + 0.24]} />
      </mesh>
      <mesh position={[ancho + 0.06, 0.14, prof / 2]} material={matBorde}>
        <boxGeometry args={[0.12, 0.08, prof + 0.24]} />
      </mesh>

      {/* etiqueta 3D (sprite: siempre mira a camara, escala con el zoom) */}
      <Html
        transform
        sprite
        position={[ancho / 2, ALTO_PARED + 0.75, prof / 2]}
        scale={0.024}
        zIndexRange={[5, 0]}
        style={{ pointerEvents: 'none' }}
      >
        <div
          className={
            'flex items-center gap-2 rounded-full border px-4 py-1 font-semibold shadow-sm ' +
            (seleccionada
              ? 'border-magenta bg-magenta text-white'
              : 'border-rosa/80 bg-white/85 text-mueble')
          }
          style={{ fontSize: 30, whiteSpace: 'nowrap', opacity: atenuada ? 0.15 : 1 }}
        >
          <span
            style={{
              width: 14,
              height: 14,
              borderRadius: 9999,
              background: fallo ? '#ff3b30' : activa ? '#c6d62f' : '#d9c9d4',
            }}
          />
          {nombre}
        </div>
      </Html>

      {megaJefe && <PantallasMegaJefe ancho={ancho} prof={prof} />}
    </group>
  )
}

// ── pantallas gigantes del mega_jefe (metricas reales del store) ───────────

const ePantallaTitulo: CSSProperties = {
  fontSize: 13,
  letterSpacing: 2,
  color: '#f8bbd9',
  marginBottom: 6,
}

function PantallaGigante({
  w,
  h,
  position,
  rotY = 0,
  children,
}: {
  w: number
  h: number
  position: [number, number, number]
  rotY?: number
  children: ReactNode
}) {
  const PX = 240 // ancho del elemento en px; scale = w/PX => ocupa w unidades de mundo
  return (
    <group position={position} rotation={[0, rotY, 0]}>
      <mesh castShadow>
        <boxGeometry args={[w + 0.16, h + 0.16, 0.08]} />
        <meshStandardMaterial color="#23262d" roughness={0.6} />
      </mesh>
      <Html
        transform
        position={[0, 0, 0.06]}
        scale={w / PX}
        zIndexRange={[4, 0]}
        style={{ pointerEvents: 'none' }}
      >
        <div
          style={{
            width: PX,
            height: (PX * h) / w,
            background: '#0d1117',
            color: '#c6d62f',
            borderRadius: 6,
            padding: '10px 12px',
            fontFamily: 'ui-monospace, SFMono-Regular, monospace',
            boxShadow: '0 0 22px rgba(198,214,47,.3)',
            overflow: 'hidden',
          }}
        >
          {children}
        </div>
      </Html>
    </group>
  )
}

function Metrica({ etiqueta, valor, pct }: { etiqueta: string; valor: string; pct: number | null }) {
  return (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
        <span style={{ color: '#f8bbd9' }}>{etiqueta}</span>
        <span>{valor}</span>
      </div>
      <div style={{ height: 6, background: '#1d2733', borderRadius: 3, overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${Math.min(100, Math.max(0, pct ?? 0))}%`,
            background: '#c6d62f',
          }}
        />
      </div>
    </div>
  )
}

function Contador({ n, etiqueta, color }: { n: number; etiqueta: string; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 30, fontWeight: 700, color, lineHeight: 1.1 }}>{n}</div>
      <div style={{ fontSize: 10, color: '#8b949e', letterSpacing: 1 }}>{etiqueta}</div>
    </div>
  )
}

function colorSalaMini(s: SalaDatos): string {
  if (!s.trabajador) return '#8a5d7d'
  if (s.trabajador.estado === 'trabajando') return '#c6d62f'
  if (s.trabajador.estado === 'fallo') return '#ff5252'
  if (s.trabajador.estado === 'hecho') return '#8f8f8f'
  return '#f8bbd9' // esperando
}

function fmtUptime(s: number): string {
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

function PantallasMegaJefe({ ancho, prof }: { ancho: number; prof: number }) {
  const sistema = useOficina((s) => s.sistema)
  const snapshot = useOficina((s) => s.snapshot)
  const colas = useMemo(() => contarColas(snapshot), [snapshot])
  const mapa = useMemo(() => derivarSalas(snapshot), [snapshot])
  const maxX = Math.max(24, ...mapa.map((s) => s.posicion[0] + s.tamano[0]))
  const maxZ = Math.max(15, ...mapa.map((s) => s.posicion[1] + s.tamano[1]))

  return (
    <>
      {/* pared norte: sistema + colas */}
      <PantallaGigante w={2.5} h={1.5} position={[ancho * 0.25, 1.6, GROSOR + 0.02]}>
        <div style={ePantallaTitulo}>SISTEMA</div>
        <Metrica
          etiqueta="CPU"
          valor={sistema?.cpu_pct != null ? `${sistema.cpu_pct.toFixed(0)}%` : '--'}
          pct={sistema?.cpu_pct ?? null}
        />
        <Metrica
          etiqueta="RAM"
          valor={sistema?.ram_mb != null ? `${sistema.ram_mb.toFixed(0)} MB` : '--'}
          pct={sistema?.ram_pct ?? null}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
          <span>THR {sistema?.n_threads ?? '--'}</span>
          <span>AG {sistema?.agentes_activos ?? 0}</span>
          <span>UP {sistema ? fmtUptime(sistema.uptime_s) : '--'}</span>
        </div>
      </PantallaGigante>

      <PantallaGigante w={2.5} h={1.5} position={[ancho * 0.73, 1.6, GROSOR + 0.02]}>
        <div style={ePantallaTitulo}>COLAS</div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '6px 4px',
            alignItems: 'center',
          }}
        >
          <Contador n={colas.enCurso} etiqueta="EN CURSO" color="#c6d62f" />
          <Contador n={colas.pendientes} etiqueta="PENDIENTES" color="#f8bbd9" />
          <Contador n={colas.hechas} etiqueta="HECHAS" color="#fafafa" />
          <Contador n={colas.fallidas} etiqueta="FALLIDAS" color="#ff5252" />
        </div>
      </PantallaGigante>

      {/* pared oeste: mapa simplificado del sistema */}
      <PantallaGigante w={2.8} h={1.6} position={[GROSOR + 0.02, 1.6, prof / 2]} rotY={Math.PI / 2}>
        <div style={ePantallaTitulo}>MAPA DEL SISTEMA</div>
        <div style={{ position: 'relative', width: '100%', height: 'calc(100% - 24px)' }}>
          {mapa.map((s) => (
            <div
              key={s.id}
              style={{
                position: 'absolute',
                left: `${(s.posicion[0] / maxX) * 100}%`,
                top: `${(s.posicion[1] / maxZ) * 100}%`,
                width: `${(s.tamano[0] / maxX) * 100}%`,
                height: `${(s.tamano[1] / maxZ) * 100}%`,
                background: colorSalaMini(s),
                borderRadius: 2,
                opacity: 0.9,
              }}
            />
          ))}
        </div>
      </PantallaGigante>
    </>
  )
}
