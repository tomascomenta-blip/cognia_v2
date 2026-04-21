import sys
sys.path.insert(0,'.')
from cognia_v3 import Cognia
from respuestas_articuladas import construir_contexto
from investigador import necesita_investigar
ai = Cognia()
ctx = construir_contexto(ai, 'que es el voleibol')
lines = [l for l in ctx.split(chr(10)) if chr(39) in l and len(l) > 60]
print('Episodios:', len(lines))
for l in lines[:5]:
    print(repr(l[:150]))
