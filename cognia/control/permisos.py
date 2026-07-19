"""
cognia/control/permisos.py
==========================
Gate de seguridad para las acciones de escritorio de Cognia
(planes/JARVIS_COGNIA.md 2.5).

Este modulo se escribe ANTES que navegador.py, escritorio.py y raton.py a
proposito. Cognia con mouse y teclado puede borrar archivos, mandar mensajes y
comprar cosas; el permiso no puede ser un agregado posterior porque para
entonces ya existe el camino sin permiso.

Tres niveles:
  LIBRE       se ejecuta sin preguntar (leer, abrir pestaña, buscar)
  CONFIRMAR   exige un si explicito del dueño (borrar, enviar, pagar, cerrar
              sin guardar)
  PROHIBIDO   no se ejecuta ni preguntando, porque el CONTEXTO lo veda (la
              ventana activa es un gestor de contraseñas, un banco o una
              ventana de incognito)

La distincion clave, y la razon de que el contexto gane siempre: una accion
inofensiva en abstracto ("escribir texto") deja de serlo si la ventana activa es
el gestor de contraseñas. Por eso se evalua (accion, ventana), nunca la accion
sola.

Politica de defecto: lo que no esta declarado se trata como CONFIRMAR, no como
LIBRE. Una accion nueva que nadie clasifico es sospechosa por definicion.
"""

import re
from dataclasses import dataclass, field

NIVEL_LIBRE = "libre"
NIVEL_CONFIRMAR = "confirmar"
NIVEL_PROHIBIDO = "prohibido"

# Catalogo de acciones conocidas. Las que no figuran caen en CONFIRMAR.
ACCIONES = {
    # --- lectura y navegacion: no destruyen nada ---
    "leer_pantalla": NIVEL_LIBRE,
    "listar_ventanas": NIVEL_LIBRE,
    "abrir_pestaña": NIVEL_LIBRE,
    "cambiar_pestaña": NIVEL_LIBRE,
    "navegar": NIVEL_LIBRE,
    "buscar": NIVEL_LIBRE,
    "desplazar": NIVEL_LIBRE,
    "captura_pantalla": NIVEL_LIBRE,
    "enfocar_ventana": NIVEL_LIBRE,
    "abrir_app": NIVEL_LIBRE,

    # --- modifican estado: exigen un si explicito ---
    "escribir_texto": NIVEL_CONFIRMAR,
    "clic": NIVEL_CONFIRMAR,
    "cerrar_pestaña": NIVEL_CONFIRMAR,
    "cerrar_ventana": NIVEL_CONFIRMAR,
    "cerrar_sin_guardar": NIVEL_CONFIRMAR,
    "borrar": NIVEL_CONFIRMAR,
    "mover_archivo": NIVEL_CONFIRMAR,
    "enviar": NIVEL_CONFIRMAR,
    "enviar_mensaje": NIVEL_CONFIRMAR,
    "enviar_correo": NIVEL_CONFIRMAR,
    "pagar": NIVEL_CONFIRMAR,
    "comprar": NIVEL_CONFIRMAR,
    "instalar": NIVEL_CONFIRMAR,
    "ejecutar_comando": NIVEL_CONFIRMAR,
    "apagar": NIVEL_CONFIRMAR,
}

# Ventanas donde Cognia no actua, punto. Se comparan contra el titulo de la
# ventana activa (sin distinguir mayusculas).
#
# OJO CON LOS LIMITES DE PALABRA: los nombres de producto van SIN \b al final a
# proposito. Un test cazo el bug: `\bkeepass\b` no matchea "KeePassXC" porque
# "XC" impide el limite de palabra, y ese es justamente el cliente de escritorio
# mas usado. Lo mismo pasaria con Bitwarden Desktop, 1Password 8, etc. En un
# gate de seguridad, fallar cerrado importa mas que la precision: preferimos
# marcar de mas.
PATRONES_VENTANA_SENSIBLE = [
    r"\bbitwarden", r"\b1password", r"\blastpass", r"\bkeepass",
    r"\bdashlane", r"\bproton ?pass", r"\bgestor de contrase",
    r"\bpassword manager", r"\badministrador de contrase",
    r"\binc[oó]gnito", r"\bincognito", r"\bprivate browsing",
    r"\bnavegaci[oó]n privada", r"\binprivate",
    r"\bhome ?bank", r"\bbanca en l[ií]nea", r"\bonline banking",
    r"\bmercado ?pago", r"\bpaypal", r"\bbilletera", r"\bwallet",
    r"\bwindows security", r"\bseguridad de windows",
    r"\bcontrol de cuentas de usuario", r"\buser account control",
]

