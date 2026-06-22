r"""
Verificacion REAL end-to-end del wiring de speculative en node/llama_backend.py:
arranca el _LlamaServerBackend (que ahora agrega --spec-type ngram-mod por defecto),
genera texto de verdad y confirma salida no vacia. CHECK explicito (CLAUDE.md).

  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\verify_spec_wiring.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from node.llama_backend import _LlamaServerBackend, _spec_args  # noqa: E402

GGUF = REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"


def main():
    print("CHECK _spec_args() default =", _spec_args())
    assert _spec_args() == ["--spec-type", "ngram-mod"]
    b = _LlamaServerBackend(GGUF, port=8098)
    try:
        out = b.generate("Di una frase corta y amable en espanol.",
                         max_tokens=24, temperature=0.0)
        print("CHECK salida real:", repr(out)[:240])
        assert out and out.strip(), "salida VACIA — el server no genero!"
        print("CHECK OK: el backend arranco con --spec-type ngram-mod y genero texto real.")
    finally:
        proc = getattr(b, "_proc", None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
