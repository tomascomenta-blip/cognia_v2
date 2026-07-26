"""Probe: ¿que devuelve gpt-oss por /completion crudo vs /v1/chat/completions?
Hipotesis: el prompt crudo (sin plantilla Harmony) hace que el razonamiento
se cuele en el texto y generate_program rechace ('no es un documento HTML').
"""
import json
import urllib.request as req

PROMPT = ("You are a creative front-end developer.\n\n"
          "Write a complete self-contained HTML page with a button that "
          "increments a counter. Reply in this exact format:\n"
          "Title: <t>\nDescription: <d>\nHTML Code:\n```html\n<page>\n```")


def post(url, payload):
    r = req.Request(url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"})
    with req.urlopen(r, timeout=300) as x:
        return json.loads(x.read().decode("utf-8", errors="replace"))


print("== /completion (crudo, como LlamaBackend.generate / orch.infer) ==")
d = post("http://127.0.0.1:8080/completion",
         {"prompt": PROMPT, "n_predict": 700, "temperature": 0.2})
txt = d.get("content", "")
print(f"stop_type={d.get('stop_type')} len={len(txt)}")
print("canales_harmony=", "<|channel|>" in txt or "<|message|>" in txt,
      " tiene_fence=", "```" in txt, " tiene_html=", "<html" in txt.lower())
print(txt[:500].replace("\n", "\\n"))

print()
print("== /v1/chat/completions (como llm_local.generar) ==")
d = post("http://127.0.0.1:8080/v1/chat/completions",
         {"model": "local", "messages": [{"role": "user", "content": PROMPT}],
          "max_tokens": 700, "temperature": 0.2})
m = d["choices"][0]["message"]
c = m.get("content") or ""
rc = m.get("reasoning_content") or ""
print(f"finish={d['choices'][0].get('finish_reason')} len_content={len(c)} "
      f"len_reasoning={len(rc)}")
print("canales=", "<|channel|>" in c, " fence=", "```" in c,
      " html=", "<html" in c.lower())
print(c[:400].replace("\n", "\\n"))
