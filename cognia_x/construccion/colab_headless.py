r"""
Infra reusable para correr trabajos GPU en Colab vía colab-cli, HEADLESS y DESACOPLADO.

Por qué: Colab free se desconecta (~90 min idle / 12 h máx) y un `exec` síncrono largo pierde el output
si cae la conexión. El patrón robusto (briefing §4 / COLAB_GPU_SETUP.md): lanzar el script DESACOPLADO
(`Popen(..., start_new_session=True)`) con stdout→log y una SENTINELA que se escribe recién al terminar;
después se POLLEA con un checker. Este archivo GENERA el launcher y el checker para cualquier target, así
no se re-escriben a mano cada vez.

USO (desde el i3, PowerShell):
  # 1) generar launcher+checker para un target:
  venv312\Scripts\python.exe cognia_x\construccion\colab_headless.py --target m0_paramspeed_curve.py \
        --result g2_paramspeed_results.json --tag curve --out-dir <scratchpad>
  # 2) subir target + launcher a /content y exec el launcher (vuelve rápido):
  colab --auth oauth2 upload -s SESS <target> /content/<target>
  colab --auth oauth2 exec   -s SESS -f <launcher> --timeout 60
  # 3) pollear hasta que la sentinela exista, luego download del result:
  colab --auth oauth2 exec     -s SESS -f <checker> --timeout 30
  colab --auth oauth2 download -s SESS /content/<result> <local>
"""
import argparse
import os


LAUNCHER_TMPL = '''import os, subprocess
os.chdir('/content')
cmd = ("python /content/{target} > /content/{tag}.log 2>&1; "
       "echo DONE_EXIT=$? > /content/{tag_upper}_DONE")
subprocess.Popen(cmd, shell=True, start_new_session=True)
print("LAUNCHED {target} detached -> /content/{tag}.log (sentinela /content/{tag_upper}_DONE)")
'''

CHECKER_TMPL = '''import os
done = os.path.exists('/content/{tag_upper}_DONE')
print("=== {tag_upper}_DONE:", done, "===")
if done:
    print(open('/content/{tag_upper}_DONE').read().strip())
try:
    print(open('/content/{tag}.log').read()[-4500:])
except Exception as e:
    print("no log yet:", e)
print("=== RESULT_EXISTS:", os.path.exists('/content/{result}'), "===")
'''


def generate(target, result, tag, out_dir):
    ctx = {"target": target, "result": result, "tag": tag, "tag_upper": tag.upper()}
    launcher = os.path.join(out_dir, f"launch_{tag}.py")
    checker = os.path.join(out_dir, f"check_{tag}.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER_TMPL.format(**ctx))
    with open(checker, "w", encoding="utf-8") as f:
        f.write(CHECKER_TMPL.format(**ctx))
    return launcher, checker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="script a correr en /content (nombre del archivo)")
    ap.add_argument("--result", required=True, help="archivo de resultado que el target deja en /content")
    ap.add_argument("--tag", required=True, help="etiqueta corta (nombra log/sentinela/launcher/checker)")
    ap.add_argument("--out-dir", default=".", help="dónde escribir launcher+checker")
    args = ap.parse_args()
    launcher, checker = generate(args.target, args.result, args.tag, args.out_dir)
    print("launcher:", launcher)
    print("checker :", checker)


if __name__ == "__main__":
    main()
