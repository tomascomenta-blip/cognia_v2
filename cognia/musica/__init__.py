# -*- coding: utf-8 -*-
"""Musica generativa para Cognia (backend SymphonyGen + render fluidsynth).

POR QUE existe este paquete: el vendor SymphonyGen vive fuera del repo
(~/.cognia/vendors/symphonygen) y exige torch -- que esta PROHIBIDO importar
en el proceso principal de cognia/. Este paquete es el puente: funciones
planas 100% stdlib que lanzan el trabajo pesado por subprocess con el python
de venv312gpu y un contrato stdout-JSON (patron expert_forge/cli_train.py).

Los re-exports son seguros: symphony_backend y render solo importan stdlib,
y expresividad importa miditoolkit PEREZOSO (solo al aplicar).
"""
from cognia.musica.symphony_backend import musica_disponible, orquestar
from cognia.musica.render import fluidsynth_disponible, midi_a_wav
from cognia.musica.expresividad import aplicar_expresividad
# el modulo se llama transcripcion (y no transcribir) A PROPOSITO: exportar
# una funcion homonima a su modulo hace que `from cognia.musica import
# transcribir` devuelva una u otro segun el orden de imports (visto en la
# suite: AttributeError dependiente del orden)
from cognia.musica.transcripcion import transcribir, transcribir_disponible
from cognia.musica.song2song import song_to_song
from cognia.musica.compositor import componer_esqueleto, texto_a_esqueleto
from cognia.musica.banco_monotonia import medir as medir_monotonia
# modulo produccion, funcion producir: nombres distintos A PROPOSITO (misma
# leccion que transcripcion/transcribir de arriba). pedalboard/numpy se
# importan perezosos dentro de producir: este import es liviano.
from cognia.musica.produccion import producir

__all__ = ["musica_disponible", "orquestar", "fluidsynth_disponible",
           "midi_a_wav", "aplicar_expresividad", "transcribir",
           "transcribir_disponible", "song_to_song", "componer_esqueleto",
           "texto_a_esqueleto", "medir_monotonia", "producir"]
