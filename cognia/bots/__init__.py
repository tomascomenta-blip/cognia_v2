"""
cognia/bots/
============
Modo BOTS de Cognia: perfiles aislados con identidad propia (ALMA.md),
memoria, rutinas y un chat canonico, que se mandan mensajes entre si.

Fuente del diseno: Hermes Bot Mode (Nous Research, 2026-08-14,
docs/user-guide/bot-mode) y Grok Bot (xAI). Un bot ES un directorio bajo
dir_bots() -- nada vive en memoria de proceso: dos Cognias (el REPL y el
daemon) ven el mismo estado leyendo disco en cada llamada.

Modulos:
    registro.py    perfil en disco, identidad en el prompt, contexto(bot)
    mensajeria.py  inbox.jsonl entre bots, chat canonico (canon.jsonl)
    ejecutor.py    correr un turno / una rutina / el inbox (otro agente)
    __main__.py    daemon headless + estado + Scheduled Task (otro agente)

Layout por bot (dir_bots()/<nombre>/):
    bot.json         perfil (escritura atomica)
    ALMA.md          identidad libre (reemplaza al prompt de usuario)
    skills/          skills propias del bot
    permisos.json    allowlist persistente
    memoria/         COGNIA_DB_PATH del bot (config.py lo trata como DIRECTORIO)
    rutinas/         almacen integro de cognia.hermes.rutinas
    sesiones/canon.jsonl   chat canonico ({t, quien, texto}, como el remoto)
    inbox.jsonl      envelopes entrantes de otros bots

Apagado global: COGNIA_BOTS=0 (lo lee el CLI); este paquete no decide eso.
"""

from cognia.bots.registro import (  # noqa: F401
    Bot, Contexto, RE_NOMBRE, dir_bots, crear, listar, obtener, resolver,
    guardar, borrar, ruta, alma_de, escribir_alma, entorno, contexto,
    roster_texto, protocolo_mensajeria, ultima_actividad, activo, bot_activo,
)
