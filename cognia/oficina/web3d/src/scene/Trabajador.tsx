// Personaje low-poly procedural de la oficina (capsula + esfera + brazos).
// SOLO visual: recibe el estado ya derivado (lib/derivar.ts) y anima con
// useFrame; cero fetch, cero logica del sistema. Geometrias y materiales a
// nivel de modulo (compartidos entre todas las instancias, ~200 max) y
// useFrame sin allocs por frame (scratch Vector3 de modulo).
import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import type { EstadoTrabajador } from '../lib/derivar'
import { amortiguar, clamp01, easeInOutCubic, easeOutBack, oscilar, pulso } from './animaciones'

// ── interfaz ───────────────────────────────────────────────────────────────

export type RolVisual = 'investigador' | 'implementador' | 'jefe' | 'mega_jefe'

/** Trayecto de caminata (entrega del resultado hacia la sala del jefe).
 *  El padre lo setea cuando la tarea pasa a `hecha` y lo saca en onLlegada. */
export interface Camino {
  desde: [number, number, number]
  hasta: [number, number, number]
  /** unidades/segundo; default 1.6 */
  velocidad?: number
}

export interface TrabajadorProps {
  estado: EstadoTrabajador // 'trabajando' | 'esperando' | 'fallo' | 'hecho' | 'dormido'
  rol: RolVisual
  /** posicion del asiento (base del personaje) en coords del padre */
  posicion?: [number, number, number]
  /** orientacion sentado, radianes sobre Y (mirando al monitor) */
  rotacionY?: number
  /** si esta presente, CAMINA desde->hasta (prioridad sobre la pose sentada) */
  camino?: Camino | null
  /** se dispara UNA vez al llegar al final del camino */
  onLlegada?: () => void
  escala?: number
}

/** Tinte del escritorio segun estado. La Sala es duena del escritorio: usa
 *  este color para teñir su material cuando el trabajador esta en fallo
 *  (null = sin tinte). */
export function colorTinteEscritorio(estado: EstadoTrabajador): string | null {
  return estado === 'fallo' ? '#e5484d' : null
}

// ── recursos compartidos (una sola vez por modulo, no por instancia) ───────

const GEO_CUERPO = new THREE.CapsuleGeometry(0.22, 0.35, 4, 12)
const GEO_CABEZA = new THREE.SphereGeometry(0.16, 16, 12)
const GEO_OJO = new THREE.SphereGeometry(0.022, 8, 6)
const GEO_BRAZO = new THREE.CapsuleGeometry(0.055, 0.28, 3, 8)
const GEO_CORBATA = new THREE.ConeGeometry(0.055, 0.22, 4)
const GEO_SIGNO_BARRA = new THREE.BoxGeometry(0.07, 0.2, 0.07)
const GEO_SIGNO_PUNTO = new THREE.SphereGeometry(0.045, 10, 8)
// barras que arman las "Z" del dormido (billboard, mismo grupo que el "!")
const GEO_Z_H = new THREE.BoxGeometry(0.16, 0.045, 0.045)
const GEO_Z_DIAG = new THREE.BoxGeometry(0.2, 0.045, 0.045)

const MAT_PIEL = new THREE.MeshStandardMaterial({ color: '#f2c9a3', roughness: 0.85 })
const MAT_OJO = new THREE.MeshStandardMaterial({ color: '#2a2a2a', roughness: 0.4 })
const MAT_SIGNO = new THREE.MeshStandardMaterial({
  color: '#ff3b30',
  emissive: '#ff3b30',
  emissiveIntensity: 1.4,
})
const MAT_ZZZ = new THREE.MeshStandardMaterial({
  color: '#7aa2f7',
  emissive: '#7aa2f7',
  emissiveIntensity: 1.1,
})
const MAT_CORBATA = new THREE.MeshStandardMaterial({
  color: '#e91e8c',
  emissive: '#e91e8c',
  emissiveIntensity: 0.35,
  roughness: 0.5,
})
// colores por rol: investigador azul, implementador verde, jefes traje oscuro
const MATS_ROL: Record<RolVisual, THREE.MeshStandardMaterial> = {
  investigador: new THREE.MeshStandardMaterial({ color: '#3b82f6', roughness: 0.7 }),
  implementador: new THREE.MeshStandardMaterial({ color: '#2f9e63', roughness: 0.7 }),
  jefe: new THREE.MeshStandardMaterial({ color: '#2e2e36', roughness: 0.6 }),
  mega_jefe: new THREE.MeshStandardMaterial({ color: '#232331', roughness: 0.55 }),
}

