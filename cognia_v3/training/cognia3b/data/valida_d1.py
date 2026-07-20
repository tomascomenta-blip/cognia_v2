"""Validador del dataset D1 (identidad Cognia) contra el SPEC.

Correr: .\\venv312\\Scripts\\python.exe cognia_v3\\training\\cognia3b\\data\\valida_d1.py
Exit 0 = valido; 1 = defectos (listados).
"""
import glob
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = os.path.abspath(os.path.join(HERE, "..", "..", "..", "eval", "suites"))
ARCHIVOS = ["d1_ab_identidad.jsonl", "d1_cd_capacidades.jsonl", "d1_e_estilo.jsonl"]
MARCAS_PROHIBIDAS = ["qwen", "alibaba", "gpt", "openai", "claude", "anthropic",
                     "meta ai", "gemini", "google ai"]
# "llama" es verbo español comunísimo ("me llaman", "se llama") → solo es marca
# en contextos tipo "Llama 3", "meta llama", "llama.cpp" (regex, no substring).
RE_LLAMA_MARCA = re.compile(r"(?i)\bllama[s]?[-. ]?\d|meta[- ]llama|\bllama\.cpp")
CATS = set("ABCDE")


def fold(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


def norm_prompt(p):
    return re.sub(r"\s+", " ", fold(p)).strip(" ?!.¿¡")


def main():
    errores, avisos = [], []
    pares, prompts_vistos = [], {}
    for nombre in ARCHIVOS:
        path = os.path.join(HERE, nombre)
        if not os.path.exists(path):
            errores.append(f"{nombre}: NO EXISTE")
            continue
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    errores.append(f"{nombre}:{lineno}: línea vacía")
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as e:
                    errores.append(f"{nombre}:{lineno}: JSON roto: {e}")
                    continue
                for campo in ("prompt", "completion", "cat", "idioma"):
                    if not r.get(campo):
                        errores.append(f"{nombre}:{lineno}: falta {campo}")
                if r.get("cat") not in CATS:
                    errores.append(f"{nombre}:{lineno}: cat inválida {r.get('cat')}")
                    continue
                texto = fold(r.get("prompt", "") + " " + r.get("completion", ""))
                comp = fold(r.get("completion", ""))
                # regla 3: marcas prohibidas — en la COMPLETION siempre es error;
                # en el prompt solo si la cat no es B (en B el usuario pregunta
                # "sos chatgpt?" y eso es legitimo)
                for m in MARCAS_PROHIBIDAS:
                    if m in comp:
                        errores.append(f"{nombre}:{lineno}: marca prohibida "
                                       f"'{m}' en completion (cat {r['cat']})")
                    elif m in texto and r["cat"] != "B":
                        avisos.append(f"{nombre}:{lineno}: marca '{m}' en prompt "
                                      f"de cat {r['cat']} (revisar)")
                if RE_LLAMA_MARCA.search(r.get("completion", "")):
                    errores.append(f"{nombre}:{lineno}: marca Llama (regex) "
                                   f"en completion")
                # regla 4
                if r["cat"] in "AB" and "cognia" not in comp:
                    errores.append(f"{nombre}:{lineno}: cat {r['cat']} sin "
                                   "'Cognia' en completion")
                if r["cat"] == "E" and "cognia" in comp:
                    errores.append(f"{nombre}:{lineno}: cat E menciona Cognia "
                                   "(identity-spam)")
                np = norm_prompt(r.get("prompt", ""))
                if np in prompts_vistos:
                    errores.append(f"{nombre}:{lineno}: prompt duplicado de "
                                   f"{prompts_vistos[np]}")
                else:
                    prompts_vistos[np] = f"{nombre}:{lineno}"
                pares.append(r)

    # overlap EXACTO con los prompts de la suite G3 (held-out de identidad)
    g3 = os.path.join(SUITES, "g3_identidad.jsonl")
    if os.path.exists(g3):
        with open(g3, encoding="utf-8") as f:
            g3_prompts = {norm_prompt(json.loads(l)["prompt"]) for l in f if l.strip()}
        colisiones = [p for p in prompts_vistos if p in g3_prompts]
        for c in colisiones:
            errores.append(f"OVERLAP con suite G3 (train==eval exacto): '{c}' "
                           f"en {prompts_vistos[c]} — reformular el par de train")

    # conteos
    from collections import Counter
    cats = Counter(r["cat"] for r in pares)
    idiomas = Counter(r["idioma"] for r in pares)
    print(f"pares: {len(pares)} | cats: {dict(cats)} | idiomas: {dict(idiomas)}")
    for a in avisos[:10]:
        print("AVISO", a)
    if errores:
        print(f"\nERRORES: {len(errores)}")
        for e in errores[:40]:
            print(" ", e)
        sys.exit(1)
    print("D1 VALIDO")


if __name__ == "__main__":
    main()
