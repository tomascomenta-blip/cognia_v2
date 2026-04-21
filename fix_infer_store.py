import re
with open('cognia_v3.py', 'r', encoding='utf-8') as f:
    code = f.read()
OLD = '        else:\n            # \u2500\u2500 MODO INFERENCIA \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
NEW = '        else:\n            # \u2500\u2500 MODO INFERENCIA \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n            self.episodic.store(observation=observation, label=None, vector=vec, confidence=0.3, importance=0.5, emotion=emotion, surprise=surprise, context_tags=[])'
if OLD in code:
    code = code.replace(OLD, NEW)
    with open('cognia_v3.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print('Parche aplicado OK')
else:
    print('Texto no encontrado - parche manual necesario')
