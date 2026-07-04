"""
cognia_x/lcd/scene.py — Representación de escena ESTRUCTURADA (LCD, paper §5).

El núcleo de LCD+MOM: en vez de píxeles, el sistema mantiene una escena
estructurada (objetos con posición/tamaño/material + relaciones; cámara y luz
como entidades de primera clase). Es lo que habilita (a) control composicional
exacto por construcción (§8.1) y (b) edición selectiva sin regenerar la escena
(§8.2) — la propiedad que más diferencia LCD de un modelo de difusión
monolítico, cuyo espacio latente no tiene puntos de edición por-objeto.

Concreto: dataclasses planas + JSON. Sin dependencias.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict


# Colores nombrados -> RGB (paleta simple, ampliable).
COLORS = {
    "red": (220, 60, 50), "rojo": (220, 60, 50),
    "blue": (60, 110, 220), "azul": (60, 110, 220),
    "green": (70, 180, 90), "verde": (70, 180, 90),
    "yellow": (240, 210, 70), "amarillo": (240, 210, 70),
    "brown": (150, 100, 60), "marron": (150, 100, 60), "cafe": (150, 100, 60),
    "white": (240, 240, 240), "blanco": (240, 240, 240),
    "black": (40, 40, 40), "negro": (40, 40, 40),
    "gray": (150, 150, 150), "gris": (150, 150, 150),
    "orange": (240, 150, 60), "naranja": (240, 150, 60),
    "purple": (160, 90, 200), "violeta": (160, 90, 200),
    "pink": (240, 150, 190), "rosa": (240, 150, 190),
}

# Objeto -> forma primitiva + tamaño por defecto (fracción del canvas).
# density (masa por area) para la fisica: bajo=liviano (flota poco, se apila
# encima), alto=pesado (base estable). Default 1.0 si no se lista.
SHAPES = {
    "table": ("rect", 0.55, 0.12), "mesa": ("rect", 0.55, 0.12),
    "cup": ("ellipse", 0.10, 0.12), "taza": ("ellipse", 0.10, 0.12),
    "ball": ("circle", 0.12, 0.12), "pelota": ("circle", 0.12, 0.12),
    "box": ("rect", 0.16, 0.16), "caja": ("rect", 0.16, 0.16),
    "plate": ("ellipse", 0.18, 0.05), "plato": ("ellipse", 0.18, 0.05),
    "book": ("rect", 0.12, 0.16), "libro": ("rect", 0.12, 0.16),
    "sun": ("circle", 0.16, 0.16), "sol": ("circle", 0.16, 0.16),
    "tree": ("triangle", 0.20, 0.30), "arbol": ("triangle", 0.20, 0.30),
    "house": ("rect", 0.28, 0.24), "casa": ("rect", 0.28, 0.24),
    "lamp": ("rect", 0.06, 0.20), "lampara": ("rect", 0.06, 0.20),
    "chair": ("rect", 0.14, 0.22), "silla": ("rect", 0.14, 0.22),
    # ampliacion (mas objetos = mas expresividad para la IA)
    "bottle": ("rect", 0.07, 0.20), "botella": ("rect", 0.07, 0.20),
    "glass": ("rect", 0.07, 0.13), "vaso": ("rect", 0.07, 0.13),
    "phone": ("rect", 0.07, 0.14), "telefono": ("rect", 0.07, 0.14),
    "laptop": ("rect", 0.22, 0.14), "notebook": ("rect", 0.22, 0.14),
    "clock": ("circle", 0.13, 0.13), "reloj": ("circle", 0.13, 0.13),
    "apple": ("circle", 0.09, 0.09), "manzana": ("circle", 0.09, 0.09),
    "flower": ("circle", 0.10, 0.10), "flor": ("circle", 0.10, 0.10),
    "star": ("triangle", 0.12, 0.12), "estrella": ("triangle", 0.12, 0.12),
    "cloud": ("ellipse", 0.24, 0.10), "nube": ("ellipse", 0.24, 0.10),
    "moon": ("circle", 0.12, 0.12), "luna": ("circle", 0.12, 0.12),
    "car": ("rect", 0.26, 0.12), "auto": ("rect", 0.26, 0.12), "coche": ("rect", 0.26, 0.12),
    "cat": ("ellipse", 0.16, 0.12), "gato": ("ellipse", 0.16, 0.12),
    "dog": ("ellipse", 0.18, 0.13), "perro": ("ellipse", 0.18, 0.13),
    "bird": ("triangle", 0.10, 0.08), "pajaro": ("triangle", 0.10, 0.08),
    "window": ("rect", 0.18, 0.22), "ventana": ("rect", 0.18, 0.22),
    "door": ("rect", 0.12, 0.30), "puerta": ("rect", 0.12, 0.30),
    "bowl": ("ellipse", 0.16, 0.09), "bol": ("ellipse", 0.16, 0.09), "tazon": ("ellipse", 0.16, 0.09),
    "shelf": ("rect", 0.40, 0.04), "estante": ("rect", 0.40, 0.04), "repisa": ("rect", 0.40, 0.04),
    "rug": ("rect", 0.45, 0.05), "alfombra": ("rect", 0.45, 0.05),
    "pencil": ("rect", 0.62, 0.09), "lapiz": ("rect", 0.62, 0.09),
    "pen": ("rect", 0.55, 0.07), "lapicera": ("rect", 0.55, 0.07), "boligrafo": ("rect", 0.55, 0.07),
}

# density (masa por unidad de area) por objeto, para la fisica. Los soportes
# (mesa/estante/suelo) son pesados/estables; lo que se apoia arriba, liviano.
DENSITY = {
    "table": 3.0, "mesa": 3.0, "shelf": 3.0, "estante": 3.0, "repisa": 3.0,
    "house": 4.0, "casa": 4.0, "car": 3.0, "auto": 3.0, "coche": 3.0,
    "rug": 5.0, "alfombra": 5.0, "door": 3.0, "puerta": 3.0,
    "cup": 0.6, "taza": 0.6, "glass": 0.6, "vaso": 0.6, "bottle": 0.7, "botella": 0.7,
    "apple": 0.8, "manzana": 0.8, "ball": 0.5, "pelota": 0.5,
    "cloud": 0.05, "nube": 0.05, "sun": 0.05, "sol": 0.05, "moon": 0.05, "luna": 0.05,
    "star": 0.05, "estrella": 0.05, "bird": 0.1, "pajaro": 0.1, "flower": 0.3, "flor": 0.3,
}

# Objetos que "flotan" (no les aplica gravedad): cielo/decorativos.
FLOATING = {"sun", "sol", "moon", "luna", "star", "estrella", "cloud", "nube",
            "bird", "pajaro"}

# Materiales nombrados (afectan el sombreado del render + son editables).
MATERIALS = {"madera", "wood", "metal", "vidrio", "glass", "plastico", "plastic",
             "tela", "fabric", "piedra", "stone", "agua", "water"}

# Sinonimos es<->en: dos nombres son el MISMO tipo de objeto. Se usa para la
# similitud de escenas (que 'mesa' y 'table' no cuenten como objetos distintos
# cuando el modelo traduce) y para cualquier match por tipo. Canonical = la
# forma en ingles (la 1a de cada par en SHAPES).
_SYNONYM_PAIRS = [
    ("table", "mesa"), ("cup", "taza"), ("ball", "pelota"), ("box", "caja"),
    ("plate", "plato"), ("book", "libro"), ("sun", "sol"), ("tree", "arbol"),
    ("house", "casa"), ("lamp", "lampara"), ("chair", "silla"),
    ("bottle", "botella"), ("glass", "vaso"), ("phone", "telefono"),
    ("laptop", "notebook"), ("clock", "reloj"), ("apple", "manzana"),
    ("flower", "flor"), ("star", "estrella"), ("cloud", "nube"), ("moon", "luna"),
    ("car", "auto"), ("car", "coche"), ("cat", "gato"), ("dog", "perro"),
    ("bird", "pajaro"), ("window", "ventana"), ("door", "puerta"),
    ("bowl", "bol"), ("bowl", "tazon"), ("shelf", "estante"), ("shelf", "repisa"),
    ("rug", "alfombra"), ("pencil", "lapiz"), ("pen", "lapicera"), ("pen", "boligrafo"),
]
_CANON = {}
for _canonical, _alias in _SYNONYM_PAIRS:
    _CANON[_canonical] = _canonical
    _CANON[_alias] = _canonical


def canonical_name(name: str) -> str:
    """Nombre canonico de un objeto (colapsa sinonimos es/en a una sola forma).
    'mesa' y 'table' -> 'table'. Nombres desconocidos se devuelven tal cual
    (minusculas), para que dos 'dragon' sigan matcheando entre si."""
    base = (name or "").lower().strip()
    # sacar sufijo de desambiguacion (cup_2 -> cup) para comparar por tipo
    import re as _re
    base = _re.sub(r"_\d+$", "", base)
    return _CANON.get(base, base)


@dataclass
class Obj:
    """Un objeto de la escena: identidad, forma, posición (centro, 0..1),
    tamaño (fracción del canvas), material/color, rotación, y relación con otro
    objeto ('on'/'sobre' → se apila encima; 'left_of'/'right_of'/'above'/'below').

    id: identidad única (permite dos 'cup'); name conserva el tipo/etiqueta.
    rotation: grados (render y física simple lo usan). material: nombre editable."""
    name: str
    shape: str                    # rect | ellipse | circle | triangle
    x: float                      # centro x en [0,1]
    y: float                      # centro y en [0,1] (0=arriba, 1=abajo)
    w: float
    h: float
    color: tuple = (150, 150, 150)
    z: int = 0                    # orden de dibujo (mayor = encima)
    relation: str = ""            # relacion pedida (para el eval de control)
    ref: str = ""                 # objeto de referencia de la relacion
    rotation: float = 0.0         # grados (0 = sin rotar)
    material: str = ""            # madera/metal/vidrio/... (editable)
    id: str = ""                  # identidad unica; si vacia, se usa name
    points: list = None           # vertices custom (shape='polygon'): [[x,y],...]
                                  # en coords LOCALES del objeto [-0.5,0.5] (0=centro)

    def key(self) -> str:
        return self.id or self.name

    # --- geometria util (para fisica y colision) ---
    def bbox(self) -> tuple:
        """(x0, y0, x1, y1) en [0,1], caja alineada a ejes (ignora rotacion)."""
        return (self.x - self.w / 2, self.y - self.h / 2,
                self.x + self.w / 2, self.y + self.h / 2)

    def top(self) -> float:
        return self.y - self.h / 2

    def bottom(self) -> float:
        return self.y + self.h / 2


@dataclass
class Scene:
    """Escena estructurada completa. width/height en px del render aproximado;
    background y una luz simple (dirección) como entidad de primera clase."""
    objects: list = field(default_factory=list)
    width: int = 512
    height: int = 512
    background: tuple = (235, 238, 245)
    light_dir: tuple = (-0.5, -0.8)   # de arriba-izquierda (sombras)

    def get(self, name: str):
        """Objeto por id o por name (id gana). Devuelve el primero que matchea."""
        for o in self.objects:
            if o.id == name:
                return o
        for o in self.objects:
            if o.name == name:
                return o
        return None

    def edit(self, name: str, **changes) -> bool:
        """Edición SELECTIVA (§8.2): cambia atributos de UN objeto sin tocar el
        resto ni regenerar la escena. Devuelve True si el objeto existe.
        color/material como str se resuelven. Es O(1) — el diferenciador de LCD."""
        o = self.get(name)
        if o is None:
            return False
        for k, v in changes.items():
            if k == "color" and isinstance(v, str):
                v = COLORS.get(v.lower(), o.color)
            setattr(o, k, v)
        return True

    # --- edición estructural (edición TOTAL: agregar/quitar/duplicar) ---
    def add(self, obj: "Obj") -> "Obj":
        """Agrega un objeto; si su key ya existe, lo desambigua con un sufijo."""
        keys = {o.key() for o in self.objects}
        if obj.key() in keys:
            base, i = obj.name, 2
            while f"{base}_{i}" in keys:
                i += 1
            obj.id = f"{base}_{i}"
        self.objects.append(obj)
        return obj

    def remove(self, name: str) -> bool:
        o = self.get(name)
        if o is None:
            return False
        self.objects.remove(o)
        return True

    def duplicate(self, name: str, dx: float = 0.08, dy: float = 0.0):
        """Copia un objeto desplazado; devuelve la copia (o None)."""
        import copy
        o = self.get(name)
        if o is None:
            return None
        c = copy.deepcopy(o)
        c.id = ""                       # add() le asigna una key unica
        c.x = min(1.0, max(0.0, o.x + dx))
        c.y = min(1.0, max(0.0, o.y + dy))
        c.z = max((oo.z for oo in self.objects), default=0) + 1
        return self.add(c)

    def to_json(self) -> str:
        d = {"width": self.width, "height": self.height,
             "background": list(self.background), "light_dir": list(self.light_dir),
             "objects": [asdict(o) for o in self.objects]}
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Scene":
        d = json.loads(text)
        objs = []
        # solo los campos que Obj conoce (compat: escenas viejas sin rotation/
        # material/id no rompen; campos extra se ignoran).
        _fields = {"name", "shape", "x", "y", "w", "h", "color", "z",
                   "relation", "ref", "rotation", "material", "id", "points"}
        for od in d.get("objects", []):
            od = {k: v for k, v in dict(od).items() if k in _fields}
            od["color"] = tuple(od.get("color", (150, 150, 150)))
            objs.append(Obj(**od))
        return cls(objects=objs, width=d.get("width", 512),
                   height=d.get("height", 512),
                   background=tuple(d.get("background", (235, 238, 245))),
                   light_dir=tuple(d.get("light_dir", (-0.5, -0.8))))
