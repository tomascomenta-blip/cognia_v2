"""
cognia/lcd/templates.py — plantillas de escena reusables (LCD).

Una plantilla es una funcion que arma una Scene con Obj concretos (sin pasar
por el planner de lenguaje natural): sirve para arrancar de un tiro una escena
compuesta (mesa servida, sala, ...) que el agente despues puede editar
selectivamente (escena_editar, §8.2). Posiciones fijas y deterministas, en el
mismo estilo que planner.py (soportes calculados a mano via top()/bottom(),
sin invocar el motor de fisica -- objetos como 'ventana' son de pared, no de
piso, y physics.settle() los haria caer al suelo por no tener ese concepto).
"""
from __future__ import annotations

from cognia.lcd.scene import COLORS, SHAPES, Obj, Scene


def _obj(name: str, x: float, y: float, color: str = "gris", z: int = 0) -> Obj:
    """Un Obj con la forma/tamaño default de SHAPES (mismo mapeo que planner.py
    y scene.py). Color por nombre (se resuelve via COLORS; gris si no matchea)."""
    shape, w, h = SHAPES.get(name, ("rect", 0.15, 0.15))
    return Obj(name=name, shape=shape, x=x, y=y, w=w, h=h,
               color=COLORS.get(color.lower(), COLORS["gris"]), z=z)


def _on_top(base: Obj, name: str, x: float, color: str, z: int) -> Obj:
    """Un objeto `name` apoyado sobre el borde superior de `base` (su borde
    inferior == el top() del soporte) -- misma convencion que usa plan() en
    planner.py para la relacion 'on'."""
    shape, w, h = SHAPES.get(name, ("rect", 0.15, 0.15))
    y = base.top() - h / 2
    return Obj(name=name, shape=shape, x=x, y=y, w=w, h=h,
               color=COLORS.get(color.lower(), COLORS["gris"]), z=z)


def _mesa_servida() -> Scene:
    """Mesa con plato, taza y libro apoyados encima."""
    s = Scene()
    mesa = s.add(_obj("mesa", 0.5, 0.75, "marron", z=0))
    s.add(_on_top(mesa, "plato", 0.35, "blanco", z=1))
    s.add(_on_top(mesa, "taza", 0.52, "blanco", z=1))
    s.add(_on_top(mesa, "libro", 0.70, "rojo", z=1))
    return s


def _cielo() -> Scene:
    """Sol + nube + pajaro (todos 'flotantes': no les aplica la gravedad de
    physics.py, asi que sus posiciones no dependen de ningun soporte)."""
    s = Scene()
    s.add(_obj("sol", 0.80, 0.15, "amarillo", z=0))
    s.add(_obj("nube", 0.30, 0.20, "blanco", z=1))
    s.add(_obj("pajaro", 0.55, 0.35, "negro", z=2))
    return s


def _sala() -> Scene:
    """Mesa + silla (piso) + lampara (piso) + ventana (pared, no descansa en
    el piso: y bajo = arriba en la convencion de la escena)."""
    s = Scene()
    s.add(_obj("mesa", 0.40, 0.80, "marron", z=0))
    s.add(_obj("silla", 0.85, 0.78, "marron", z=0))
    s.add(_obj("lampara", 0.06, 0.75, "amarillo", z=0))
    s.add(_obj("ventana", 0.55, 0.25, "azul", z=0))
    return s


def _escritorio() -> Scene:
    """Mesa (escritorio) con laptop y taza apoyados encima."""
    s = Scene()
    mesa = s.add(_obj("mesa", 0.5, 0.78, "marron", z=0))
    s.add(_on_top(mesa, "laptop", 0.38, "gris", z=1))
    s.add(_on_top(mesa, "taza", 0.68, "blanco", z=1))
    return s


def _naturaleza() -> Scene:
    """Dos arboles en el piso + sol y nube en el cielo."""
    s = Scene()
    s.add(_obj("arbol", 0.20, 0.75, "verde", z=0))
    s.add(_obj("arbol", 0.38, 0.75, "verde", z=0))
    s.add(_obj("sol", 0.80, 0.15, "amarillo", z=1))
    s.add(_obj("nube", 0.60, 0.20, "blanco", z=1))
    return s


def _pila_cajas() -> Scene:
    """3-4 cajas apiladas: cada una apoyada sobre el borde superior de la de
    abajo (misma x; soporte calculado a mano via top(), sin motor de fisica)."""
    s = Scene()
    base = s.add(_obj("caja", 0.5, 0.82, "marron", z=0))
    c2 = s.add(_on_top(base, "caja", 0.5, "azul", z=1))
    c3 = s.add(_on_top(c2, "caja", 0.5, "rojo", z=2))
    s.add(_on_top(c3, "caja", 0.5, "verde", z=3))
    return s


TEMPLATES = {
    "mesa_servida": _mesa_servida,
    "cielo": _cielo,
    "sala": _sala,
    "escritorio": _escritorio,
    "naturaleza": _naturaleza,
    "pila_cajas": _pila_cajas,
}


def get_template(nombre: str) -> Scene | None:
    """Instancia la plantilla `nombre` (una Scene NUEVA en cada llamada, para
    que dos tareas no compartan estado). None si `nombre` no existe."""
    fn = TEMPLATES.get((nombre or "").strip().lower())
    return fn() if fn else None


def list_templates() -> list:
    return sorted(TEMPLATES.keys())
