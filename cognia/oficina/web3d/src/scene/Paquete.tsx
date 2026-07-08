// Paquetito de informacion viajando entre salas: cubo emisivo que recorre
// una curva bezier elevada + trail luminoso (drei). SOLO visual: el padre
// resuelve sala->coordenadas de mundo, monta desde derivar.derivarPaquetes
// y desmonta al recibir onLlegada. Recursos compartidos a nivel de modulo.
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Line, Trail } from '@react-three/drei'
import * as THREE from 'three'
import { clamp01, easeInOutCubic } from './animaciones'

// ── interfaz ───────────────────────────────────────────────────────────────

export type TipoPaquete = 'directiva' | 'resultado' | 'mensaje'

export interface PaqueteProps {
  /** id estable del paquete (el de derivar.derivarPaquetes) */
  id: string
  tipo: TipoPaquete
  /** origen/destino en coordenadas de MUNDO (el padre resuelve sala->pos) */
  de: [number, number, number]
  a: [number, number, number]
  /** duracion del viaje en segundos; default 1.6 */
  duracion?: number
  /** al llegar (una sola vez): el padre desmonta este paquete */
  onLlegada: (id: string) => void
}

/** Color por tipo (contrato visual): directiva magenta, resultado verde-lima,
 *  mensaje azul. Exportado para leyendas/paneles. */
export const COLOR_PAQUETE: Record<TipoPaquete, string> = {
  directiva: '#e91e8c',
  resultado: '#c6d62f',
  mensaje: '#3b82f6',
}

/** Mapea el id de derivar.derivarPaquetes al tipo visual:
 *  'crea:<tid>' = directiva (padre->hija), 'hecha:<tid>' = resultado
 *  (hija->padre); cualquier otro (POST /api/mensaje) = mensaje. */
export function tipoDePaqueteId(id: string): TipoPaquete {
  if (id.startsWith('crea:')) return 'directiva'
  if (id.startsWith('hecha:')) return 'resultado'
  return 'mensaje'
}

// ── recursos compartidos ───────────────────────────────────────────────────

const GEO_PAQUETE = new THREE.BoxGeometry(0.18, 0.18, 0.18)
const MATS_TIPO: Record<TipoPaquete, THREE.MeshStandardMaterial> = {
  directiva: new THREE.MeshStandardMaterial({
    color: COLOR_PAQUETE.directiva,
    emissive: COLOR_PAQUETE.directiva,
    emissiveIntensity: 1.6,
  }),
  resultado: new THREE.MeshStandardMaterial({
    color: COLOR_PAQUETE.resultado,
    emissive: COLOR_PAQUETE.resultado,
    emissiveIntensity: 1.6,
  }),
  mensaje: new THREE.MeshStandardMaterial({
    color: COLOR_PAQUETE.mensaje,
    emissive: COLOR_PAQUETE.mensaje,
    emissiveIntensity: 1.6,
  }),
}

// ── componente ─────────────────────────────────────────────────────────────

export function Paquete({ id, tipo, de, a, duracion = 1.6, onLlegada }: PaqueteProps) {
  const cubo = useRef<THREE.Mesh>(null)
  const inicio = useRef(-1) // clock del primer frame
  const llego = useRef(false)

  // curva elevada de/a: el paquete "vuela" por encima de las salas.
  // clave por valores (de/a son arrays nuevos en cada render del padre).
  const claveRuta = `${de}>${a}`
  const curva = useMemo(() => {
    const pDe = new THREE.Vector3(de[0], de[1], de[2])
    const pA = new THREE.Vector3(a[0], a[1], a[2])
    const control = pDe.clone().add(pA).multiplyScalar(0.5)
    control.y += Math.max(1.2, pDe.distanceTo(pA) * 0.3)
    return new THREE.QuadraticBezierCurve3(pDe, control, pA)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claveRuta])

  // trazo tenue de la ruta completa (guia visual del viaje)
  const puntosRuta = useMemo(() => curva.getPoints(24), [curva])

  useFrame((st, dt) => {
    const m = cubo.current
    if (!m) return
    if (inicio.current < 0) inicio.current = st.clock.elapsedTime
    const u = clamp01((st.clock.elapsedTime - inicio.current) / duracion)
    curva.getPointAt(easeInOutCubic(u), m.position) // sin allocs: target reusado
    m.rotation.x += dt * 2.5
    m.rotation.y += dt * 3.7
    if (u >= 1 && !llego.current) {
      llego.current = true
      onLlegada(id)
    }
  })

  return (
    <group>
      <Line points={puntosRuta} color={COLOR_PAQUETE[tipo]} lineWidth={1} transparent opacity={0.25} />
      <Trail
        width={0.8}
        length={3}
        decay={2}
        color={COLOR_PAQUETE[tipo]}
        attenuation={(w: number) => w * w}
      >
        <mesh ref={cubo} geometry={GEO_PAQUETE} material={MATS_TIPO[tipo]} position={de} />
      </Trail>
    </group>
  )
}
