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
}


@dataclass
class Obj:
    """Un objeto de la escena: identidad, forma, posición (centro, 0..1),
    tamaño (fracción del canvas), material/color, y relación con otro objeto
    ('on'/'sobre' → se apila encima; 'left_of'/'right_of'/'above'/'below')."""
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
        for o in self.objects:
            if o.name == name:
                return o
        return None

    def edit(self, name: str, **changes) -> bool:
        """Edición SELECTIVA (§8.2): cambia atributos de UN objeto sin tocar el
        resto ni regenerar la escena. Devuelve True si el objeto existe.
        color como str se resuelve a RGB. Es O(1) — el diferenciador de LCD."""
        o = self.get(name)
        if o is None:
            return False
        for k, v in changes.items():
            if k == "color" and isinstance(v, str):
                v = COLORS.get(v.lower(), o.color)
            setattr(o, k, v)
        return True

    def to_json(self) -> str:
        d = {"width": self.width, "height": self.height,
             "background": list(self.background), "light_dir": list(self.light_dir),
             "objects": [asdict(o) for o in self.objects]}
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Scene":
        d = json.loads(text)
        objs = []
        for od in d.get("objects", []):
            od = dict(od)
            od["color"] = tuple(od.get("color", (150, 150, 150)))
            objs.append(Obj(**od))
        return cls(objects=objs, width=d.get("width", 512),
                   height=d.get("height", 512),
                   background=tuple(d.get("background", (235, 238, 245))),
                   light_dir=tuple(d.get("light_dir", (-0.5, -0.8))))
