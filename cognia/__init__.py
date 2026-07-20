# Antes de nada: stdout UTF-8. Si no, cualquier print con emoji mata el
# proceso en Windows cuando la salida esta redirigida (ver cognia/consola.py).
from .consola import forzar_utf8

forzar_utf8()

from .cognia import Cognia
