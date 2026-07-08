// Derivaciones del snapshot -> modelo de escena (MAPEO VISUAL del contrato).
// Sin fetch, sin three: solo datos. Se chequea via tsc en el build.
// Única pieza con estado: el mapa module-level tid->slot de las salas
// dinámicas (para que cada sala conserve su posición mientras viva).
import type { EstadoTarea, Snapshot, Tarea } from '../state/tipos'

// ── salas ──────────────────────────────────────────────────────────────────

export type TipoSala = 'fija' | 'director' | 'trabajador'
export type EstadoTrabajador = 'trabajando' | 'esperando' | 'fallo' | 'hecho'

export interface Sala {
  id: string // id fijo ('mega_jefe', 'planner', ...) o tid para dinamicas
  tipo: TipoSala
  nombre: string
  tamano: [number, number] // [ancho, profundidad] en celdas del grid
  posicion: [number, number] // esquina [x, z] en el grid isometrico
  /** null en salas de modulo sin tarea propia; su animacion la da actividadModulos */
  trabajador: { estado: EstadoTrabajador } | null
  /** tid de la tarea asociada (dinamicas y 'jefe'); null en salas de modulo */
  tid: string | null
}

// Layout deterministico de las salas fijas: bloques en L alrededor del patio.
// mega_jefe grande al noroeste; el ala este (x >= ALA_ESTE_X) queda libre
// para las salas dinamicas.
const SALAS_FIJAS: ReadonlyArray<{
  id: string
  nombre: string
  tamano: [number, number]
  posicion: [number, number]
}> = [
  { id: 'mega_jefe', nombre: 'Mega Jefe', tamano: [6, 6], posicion: [0, 0] },
  { id: 'jefe', nombre: 'Jefe', tamano: [4, 4], posicion: [7, 0] },
  { id: 'planner', nombre: 'Planner', tamano: [4, 4], posicion: [12, 0] },
  { id: 'scheduler', nombre: 'Scheduler', tamano: [4, 4], posicion: [17, 0] },
  { id: 'razonamiento', nombre: 'Razonamiento', tamano: [4, 4], posicion: [7, 5] },
  { id: 'generacion', nombre: 'Generación', tamano: [4, 4], posicion: [12, 5] },
  { id: 'herramientas', nombre: 'Herramientas', tamano: [4, 4], posicion: [17, 5] },
  { id: 'memoria_episodica', nombre: 'Memoria Episódica', tamano: [4, 4], posicion: [0, 10] },
  { id: 'memoria_semantica', nombre: 'Memoria Semántica', tamano: [4, 4], posicion: [5, 10] },
  { id: 'working_memory', nombre: 'Working Memory', tamano: [4, 4], posicion: [10, 10] },
  { id: 'knowledge_graph', nombre: 'Knowledge Graph', tamano: [4, 4], posicion: [15, 10] },
]

const ALA_ESTE_X = 23 // desde aca crecen las salas dinamicas
const COLS_ALA = 3 // slots por fila en el ala este
const PASO_ALA = 5 // celdas entre slots (sala 4x3 + pasillo)

// El piso de Oficina3D.tsx es FIJO (42x22 => grid logico x en [-2,40], z en
// [-2,20]): ningun slot puede caer fuera de el. Capacidad:
// - slots 0..14: ala este, 3 columnas x 5 filas (x=23/28/33, z=0/4/8/12/16)
// - slots 15..19: franja sur libre (z=16, debajo de las salas fijas que
//   terminan en z=14) creciendo hacia el OESTE (x=18,13,8,3,-2)
// - >20 salas activas a la vez: se reusa el grid (modulo) — se superponen
//   dentro del piso en vez de flotar fuera de la oficina (caso extremo).
const FILAS_ALA = 5
const SLOTS_ALA = COLS_ALA * FILAS_ALA // 15
const SLOTS_OESTE = 5 // la ultima columna (x=-2) toca justo el borde oeste
const TOTAL_SLOTS = SLOTS_ALA + SLOTS_OESTE // 20

function posicionDeSlot(slot: number): [number, number] {
  const s = slot % TOTAL_SLOTS
  if (s < SLOTS_ALA) {
    const col = s % COLS_ALA
    const fila = Math.floor(s / COLS_ALA)
    return [ALA_ESTE_X + col * PASO_ALA, fila * (PASO_ALA - 1)]
  }
  const k = s - SLOTS_ALA // franja sur: misma z que la ultima fila del ala
  return [ALA_ESTE_X - (k + 1) * PASO_ALA, (FILAS_ALA - 1) * (PASO_ALA - 1)]
}