// scratch reutilizado en useFrame (los useFrame corren en serie: es seguro)
const V_A = new THREE.Vector3()
const V_B = new THREE.Vector3()

const POS_DEFECTO: [number, number, number] = [0, 0, 0]
const DUR_FESTEJO = 1.3 // s de brazo arriba al pasar a 'hecho'
const K_SUAVE = 10 // velocidad de amortiguacion entre poses

// ── componente ─────────────────────────────────────────────────────────────

export function Trabajador({
  estado,
  rol,
  posicion = POS_DEFECTO,
  rotacionY = 0,
  camino = null,
  onLlegada,
  escala = 1,
}: TrabajadorProps) {
  const raiz = useRef<THREE.Group>(null)
  const cuerpo = useRef<THREE.Group>(null) // bob + encorvado
  const torso = useRef<THREE.Mesh>(null) // respiracion (escala solo del torso)
  const cabeza = useRef<THREE.Group>(null)
  const brazoIzq = useRef<THREE.Group>(null)
  const brazoDer = useRef<THREE.Group>(null)
  const signo = useRef<THREE.Group>(null) // "!" flotante en fallo

  // desfase por instancia: 200 trabajadores no tipean sincronizados
  const fase = useMemo(() => Math.random() * 20, [])

  const prevEstado = useRef<EstadoTrabajador | null>(null)
  const hechoT = useRef(-1e9) // momento (clock) del flanco a 'hecho'
  const progreso = useRef(0) // avance [0,1] sobre el camino
  const avisado = useRef(false) // onLlegada disparado

  // reset del trayecto cuando cambian los extremos del camino
  const claveCamino = camino ? `${camino.desde}>${camino.hasta}` : ''
  useEffect(() => {
    progreso.current = 0
    avisado.current = false
  }, [claveCamino])

  useFrame((st, dt) => {
    const g = raiz.current
    const cu = cuerpo.current
    const to = torso.current
    const cab = cabeza.current
    const bi = brazoIzq.current
    const bd = brazoDer.current
    if (!g || !cu || !to || !cab || !bi || !bd) return

    const dtc = Math.min(dt, 0.1) // evita saltos al volver de una tab inactiva
    const t = st.clock.elapsedTime + fase

    // flanco a 'hecho' -> festejo breve
    if (estado === 'hecho' && prevEstado.current !== 'hecho') hechoT.current = t
    prevEstado.current = estado

    // ── caminando (entrega): prioridad sobre la pose sentada ──
    if (camino) {
      V_A.set(camino.desde[0], camino.desde[1], camino.desde[2])
      V_B.set(camino.hasta[0], camino.hasta[1], camino.hasta[2])
      const largo = Math.max(V_A.distanceTo(V_B), 0.0001)
      const vel = camino.velocidad ?? 1.6
      progreso.current = Math.min(1, progreso.current + (dtc * vel) / largo)
      g.position.lerpVectors(V_A, V_B, easeInOutCubic(progreso.current))
      g.rotation.y = Math.atan2(V_B.x - V_A.x, V_B.z - V_A.z)

      const andando = progreso.current < 1
      const sw = andando ? oscilar(t, 2.2, 0.75) : 0 // brazos alternados
      bi.rotation.x = amortiguar(bi.rotation.x, sw, K_SUAVE, dtc)
      bd.rotation.x = amortiguar(bd.rotation.x, -sw, K_SUAVE, dtc)
      bi.rotation.z = amortiguar(bi.rotation.z, 0.08, K_SUAVE, dtc)
      bd.rotation.z = amortiguar(bd.rotation.z, -0.08, K_SUAVE, dtc)
      cu.position.y = andando ? Math.abs(oscilar(t, 4.4, 0.035)) : 0 // bob de paso
      cu.rotation.x = amortiguar(cu.rotation.x, 0, K_SUAVE, dtc)
      cab.rotation.set(0, 0, 0)
      to.scale.set(1, 1, 1)

      if (!andando && !avisado.current) {
        avisado.current = true
        onLlegada?.()
      }
      return
    }

    // ── sentado: targets de pose por estado + oscilaciones ──
    g.position.set(posicion[0], posicion[1], posicion[2])
    g.rotation.y = rotacionY

    let biX = -0.15 // brazos caidos (reposo)
    let bdX = -0.15
    let biZ = 0.12
    let bdZ = -0.12
    let cabX = 0
    let cabY = 0
    let cabZ = 0
    let cuRotX = 0 // encorvado
    let bob = 0
    let respirar = 0

    if (estado === 'trabajando') {
      // tipeo: brazos al frente oscilando alternados + mirada al monitor
      biX = -1.15 + oscilar(t, 4.2, 0.22)
      bdX = -1.15 + oscilar(t, 4.2, 0.22, Math.PI)
      biZ = 0.25
      bdZ = -0.25
      cabX = 0.22 + oscilar(t, 0.4, 0.03) // cabeza hacia el monitor
      cabY = oscilar(t, 0.23, 0.1) // barrido leve de la mirada
      bob = oscilar(t, 1.3, 0.015) // micro-bob
    } else if (estado === 'esperando') {
      respirar = oscilar(t, 0.28, 0.02) // respiracion sutil del torso
      cabX = pulso(t, 9, 0.22) * 0.4 // cabeceo lento ocasional
    } else if (estado === 'fallo') {
      biX = -2.7 // manos a la cabeza
      bdX = -2.7
      biZ = 0.55
      bdZ = -0.55
      cuRotX = 0.12 // encorvado
      cabX = 0.35
      cabZ = oscilar(t, 0.9, 0.08) // niega con la cabeza
    } else if (estado === 'dormido') {
      // acostado en la cama (la posicion la da camaDeSala): el cuerpo entero
      // se recuesta hacia atras y respira lento y profundo
      cuRotX = -1.42
      respirar = oscilar(t, 0.14, 0.035)
      biX = -0.35
      bdX = -0.35
      biZ = 0.25
      bdZ = -0.25
      cabX = -0.2 // cabeza apoyada en la almohada
    } else {
      // 'hecho': festejo breve tras el flanco, despues reposo respirando
      respirar = oscilar(t, 0.3, 0.015)
      const desde = t - hechoT.current
      if (desde < DUR_FESTEJO) {
        const sube = easeOutBack(clamp01(desde / 0.35))
        bdZ = -2.3 * sube + oscilar(t, 3, 0.2) // brazo derecho arriba saludando
        bdX = -0.4 * sube
        cabX = -0.15 * sube // mira arriba
      }
    }

    // aplicar con amortiguacion: transiciones suaves entre estados
    bi.rotation.x = amortiguar(bi.rotation.x, biX, K_SUAVE, dtc)
    bd.rotation.x = amortiguar(bd.rotation.x, bdX, K_SUAVE, dtc)
    bi.rotation.z = amortiguar(bi.rotation.z, biZ, K_SUAVE, dtc)
    bd.rotation.z = amortiguar(bd.rotation.z, bdZ, K_SUAVE, dtc)
    cab.rotation.x = amortiguar(cab.rotation.x, cabX, K_SUAVE, dtc)
    cab.rotation.y = amortiguar(cab.rotation.y, cabY, K_SUAVE, dtc)
    cab.rotation.z = amortiguar(cab.rotation.z, cabZ, K_SUAVE, dtc)
    cu.position.y = amortiguar(cu.position.y, bob, K_SUAVE, dtc)
    cu.rotation.x = amortiguar(cu.rotation.x, cuRotX, K_SUAVE, dtc)
    const sy = 1 + respirar
    const sxz = 1 - respirar * 0.5
    to.scale.set(
      amortiguar(to.scale.x, sxz, K_SUAVE, dtc),
      amortiguar(to.scale.y, sy, K_SUAVE, dtc),
      amortiguar(to.scale.z, sxz, K_SUAVE, dtc),
    )

    // "!" flotante: bobea, pulsa y mira siempre a la camara (billboard)
    const sg = signo.current
    if (sg) {
      sg.position.y = 1.35 + oscilar(t, 0.8, 0.06)
      sg.scale.setScalar(1 + oscilar(t, 1.6, 0.08))
      sg.quaternion.copy(st.camera.quaternion)
    }
  })

  const matCuerpo = MATS_ROL[rol]

  return (
    <group ref={raiz} position={posicion} rotation-y={rotacionY} scale={escala}>
      <group ref={cuerpo}>
        <mesh ref={torso} geometry={GEO_CUERPO} material={matCuerpo} position={[0, 0.45, 0]} castShadow />
        {rol === 'mega_jefe' && (
          // corbata magenta del mega-jefe (cono invertido al frente del pecho)
          <mesh
            geometry={GEO_CORBATA}
            material={MAT_CORBATA}
            position={[0, 0.55, 0.2]}
            rotation={[Math.PI, 0, 0]}
            scale={[1, 1, 0.45]}
          />
        )}
        <group ref={cabeza} position={[0, 0.95, 0]}>
          <mesh geometry={GEO_CABEZA} material={MAT_PIEL} castShadow />
          <mesh geometry={GEO_OJO} material={MAT_OJO} position={[-0.055, 0.02, 0.14]} />
          <mesh geometry={GEO_OJO} material={MAT_OJO} position={[0.055, 0.02, 0.14]} />
        </group>
        {/* brazos: el group pivotea en el hombro; la malla cuelga hacia abajo */}
        <group ref={brazoIzq} position={[-0.27, 0.62, 0]}>
          <mesh geometry={GEO_BRAZO} material={matCuerpo} position={[0, -0.17, 0]} />
        </group>
        <group ref={brazoDer} position={[0.27, 0.62, 0]}>
          <mesh geometry={GEO_BRAZO} material={matCuerpo} position={[0, -0.17, 0]} />
        </group>
      </group>

      {estado === 'fallo' && !camino && (
        <group ref={signo} position={[0, 1.35, 0]}>
          <mesh geometry={GEO_SIGNO_BARRA} material={MAT_SIGNO} position={[0, 0.09, 0]} />
          <mesh geometry={GEO_SIGNO_PUNTO} material={MAT_SIGNO} position={[0, -0.11, 0]} />
        </group>
      )}

      {estado === 'dormido' && !camino && (
        // "Zz" flotante (mismo ref que el "!": bobea y mira a camara)
        <group ref={signo} position={[0, 1.35, 0]}>
          {/* Z grande */}
          <mesh geometry={GEO_Z_H} material={MAT_ZZZ} position={[0, 0.14, 0]} />
          <mesh
            geometry={GEO_Z_DIAG}
            material={MAT_ZZZ}
            position={[0, 0.02, 0]}
            rotation={[0, 0, 0.85]}
          />
          <mesh geometry={GEO_Z_H} material={MAT_ZZZ} position={[0, -0.1, 0]} />
          {/* z chica arriba a la derecha */}
          <mesh geometry={GEO_Z_H} material={MAT_ZZZ} position={[0.24, 0.34, 0]} scale={0.55} />
          <mesh
            geometry={GEO_Z_DIAG}
            material={MAT_ZZZ}
            position={[0.24, 0.27, 0]}
            rotation={[0, 0, 0.85]}
            scale={0.55}
          />
          <mesh geometry={GEO_Z_H} material={MAT_ZZZ} position={[0.24, 0.2, 0]} scale={0.55} />
        </group>
      )}
    </group>
  )
}
