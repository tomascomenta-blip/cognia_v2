import sys
sys.path.insert(0, '.')
from cognia_v3 import Cognia
from respuestas_articuladas import construir_contexto
from investigador import necesita_investigar, investigar_si_necesario
ai = Cognia()
pregunta = 'que es el voleibol'
ctx = construir_contexto(ai, pregunta)
print('=== CONTEXTO ===')
print(ctx[:800] if ctx else 'VACIO')
print()
print('=== NECESITA INVESTIGAR ===', necesita_investigar(ctx))
print()
ctx2, inv, info = investigar_si_necesario(ai, pregunta, ctx)
print('=== INVESTIGADO ===', inv)
print('=== INFO ===', info)
