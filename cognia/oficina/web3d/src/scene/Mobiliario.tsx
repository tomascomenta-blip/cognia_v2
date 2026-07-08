// Mobiliario low-poly procedural (cero texturas externas, CSP-friendly).
// TODAS las piezas repetidas de la oficina se dibujan instanciadas: un
// InstancedMesh (drei <Instances>) por combinacion geometria+material, o sea
// ~7 draw calls para el mobiliario completo sin importar cuantas salas haya.
// Las pantallas de los monitores son un grupo aparte (material basico, color
// por instancia) y "parpadean" cuando su sala esta trabajando.
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Instance, Instances } from '@react-three/drei'
import * as THREE from 'three'

export type TamanoMueble = 'chica' | 'mediana' | 'grande'

/** Lo minimo que Mobiliario necesita saber de una sala (interfaz propia:
 *  Oficina3D la construye desde las salas derivadas del snapshot). */
export interface SalaMueblada {
  id: string
  posicion: [number, number] // esquina [x, z] en mundo
  ancho: number
  prof: number
  tamano: TamanoMueble
  trabajando: boolean // los monitores de la sala parpadean
}

export interface MobiliarioOficinaProps {
  salas: SalaMueblada[]
}

// ── grupos instanciados (geometria + material compartidos) ─────────────────

type Grupo = 'magenta' | 'gris' | 'lima' | 'blanco' | 'maceta' | 'hojas' | 'pantalla'

const ORDEN_GRUPOS: ReadonlyArray<Grupo> = [
  'magenta',
  'gris',
  'lima',
  'blanco',
  'maceta',
  'hojas',
  'pantalla',
]

const COLOR_GRUPO: Record<Grupo, string> = {
  magenta: '#e91e8c',
  gris: '#3a3a3a',
  lima: '#c6d62f',
  blanco: '#fafafa',
  maceta: '#e91e8c',
  hojas: '#69a52e',
  pantalla: '#27303f', // color inicial; se anima por instancia
}

interface Parte {
  grupo: Grupo
  pos: [number, number, number]
  rotY: number
  escala: [number, number, number]
  salaId: string
  key: string
}

// pieza en coordenadas locales del mueble (origen = centro de la pieza en el piso)
interface ParteLocal {
  g: Grupo
  p: [number, number, number]
  e: [number, number, number]
}

const FY = 0.12 // altura del piso propio de la sala

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

// rotacion Y estandar de three: (x,z) -> (x cos + z sin, -x sin + z cos)
function rotXZ(x: number, z: number, rotY: number): [number, number] {
  const c = Math.cos(rotY)
  const s = Math.sin(rotY)
  return [x * c + z * s, -x * s + z * c]
}

// ── piezas (definidas mirando a +z; rotY las orienta contra la pared) ──────

function escritorio(anchoTapa: number, monitores: 1 | 2): ParteLocal[] {
  const p: ParteLocal[] = [
    { g: 'magenta', p: [0, FY + 0.6, 0], e: [anchoTapa, 0.08, 0.62] },
    { g: 'gris', p: [-(anchoTapa / 2 - 0.08), FY + 0.3, 0], e: [0.07, 0.52, 0.56] },
    { g: 'gris', p: [anchoTapa / 2 - 0.08, FY + 0.3, 0], e: [0.07, 0.52, 0.56] },
  ]
  const xs = monitores === 2 ? [-0.42, 0.42] : [0]
  for (const mx of xs) {
    p.push(
      { g: 'gris', p: [mx, FY + 0.69, -0.1], e: [0.1, 0.1, 0.09] }, // pie
      { g: 'gris', p: [mx, FY + 0.92, -0.12], e: [0.56, 0.36, 0.06] }, // cuerpo
      { g: 'pantalla', p: [mx, FY + 0.92, -0.085], e: [0.48, 0.28, 1] },
    )
  }
  // silla (base, pata, asiento, respaldo)
  p.push(
    { g: 'gris', p: [0, FY + 0.04, 0.62], e: [0.34, 0.05, 0.34] },
    { g: 'gris', p: [0, FY + 0.22, 0.62], e: [0.07, 0.34, 0.07] },
    { g: 'gris', p: [0, FY + 0.42, 0.62], e: [0.44, 0.07, 0.44] },
    { g: 'gris', p: [0, FY + 0.71, 0.83], e: [0.44, 0.52, 0.07] },
  )
  return p
}

function archivador(): ParteLocal[] {
  return [
    { g: 'lima', p: [0, FY + 0.53, 0], e: [0.55, 1.02, 0.6] },
    { g: 'blanco', p: [0, FY + 0.86, 0.31], e: [0.24, 0.05, 0.05] },
    { g: 'blanco', p: [0, FY + 0.56, 0.31], e: [0.24, 0.05, 0.05] },
    { g: 'blanco', p: [0, FY + 0.26, 0.31], e: [0.24, 0.05, 0.05] },
  ]
}

