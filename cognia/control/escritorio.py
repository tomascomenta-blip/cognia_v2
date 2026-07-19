"""
cognia/control/escritorio.py
============================
Manos de Cognia sobre el escritorio de Windows, via UI Automation
(planes/JARVIS_COGNIA.md 4.2, capa 2).

POR QUE ACCESIBILIDAD Y NO VISION. Para "abrime esta pestaña" el estado del arte
de moda (UI-TARS, OmniParser) mira pixeles con un modelo de 7B: tarda segundos
por accion, ocupa la VRAM que ya tiene el modelo de lenguaje y falla de formas
impredecibles. Windows ya publica el arbol de accesibilidad: dice que ventanas,
pestañas y botones existen, con su nombre y sus coordenadas, de forma
determinista y en milisegundos. La vision se reserva para DESCRIBIR lo que no
esta en el arbol, no para accionar.

POR QUE ESTO Y NO PLAYWRIGHT. Playwright solo maneja navegadores, y ademas el
suyo propio, no el Chrome que el dueño ya tiene abierto con sus sesiones. UI
Automation funciona sobre CUALQUIER ventana —Chrome, Word, VS Code, el
Explorador, Configuracion— sin pedirle a nadie que cambie como arranca sus
programas. Para un asistente de escritorio eso es mas util y mas universal.
Playwright/CDP queda como opcion futura para control fino DENTRO de una pagina.

TODA accion que modifica algo pasa por el gate de permisos, y el contexto que se
le pasa es la ventana activa REAL en ese momento, no la que el llamador crea.
"""

import subprocess
import unicodedata

from cognia.control.permisos import Accion, GestorPermisos


def _normalizar(texto: str) -> str:
    """Minusculas y sin acentos, para que 'Configuracion' encuentre
    'Configuración' y no dependa de como lo escriba el dueño."""
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in sin_acentos
                          if unicodedata.category(c) != "Mn")
    return sin_acentos.lower().strip()


def _backend():
    import uiautomation
    return uiautomation


