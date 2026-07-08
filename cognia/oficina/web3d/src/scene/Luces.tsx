// Iluminacion dia/noche con transicion animada (damp por frame, sin tweens).
// Dia: ambiente calido + UNA sola direccional con sombras (mapa chico).
// Noche: ambiente azulado + pool FIJO de luces puntuales calidas: mantener
// constante el numero de luces evita recompilar shaders al alternar el modo.
import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { useOficina } from '../state/store'

export interface LucesProps {
  /** centros [x,y,z] de salas a iluminar de noche (se usan los primeros 6) */
  puntos?: Array<[number, number, number]>
}

const MAX_PUNTOS = 6
const POS_OCULTA: [number, number, number] = [0, -40, 0]

interface Clima {
  fondo: THREE.Color
  amb: THREE.Color
  ambInt: number
  dir: THREE.Color
  dirInt: number
  cielo: THREE.Color
  suelo: THREE.Color
  hemiInt: number
  puntoInt: number
}

const DIA: Clima = {
  fondo: new THREE.Color('#f8bbd9'),
  amb: new THREE.Color('#fff3e9'),
  ambInt: 0.85,
  dir: new THREE.Color('#fff8ee'),
  dirInt: 1.35,
  cielo: new THREE.Color('#ffeaf4'),
  suelo: new THREE.Color('#5e2249'),
  hemiInt: 0.42,
  puntoInt: 0,
}

const NOCHE: Clima = {
  fondo: new THREE.Color('#150b1d'),
  amb: new THREE.Color('#4a5490'),
  ambInt: 0.34,
  dir: new THREE.Color('#5c6ab8'),
  dirInt: 0.15,
  cielo: new THREE.Color('#333d78'),
  suelo: new THREE.Color('#170c22'),
  hemiInt: 0.2,
  puntoInt: 6,
}

const lerp = THREE.MathUtils.lerp

export function Luces({ puntos = [] }: LucesProps) {
  const noche = useOficina((s) => s.modoNoche)
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)

  // sombras baratas: se activan una vez, solo la direccional las castea
  useEffect(() => {
    gl.shadowMap.enabled = true
    gl.shadowMap.type = THREE.PCFSoftShadowMap
  }, [gl])

  // el fondo tiene que ser un Color mutable para poder lerpearlo por frame
  useEffect(() => {
    if (!(scene.background instanceof THREE.Color)) scene.background = DIA.fondo.clone()
  }, [scene])

  const amb = useRef<THREE.AmbientLight>(null)
  const hemi = useRef<THREE.HemisphereLight>(null)
  const dir = useRef<THREE.DirectionalLight>(null)
  const pts = useRef<Array<THREE.PointLight | null>>([])

  useFrame((_, dt) => {
    const o = noche ? NOCHE : DIA
    const f = 1 - Math.exp(-3 * Math.min(dt, 0.1)) // damp independiente del framerate
    if (amb.current) {
      amb.current.intensity = lerp(amb.current.intensity, o.ambInt, f)
      amb.current.color.lerp(o.amb, f)
    }
    if (hemi.current) {
      hemi.current.intensity = lerp(hemi.current.intensity, o.hemiInt, f)
      hemi.current.color.lerp(o.cielo, f)
      hemi.current.groundColor.lerp(o.suelo, f)
    }
    if (dir.current) {
      dir.current.intensity = lerp(dir.current.intensity, o.dirInt, f)
      dir.current.color.lerp(o.dir, f)
    }
    for (let i = 0; i < MAX_PUNTOS; i++) {
      const l = pts.current[i]
      if (!l) continue
      const objetivo = noche && i < puntos.length ? o.puntoInt : 0
      l.intensity = lerp(l.intensity, objetivo, f)
    }
    if (scene.background instanceof THREE.Color) scene.background.lerp(o.fondo, f)
  })

  return (
    <>
      <ambientLight ref={amb} color="#fff3e9" intensity={0.85} />
      <hemisphereLight ref={hemi} args={['#ffeaf4', '#5e2249', 0.42]} />
      <directionalLight
        ref={dir}
        position={[18, 26, 12]}
        color="#fff8ee"
        intensity={1.35}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-bias={-0.0004}
        shadow-camera-left={-28}
        shadow-camera-right={28}
        shadow-camera-top={28}
        shadow-camera-bottom={-28}
        shadow-camera-near={1}
        shadow-camera-far={80}
      />
      {Array.from({ length: MAX_PUNTOS }, (_, i) => (
        <pointLight
          key={i}
          ref={(l) => {
            pts.current[i] = l
          }}
          position={puntos[i] ?? POS_OCULTA}
          color="#ffb46b"
          intensity={0}
          distance={7.5}
          decay={1.6}
        />
      ))}
    </>
  )
}
