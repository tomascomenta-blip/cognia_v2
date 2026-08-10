# -*- coding: utf-8 -*-
"""Musica generativa para Cognia (backend SymphonyGen + render fluidsynth).

POR QUE existe este paquete: el vendor SymphonyGen vive fuera del repo
(~/.cognia/vendors/symphonygen) y exige torch -- que esta PROHIBIDO importar
en el proceso principal de cognia/. Este paquete es el puente: funciones
planas 100% stdlib que lanzan el trabajo pesado por subprocess con el python
de venv312gpu y un contrato stdout-JSON (patron expert_forge/cli_train.py).

Los re-exports son seguros: symphony_backend y render solo importan stdlib.
"""
from cognia.musica.symphony_backend import musica_disponible, orquestar
from cognia.musica.render import fluidsynth_disponible, midi_a_wav

__all__ = ["musica_disponible", "orquestar", "fluidsynth_disponible", "midi_a_wav"]