_RE_SENSIBLE = re.compile("|".join(PATRONES_VENTANA_SENSIBLE), re.IGNORECASE)


def ventana_es_sensible(titulo: str | None) -> bool:
    """El titulo de la ventana activa indica un contexto donde no se actua?"""
    if not titulo:
        return False
    return bool(_RE_SENSIBLE.search(titulo))


@dataclass
class Accion:
    """Algo que Cognia quiere hacer en la computadora."""
    tipo: str
    objetivo: str = ""
    detalle: dict = field(default_factory=dict)

    def descripcion(self) -> str:
        base = self.tipo.replace("_", " ")
        return "%s: %s" % (base, self.objetivo) if self.objetivo else base


@dataclass
class Veredicto:
    """Resultado de evaluar una accion en su contexto."""
    nivel: str
    permitida: bool
    motivo: str
    accion: Accion
    ventana: str | None = None

    def __bool__(self) -> bool:
        return self.permitida


class GestorPermisos:
    """Decide si una accion se ejecuta, se pregunta o se rechaza.

        gestor = GestorPermisos(confirmar=preguntar_al_dueño)
        v = gestor.evaluar(Accion("borrar", "informe.docx"), ventana_activa="Explorador")
        if v:
            hacer_la_accion()

    confirmar: funcion que recibe el texto de la pregunta y devuelve True/False.
    Si no se pasa ninguna, toda accion de nivel CONFIRMAR se DENIEGA: sin canal
    para preguntar, el defecto seguro es que no.

    modo_estricto: si es True, tambien las acciones LIBRES se bloquean cuando la
    ventana activa es sensible. Por defecto es True, porque hasta leer la
    pantalla de un gestor de contraseñas es exactamente lo que no se quiere.
    """

    def __init__(self, confirmar=None, modo_estricto: bool = True,
                 acciones: dict | None = None):
        self.confirmar = confirmar
        self.modo_estricto = modo_estricto
        self.acciones = dict(acciones) if acciones else dict(ACCIONES)
        self.registro: list[Veredicto] = []

    def nivel_de(self, tipo: str) -> str:
        """Nivel declarado de un tipo de accion. Lo no declarado es CONFIRMAR:
        una accion que nadie clasifico no puede ser libre por descuido."""
        return self.acciones.get(tipo, NIVEL_CONFIRMAR)

    def evaluar(self, accion: Accion, ventana_activa: str | None = None) -> Veredicto:
        """Decide sin ejecutar nada. Registra el veredicto para auditoria."""
        nivel = self.nivel_de(accion.tipo)
        sensible = ventana_es_sensible(ventana_activa)

        # El contexto manda sobre el catalogo: da igual cuan inocente sea la
        # accion si la ventana activa es el gestor de contraseñas.
        if sensible and (self.modo_estricto or nivel != NIVEL_LIBRE):
            v = Veredicto(NIVEL_PROHIBIDO, False,
                          "ventana sensible: %r" % (ventana_activa,),
                          accion, ventana_activa)
            self.registro.append(v)
            return v

        if nivel == NIVEL_LIBRE:
            v = Veredicto(nivel, True, "accion de solo lectura o navegacion",
                          accion, ventana_activa)
        elif self.confirmar is None:
            v = Veredicto(nivel, False,
                          "requiere confirmacion y no hay canal para pedirla",
                          accion, ventana_activa)
        else:
            pregunta = "Cognia quiere %s. Autorizas?" % accion.descripcion()
            try:
                ok = bool(self.confirmar(pregunta))
            except Exception as exc:
                ok = False
                v = Veredicto(nivel, False,
                              "fallo al pedir confirmacion: %r" % (exc,),
                              accion, ventana_activa)
                self.registro.append(v)
                return v
            v = Veredicto(nivel, ok,
                          "confirmado por el dueño" if ok
                          else "el dueño lo rechazo", accion, ventana_activa)
        self.registro.append(v)
        return v

    def estadisticas(self) -> dict:
        return {
            "evaluadas": len(self.registro),
            "permitidas": sum(1 for v in self.registro if v.permitida),
            "denegadas": sum(1 for v in self.registro if not v.permitida),
            "prohibidas_por_contexto": sum(
                1 for v in self.registro if v.nivel == NIVEL_PROHIBIDO),
        }