// INVARIANTE de slots: cada sala dinamica VISIBLE (tarea activa) tiene un
// slot estable mientras viva (aunque otras aparezcan o desaparezcan); al
// desaparecer del snapshot su slot se LIBERA y lo recicla la proxima sala
// nueva (menor slot libre). Los slots ocupados == salas visibles: NO crecen
// con el historial de tareas hechas/fallidas/detenidas.
// Mini-test mental: orden=[A,B,C] activas -> A:0 B:1 C:2; termina B -> B se
// libera (A:0 C:2); nace D -> recicla el 1 (A:0 D:1 C:2); con 30 hechas y 2
// activas solo hay 2 slots ocupados (antes: slot 30+ => fuera del piso).
const slotsAsignados = new Map<string, number>() // tid -> slot (persiste entre derivaciones)

function asignarSlots(visibles: ReadonlyArray<string>): Map<string, number> {
  const vivos = new Set(visibles)
  for (const tid of slotsAsignados.keys()) {
    if (!vivos.has(tid)) slotsAsignados.delete(tid) // libero salas que ya no estan
  }
  const ocupados = new Set(slotsAsignados.values())
  for (const tid of visibles) {
    if (slotsAsignados.has(tid)) continue // estabilidad: conserva su slot
    let s = 0
    while (ocupados.has(s)) s++ // menor slot libre (recicla)
    slotsAsignados.set(tid, s)
    ocupados.add(s)
  }
  if (import.meta.env.DEV && slotsAsignados.size !== visibles.length) {
    console.error('derivar.ts: invariante de slots roto', { slotsAsignados, visibles })
  }
  return slotsAsignados
}

const ACTIVAS: ReadonlyArray<EstadoTarea> = ['pendiente', 'en_curso', 'pausada']

export function estadoTrabajador(estado: EstadoTarea): EstadoTrabajador {
  if (estado === 'en_curso') return 'trabajando'
  if (estado === 'hecha') return 'hecho'
  if (estado === 'fallida' || estado === 'detenida') return 'fallo'
  return 'esperando' // pendiente | pausada
}

/** Sala que representa a una tarea: el jefe vive en la sala fija 'jefe';
 *  directores y trabajadores tienen sala dinamica propia (id = tid). */
export function salaDeTarea(tid: string, snap: Snapshot): string {
  const t = snap.tareas[tid]
  return t && t.nivel === 'jefe' ? 'jefe' : tid
}

export function derivarSalas(snap: Snapshot): Sala[] {
  const jefeActivo = snap.orden
    .map((tid) => snap.tareas[tid])
    .filter((t): t is Tarea => t !== undefined)
    .filter((t) => t.nivel === 'jefe')
    .at(-1) // la corrida actual: ultimo jefe creado

  const salas: Sala[] = SALAS_FIJAS.map((f) => ({
    ...f,
    tipo: 'fija',
    trabajador:
      f.id === 'jefe' && jefeActivo
        ? { estado: estadoTrabajador(jefeActivo.estado) }
        : null,
    tid: f.id === 'jefe' && jefeActivo ? jefeActivo.id : null,
  }))

  // Dinamicas: una por director/trabajador ACTIVO. Los slots se asignan SOLO
  // a las salas visibles (reciclando los libres via asignarSlots): posicion
  // estable mientras la sala viva, sin crecer con el historial de terminadas.
  const visibles = snap.orden.filter((tid) => {
    const t = snap.tareas[tid]
    return t !== undefined && t.nivel !== 'jefe' && ACTIVAS.includes(t.estado)
  })
  const slots = asignarSlots(visibles)
  for (const tid of visibles) {
    const t = snap.tareas[tid]
    salas.push({
      id: tid,
      tipo: t.nivel === 'director' ? 'director' : 'trabajador',
      nombre: t.titulo,
      tamano: t.nivel === 'director' ? [4, 3] : [3, 3],
      posicion: posicionDeSlot(slots.get(tid) ?? 0),
      trabajador: { estado: estadoTrabajador(t.estado) },
      tid,
    })
  }
  return salas
}

// ── actividad de modulos (regex sobre eventos de tareas en curso) ──────────

export interface ActividadModulo {
  sala: string // sala fija iluminada
  tid: string // tarea cuyo evento la disparo
  msg: string
  t: string // "HH:MM:SS" del evento (para iluminar ~4s: ver msDesde)
  key: string // estable: `${tid}:${indice del evento}`
}

