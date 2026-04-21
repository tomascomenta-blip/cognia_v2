with open('investigacion_nocturna.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    'from cognia import Cognia`nfrom cognia.vectors import text_to_vector, analyze_emotion',
    'from cognia import Cognia\nfrom cognia.vectors import text_to_vector, analyze_emotion'
)

with open('investigacion_nocturna.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Listo")