class Escritorio:
    """Ver y manejar ventanas y controles de Windows.

        esc = Escritorio(GestorPermisos(confirmar=preguntar))
        esc.listar_ventanas()
        esc.enfocar("explorador")
        esc.clic("Guardar")

    backend: el modulo uiautomation, o un doble para tests. Se resuelve
    perezosamente para que importar este modulo no toque COM.
    """

    def __init__(self, permisos: GestorPermisos | None = None, backend=None):
        self.permisos = permisos or GestorPermisos()
        self._backend = backend

    @property
    def auto(self):
        if self._backend is None:
            self._backend = _backend()
        return self._backend

    # ── Leer (no modifica nada) ──────────────────────────────────────────

    def ventana_activa(self) -> str:
        """Titulo de la ventana en primer plano. Es el contexto que decide los
        permisos, asi que se consulta en el momento de cada accion y nunca se
        cachea: entre que se planeo la accion y se ejecuta, el foco pudo
        cambiar."""
        try:
            ctrl = self.auto.GetForegroundControl()
            return (ctrl.Name or "").strip() if ctrl else ""
        except Exception:
            return ""

    def listar_ventanas(self) -> list[dict]:
        """Ventanas de nivel superior con nombre visible."""
        salida = []
        try:
            hijos = self.auto.GetRootControl().GetChildren()
        except Exception:
            return []
        for w in hijos:
            nombre = (getattr(w, "Name", "") or "").strip()
            if not nombre:
                continue
            salida.append({
                "nombre": nombre,
                "tipo": getattr(w, "ControlTypeName", ""),
                "clase": getattr(w, "ClassName", ""),
            })
        return salida

    def buscar_ventana(self, texto: str) -> dict | None:
        """La ventana que mejor coincide con `texto`, o None.

        Prefiere la coincidencia mas ajustada (el titulo mas corto que
        contiene lo buscado): pedir "explorador" con dos ventanas abiertas
        tiene que dar la que se llama asi, no una cuyo titulo larguisimo lo
        menciona de paso.
        """
        objetivo = _normalizar(texto)
        if not objetivo:
            return None
        candidatas = [v for v in self.listar_ventanas()
                      if objetivo in _normalizar(v["nombre"])]
        if not candidatas:
            return None
        return min(candidatas, key=lambda v: len(v["nombre"]))

    def listar_elementos(self, ventana: str | None = None,
                         tipos: tuple = ("ButtonControl", "TabItemControl",
                                         "MenuItemControl", "ListItemControl",
                                         "HyperlinkControl"),
                         limite: int = 60) -> list[dict]:
        """Controles accionables de una ventana (o de la activa).

        Esto es lo que reemplaza a "mirar la pantalla con un modelo de vision":
        devuelve nombres y posiciones exactas, sin inferencia y sin VRAM.
        """
        v = self.permisos.evaluar(Accion("leer_pantalla", ventana or ""),
                                  ventana_activa=self.ventana_activa())
        if not v.permitida:
            return []
        raiz = self._control_de(ventana)
        if raiz is None:
            return []
        salida = []
        try:
            for ctrl, _prof in self.auto.WalkControl(raiz, maxDepth=6):
                if len(salida) >= limite:
                    break
                tipo = getattr(ctrl, "ControlTypeName", "")
                nombre = (getattr(ctrl, "Name", "") or "").strip()
                if not nombre or (tipos and tipo not in tipos):
                    continue
                salida.append({"nombre": nombre, "tipo": tipo})
        except Exception:
            pass
        return salida

    # ── Actuar (todo pasa por el gate) ───────────────────────────────────

    def enfocar(self, nombre: str) -> bool:
        """Trae una ventana al frente. Es de nivel libre: cambiar el foco no
        destruye nada y es el paso previo de casi cualquier tarea."""
        v = self.permisos.evaluar(Accion("enfocar_ventana", nombre),
                                  ventana_activa=self.ventana_activa())
        if not v.permitida:
            return False
        ctrl = self._control_de(nombre)
        if ctrl is None:
            return False
        try:
            ctrl.SetActive()
            ctrl.SetFocus()
            return True
        except Exception:
            return False

    def abrir_app(self, nombre: str) -> bool:
        """Abre una aplicacion o una URL delegando en el shell de Windows.

        Se usa `start` del shell y no una ruta a un .exe porque asi funciona
        igual con apps instaladas, con URLs y con documentos, que es lo que un
        asistente recibe pedido en lenguaje natural.
        """
        v = self.permisos.evaluar(Accion("abrir_app", nombre),
                                  ventana_activa=self.ventana_activa())
        if not v.permitida:
            return False
        try:
            # shell=True es necesario para `start`, que es un builtin de cmd.
            # El argumento va entre comillas y `start` recibe un titulo vacio
            # primero para no confundir el destino con un titulo de ventana.
            subprocess.Popen('start "" "%s"' % nombre, shell=True)
            return True
        except Exception:
            return False

    def clic(self, texto: str, ventana: str | None = None) -> bool:
        """Clic en el control cuyo nombre coincide con `texto`."""
        v = self.permisos.evaluar(Accion("clic", texto),
                                  ventana_activa=self.ventana_activa())
        if not v.permitida:
            return False
        ctrl = self._buscar_control(texto, ventana)
        if ctrl is None:
            return False
        try:
            ctrl.Click(simulateMove=False)
            return True
        except Exception:
            return False

    def escribir(self, texto: str) -> bool:
        """Escribe texto en el control con foco."""
        v = self.permisos.evaluar(Accion("escribir_texto", texto),
                                  ventana_activa=self.ventana_activa())
        if not v.permitida:
            return False
        try:
            self.auto.SendKeys(texto, waitTime=0)
            return True
        except Exception:
            return False

    # ── Internos ─────────────────────────────────────────────────────────

    def _control_de(self, nombre: str | None):
        """El control de ventana correspondiente a `nombre`, o la activa."""
        try:
            if not nombre:
                return self.auto.GetForegroundControl()
            encontrada = self.buscar_ventana(nombre)
            if encontrada is None:
                return None
            return self.auto.WindowControl(searchDepth=1,
                                           Name=encontrada["nombre"])
        except Exception:
            return None

    def _buscar_control(self, texto: str, ventana: str | None):
        """Primer control accionable cuyo nombre contiene `texto`."""
        raiz = self._control_de(ventana)
        if raiz is None:
            return None
        objetivo = _normalizar(texto)
        try:
            for ctrl, _prof in self.auto.WalkControl(raiz, maxDepth=6):
                nombre = (getattr(ctrl, "Name", "") or "").strip()
                if nombre and objetivo in _normalizar(nombre):
                    return ctrl
        except Exception:
            return None
        return None