// Orden = prioridad: un evento ilumina UNA sala (el primer patron que matchea).
const PATRONES_MODULO: ReadonlyArray<[RegExp, string]> = [
  [/kg_agregar|kg_buscar/i, 'knowledge_graph'],
  [/anotar|notas/i, 'working_memory'],
  [/recordar|memorizar/i, 'memoria_episodica'],
  [/planificando/i, 'planner'],
  [/ACCION:\s*(escribir_archivo|leer_archivo|ejecutar|\w+)/, 'herramientas'],
  [/RESULTADO/, 'generacion'],
]

export function derivarActividad(snap: Snapshot): ActividadModulo[] {
  const acts: ActividadModulo[] = []
  for (const tid of snap.orden) {
    const t = snap.tareas[tid]
    if (!t || t.estado !== 'en_curso') continue
    t.eventos.forEach((ev, i) => {
      for (const [re, sala] of PATRONES_MODULO) {
        if (re.test(ev.msg)) {
          acts.push({ sala, tid, msg: ev.msg, t: ev.t, key: `${tid}:${i}` })
          break
        }
      }
    })
  }
  return acts
}

/** ms transcurridos desde un "HH:MM:SS" (misma jornada; maneja el cruce de
 *  medianoche asumiendo que el evento nunca es futuro). Para `< 4000` = iluminar. */
export function msDesde(hms: string, ahora: Date = new Date()): number {
  const p = hms.split(':').map(Number)
  if (p.length !== 3 || p.some(Number.isNaN)) return Number.POSITIVE_INFINITY
  const [h, m, s] = p
  const msEvento = (h * 3600 + m * 60 + s) * 1000
  const msAhora =
    (ahora.getHours() * 3600 + ahora.getMinutes() * 60 + ahora.getSeconds()) * 1000 +
    ahora.getMilliseconds()
  const d = msAhora - msEvento
  return d >= 0 ? d : d + 24 * 3600 * 1000
}

// ── paquetes (transiciones entre snapshots) ────────────────────────────────

export interface Paquete {
  id: string // estable: 'crea:<tid>' | 'hecha:<tid>'
  de: string // id de sala origen
  a: string // id de sala destino
}

/** Compara dos snapshots: subtarea nueva => paquete padre->hija;
 *  tarea que paso a hecha => paquete hija->padre. */
export function derivarPaquetes(prev: Snapshot | null, actual: Snapshot): Paquete[] {
  if (!prev) return []
  const paquetes: Paquete[] = []
  for (const tid of actual.orden) {
    const t = actual.tareas[tid]
    if (!t || !t.padre) continue
    const antes = prev.tareas[tid]
    if (!antes) {
      paquetes.push({
        id: `crea:${tid}`,
        de: salaDeTarea(t.padre, actual),
        a: salaDeTarea(tid, actual),
      })
    } else if (antes.estado !== 'hecha' && t.estado === 'hecha') {
      paquetes.push({
        id: `hecha:${tid}`,
        de: salaDeTarea(tid, actual),
        a: salaDeTarea(t.padre, actual),
      })
    }
  }
  return paquetes
}

// ── colas (pantallas del mega_jefe) ────────────────────────────────────────

export interface Colas {
  pendientes: number
  enCurso: number
  pausadas: number
  hechas: number
  fallidas: number
}

export function contarColas(snap: Snapshot): Colas {
  const c: Colas = { pendientes: 0, enCurso: 0, pausadas: 0, hechas: 0, fallidas: 0 }
  for (const tid of snap.orden) {
    const t = snap.tareas[tid]
    if (!t) continue
    if (t.estado === 'pendiente') c.pendientes++
    else if (t.estado === 'en_curso') c.enCurso++
    else if (t.estado === 'pausada') c.pausadas++
    else if (t.estado === 'hecha') c.hechas++
    else if (t.estado === 'fallida' || t.estado === 'detenida') c.fallidas++
  }
  return c
}

// ── escena completa ────────────────────────────────────────────────────────

export interface Escena {
  salas: Sala[]
  actividades: ActividadModulo[]
  paquetes: Paquete[]
  colas: Colas
}

export function derivarEscena(actual: Snapshot, prev: Snapshot | null): Escena {
  return {
    salas: derivarSalas(actual),
    actividades: derivarActividad(actual),
    paquetes: derivarPaquetes(prev, actual),
    colas: contarColas(actual),
  }
}
