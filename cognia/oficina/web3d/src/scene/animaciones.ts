// Helpers PUROS de animacion procedural (sin three, sin react, sin estado):
// easing, osciladores y amortiguacion compartidos por Trabajador y Paquete.
// Todo es funcion de (tiempo, params) -> numero: cero allocs, seguro en useFrame.

export function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x
}

/** Easing suave entrada/salida (cubica). */
export function easeInOutCubic(t: number): number {
  t = clamp01(t)
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

/** Easing con sobrepaso leve al final (para el brazo del festejo "hecho"). */
export function easeOutBack(t: number): number {
  t = clamp01(t)
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2)
}

/** Oscilador senoidal: valor en [-amp, amp] a `hz` ciclos por segundo. */
export function oscilar(tiempo: number, hz: number, amp = 1, fase = 0): number {
  return Math.sin(tiempo * hz * Math.PI * 2 + fase) * amp
}

/** Pulso periodico en [0,1]: vale 0 casi todo el periodo y sube 0->1->0
 *  durante la fraccion `ancho` inicial. Para gestos ocasionales (cabeceo). */
export function pulso(tiempo: number, periodoS: number, ancho = 0.15): number {
  const f = ((tiempo % periodoS) + periodoS) % periodoS / periodoS
  if (f >= ancho) return 0
  return Math.sin((f / ancho) * Math.PI)
}

/** Aproximacion exponencial frame-rate-independiente (spring critico simple):
 *  acerca `actual` a `objetivo`; `vel` mas grande = converge mas rapido. */
export function amortiguar(actual: number, objetivo: number, vel: number, dt: number): number {
  return objetivo + (actual - objetivo) * Math.exp(-vel * dt)
}