function planta(): ParteLocal[] {
  return [
    { g: 'maceta', p: [0, FY + 0.18, 0], e: [0.42, 0.36, 0.42] },
    { g: 'hojas', p: [0, FY + 0.6, 0], e: [0.6, 0.66, 0.6] },
    { g: 'hojas', p: [0.1, FY + 0.88, -0.06], e: [0.4, 0.44, 0.4] },
  ]
}

function pizarra(h: number): ParteLocal[] {
  const a = 0.5 + (h % 3) * 0.12 // largo del garabato: varia por sala
  return [
    { g: 'blanco', p: [0, FY + 1.32, 0], e: [1.5, 0.85, 0.06] },
    { g: 'gris', p: [0, FY + 0.86, 0.05], e: [1.05, 0.05, 0.1] }, // bandeja
    { g: 'magenta', p: [-0.25, FY + 1.5, 0.045], e: [a, 0.04, 0.012] },
    { g: 'gris', p: [-0.1, FY + 1.36, 0.045], e: [0.85, 0.04, 0.012] },
    { g: 'gris', p: [0.28, FY + 1.2, 0.045], e: [0.5, 0.04, 0.012] },
  ]
}

function estanteria(): ParteLocal[] {
  return [
    { g: 'blanco', p: [-0.62, FY + 0.78, 0], e: [0.07, 1.56, 0.5] },
    { g: 'blanco', p: [0.62, FY + 0.78, 0], e: [0.07, 1.56, 0.5] },
    { g: 'blanco', p: [0, FY + 0.08, 0], e: [1.3, 0.06, 0.5] },
    { g: 'blanco', p: [0, FY + 0.55, 0], e: [1.3, 0.06, 0.5] },
    { g: 'blanco', p: [0, FY + 1.02, 0], e: [1.3, 0.06, 0.5] },
    { g: 'blanco', p: [0, FY + 1.49, 0], e: [1.3, 0.06, 0.5] },
    { g: 'lima', p: [-0.3, FY + 0.72, 0], e: [0.4, 0.28, 0.34] }, // "libros"
    { g: 'magenta', p: [0.28, FY + 1.19, 0], e: [0.3, 0.28, 0.3] },
    { g: 'gris', p: [0.05, FY + 0.25, 0], e: [0.45, 0.26, 0.32] },
  ]
}

// ── layout por sala (deterministico via hash del id) ───────────────────────

/** Asiento (silla del escritorio principal) en coords de MUNDO + orientacion
 *  sentada mirando al monitor. Espeja el layout de piezasDeSala para que el
 *  Trabajador quede exactamente donde se dibuja la silla. */
export function asientoDeSala(sala: SalaMueblada): {
  pos: [number, number, number]
  rotY: number
} {
  const h = hash(sala.id)
  let cx = sala.ancho / 2
  let cz = 0.8
  if (sala.tamano === 'mediana') {
    if (h % 2 === 0) cx = sala.ancho * 0.3
    else cz = 0.85
  } else if (sala.tamano === 'grande') {
    cz = 2.1
  }
  // la silla vive en el local [0, +0.62] del escritorio (rotY=0, mirando -z)
  return {
    pos: [sala.posicion[0] + cx, FY, sala.posicion[1] + cz + 0.62],
    rotY: Math.PI,
  }
}

function piezasDeSala(sala: SalaMueblada): Parte[] {
  const [ox, oz] = sala.posicion
  const h = hash(sala.id)
  const partes: Parte[] = []

  const poner = (locales: ParteLocal[], cx: number, cz: number, rotY: number) => {
    for (const l of locales) {
      const [rx, rz] = rotXZ(l.p[0], l.p[2], rotY)
      partes.push({
        grupo: l.g,
        pos: [ox + cx + rx, l.p[1], oz + cz + rz],
        rotY,
        escala: l.e,
        salaId: sala.id,
        key: `${sala.id}:${partes.length}`,
      })
    }
  }

  if (sala.tamano === 'chica') {
    poner(escritorio(1.4, 1), sala.ancho / 2, 0.8, 0)
    poner(planta(), sala.ancho - 0.55, sala.prof - 0.55, 0)
  } else if (sala.tamano === 'mediana') {
    if (h % 2 === 0) {
      poner(escritorio(1.4, 1), sala.ancho * 0.3, 0.8, 0)
      poner(escritorio(1.4, 1), sala.ancho * 0.73, 0.8, 0)
    } else {
      poner(escritorio(1.7, (h >> 2) % 2 === 0 ? 1 : 2), sala.ancho / 2, 0.85, 0)
    }
    poner(archivador(), 0.48, sala.prof - 0.5, Math.PI / 2) // contra pared oeste
    poner(pizarra(h), 0.18, sala.prof * 0.45, Math.PI / 2) // colgada en pared oeste
    poner(planta(), sala.ancho - 0.5, sala.prof - 0.5, 0)
  } else {
    // grande: escritorio central doble + biblioteca; las pantallas de pared
    // de mega_jefe las dibuja Sala.tsx, no este modulo
    poner(escritorio(2.3, 2), sala.ancho / 2, 2.1, 0)
    poner(estanteria(), 0.5, sala.prof - 1.1, Math.PI / 2)
    poner(archivador(), sala.ancho * 0.72, 0.55, 0)
    poner(planta(), sala.ancho - 0.6, sala.prof - 0.6, 0)
    poner(planta(), 0.6, sala.prof - 0.6, 0)
  }
  return partes
}

// ── render instanciado + parpadeo de pantallas ─────────────────────────────

interface ObjColor {
  color: THREE.Color
}

interface PantallaViva {
  obj: ObjColor
  salaId: string
  fase: number
}

const PANTALLA_OFF = new THREE.Color('#27303f')
const PANTALLA_TENUE = new THREE.Color('#6a7420')
const PANTALLA_VIVA = new THREE.Color('#eeff9a')

function geometriaDe(g: Grupo) {
  if (g === 'maceta') return <cylinderGeometry args={[0.5, 0.4, 1, 7]} />
  if (g === 'hojas') return <icosahedronGeometry args={[0.5, 0]} />
  if (g === 'pantalla') return <planeGeometry />
  return <boxGeometry />
}

export function MobiliarioOficina({ salas }: MobiliarioOficinaProps) {
  const partes = useMemo(() => salas.flatMap((s) => piezasDeSala(s)), [salas])
  const porGrupo = useMemo(() => {
    const m = new Map<Grupo, Parte[]>()
    for (const p of partes) {
      const lista = m.get(p.grupo)
      if (lista) lista.push(p)
      else m.set(p.grupo, [p])
    }
    return m
  }, [partes])

  // set de salas trabajando en un ref: el callback-ref de las pantallas se
  // registra al montar, asi que el frame loop lee siempre el set fresco
  const trabajando = useMemo(
    () => new Set(salas.filter((s) => s.trabajando).map((s) => s.id)),
    [salas],
  )
  const trabajandoRef = useRef<ReadonlySet<string>>(trabajando)
  trabajandoRef.current = trabajando

  const pantallas = useRef(new Map<string, PantallaViva>())

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    for (const pv of pantallas.current.values()) {
      if (trabajandoRef.current.has(pv.salaId)) {
        const f = 0.5 + 0.5 * Math.sin(t * 6.3 + pv.fase)
        pv.obj.color.copy(PANTALLA_TENUE).lerp(PANTALLA_VIVA, f)
      } else {
        pv.obj.color.copy(PANTALLA_OFF)
      }
    }
  })

  return (
    <group>
      {ORDEN_GRUPOS.map((g) => {
        const lista = porGrupo.get(g)
        if (!lista || lista.length === 0) return null
        const esPantalla = g === 'pantalla'
        return (
          // key con el largo: si cambia la cantidad se recrea el buffer
          <Instances
            key={`${g}:${lista.length}`}
            limit={lista.length}
            castShadow={!esPantalla}
            receiveShadow={!esPantalla}
            frustumCulled={false}
          >
            {geometriaDe(g)}
            {esPantalla ? (
              <meshBasicMaterial toneMapped={false} side={THREE.DoubleSide} />
            ) : (
              <meshStandardMaterial
                color={COLOR_GRUPO[g]}
                roughness={0.92}
                flatShading={g === 'hojas'}
              />
            )}
            {lista.map((p) =>
              esPantalla ? (
                <Instance
                  key={p.key}
                  position={p.pos}
                  rotation={[0, p.rotY, 0]}
                  scale={p.escala}
                  color={COLOR_GRUPO.pantalla}
                  ref={(o: unknown) => {
                    if (o)
                      pantallas.current.set(p.key, {
                        obj: o as ObjColor,
                        salaId: p.salaId,
                        fase: (hash(p.key) % 628) / 100,
                      })
                    else pantallas.current.delete(p.key)
                  }}
                />
              ) : (
                <Instance
                  key={p.key}
                  position={p.pos}
                  rotation={[0, p.rotY, 0]}
                  scale={p.escala}
                />
              ),
            )}
          </Instances>
        )
      })}
    </group>
  )
}
