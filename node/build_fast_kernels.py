"""
node/build_fast_kernels.py
Compiles fast_kernels.c into a shared library.

Priority:
  1. gcc / clang  (Linux, macOS, MinGW on Windows)
  2. MSVC via vswhere + vcvars64.bat (Windows, no gcc in PATH)
  3. cffi.compile()  (any OS — uses setuptools to find the system compiler)

Usage:
    python node/build_fast_kernels.py          # build with best available flags
    python node/build_fast_kernels.py --no-omp # disable OpenMP
    python node/build_fast_kernels.py --cffi   # force cffi path
"""

import os
import sys
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

SRC      = Path(__file__).parent / "fast_kernels.c"
IS_WIN   = platform.system() == "Windows"
OUT_EXT  = ".dll" if IS_WIN else ".so"
OUT      = SRC.with_suffix(OUT_EXT)

# Common compiler locations not always in PATH
_EXTRA_COMPILER_PATHS = [
    r"C:\Program Files\LLVM\bin\clang++.exe",
    r"C:\Program Files\LLVM\bin\clang.exe",
    r"C:\msys64\mingw64\bin\gcc.exe",
    r"C:\msys64\ucrt64\bin\gcc.exe",
]

# cffi output module name — placed alongside the C source
CFFI_MOD = "_fast_kernels_cffi"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _try_cmd(cmd: list, label: str, env: "dict | None" = None) -> bool:
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode == 0:
        print(f"[fast_kernels] built with {label}")
        return True
    print(f"[fast_kernels] {label} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return False


def _msys2_env(gcc_path: str) -> dict:
    """Return os.environ with MSYS2 bin dirs prepended so the MinGW linker is found."""
    import os
    msys2_root = Path(gcc_path).parent.parent.parent  # ucrt64/bin/gcc.exe -> msys64/
    extra = str(Path(gcc_path).parent)                # e.g. C:\msys64\ucrt64\bin
    usr_bin = str(msys2_root / "usr" / "bin")
    env = os.environ.copy()
    env["PATH"] = extra + os.pathsep + usr_bin + os.pathsep + env.get("PATH", "")
    return env


def _find_vcvars() -> "str | None":
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if not vswhere.exists():
        return None
    r = subprocess.run([str(vswhere), "-latest", "-property", "installationPath"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    # vswhere sometimes wraps the path in quotes — strip them before constructing the Path
    install_path = r.stdout.strip().strip('"')
    build = Path(install_path) / "VC" / "Auxiliary" / "Build"
    for name in ("vcvarsall.bat", "vcvars64.bat"):
        p = build / name
        if p.exists():
            return str(p)
    return None


def _try_vcvars(vcvars: str, omp: bool) -> bool:
    """Compile via MSVC after sourcing vcvars. Writes a temp .bat to avoid cmd quoting issues."""
    args     = "" if vcvars.endswith("vcvars64.bat") else " x64"
    omp_flag = "/openmp " if omp else ""
    cmd_line = (
        f'call "{vcvars}"{args}\r\n'
        f'cl /O2 /arch:AVX2 {omp_flag}/LD "{SRC}" /Fe:"{OUT}"\r\n'
    )
    bat = Path(tempfile.mktemp(suffix=".bat"))
    try:
        bat.write_text(f"@echo off\r\n{cmd_line}", encoding="cp1252")
        r = subprocess.run(["cmd.exe", "/c", str(bat)],
                           capture_output=True, text=True, cwd=str(SRC.parent))
        label = f"msvc (vswhere{'+omp' if omp else ''})"
        if r.returncode == 0 and OUT.exists():
            print(f"[fast_kernels] built with {label}")
            return True
        print(f"[fast_kernels] {label} failed:\n{(r.stdout + r.stderr).strip()[:400]}")
    finally:
        bat.unlink(missing_ok=True)
    return False


def _build_cffi() -> bool:
    """Fall-back: use cffi.compile() which invokes setuptools + MSVC automatically."""
    try:
        from cffi import FFI
    except ImportError:
        print("[fast_kernels] cffi not installed — cannot use cffi fallback.")
        return False

    ffi = FFI()
    ffi.cdef("""
        void int4_linear(uint8_t *packed, float *scale,
                         int n_rows, int n_packed, int orig_cols,
                         float *x, int n_batch, float *out);
        void rms_norm(float *x, float *weight,
                      int n_batch, int d, float eps, float *out);
        void silu_fwd(float *x, int n_batch, int d, float *out);
    """)

    extra = ["/O2", "/arch:AVX2"] if IS_WIN else ["-O3", "-march=native", "-ffast-math"]
    ffi.set_source(
        CFFI_MOD,
        SRC.read_text(encoding="utf-8"),
        extra_compile_args=extra,
        libraries=[] if IS_WIN else ["m"],
    )
    try:
        out_dir = str(SRC.parent)
        ffi.compile(tmpdir=out_dir, verbose=True)
        print(f"[fast_kernels] built with cffi (module: {CFFI_MOD})")
        return True
    except Exception as e:
        print(f"[fast_kernels] cffi compile failed: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def build(no_omp: bool = False, force_cffi: bool = False) -> bool:
    if not force_cffi:
        base = ["-O3", "-march=native", "-mavx2", "-mfma", "-ffast-math",
                "-shared"] + ([] if IS_WIN else ["-fPIC"])
        omp  = [] if no_omp else ["-fopenmp"]

        # gcc — check PATH first, then known MSYS2 install locations
        _GCC_EXTRA = [
            r"C:\msys64\ucrt64\bin\gcc.exe",
            r"C:\msys64\mingw64\bin\gcc.exe",
            r"C:\msys64\mingw32\bin\gcc.exe",
        ]
        gcc_exe = shutil.which("gcc")
        if not gcc_exe and IS_WIN:
            for p in _GCC_EXTRA:
                if Path(p).exists():
                    gcc_exe = p
                    break
        if gcc_exe:
            gcc_env = _msys2_env(gcc_exe) if any(p in gcc_exe for p in ("msys64",)) else None
            if _try_cmd([gcc_exe] + base + omp + [str(SRC), "-o", str(OUT), "-lm"], "gcc+omp", gcc_env):
                return True
            if omp:
                if _try_cmd([gcc_exe] + base + [str(SRC), "-o", str(OUT), "-lm"], "gcc", gcc_env):
                    return True

        # clang (PATH or known install locations)
        clang_exe = shutil.which("clang") or shutil.which("clang++")
        if not clang_exe:
            for p in _EXTRA_COMPILER_PATHS:
                if Path(p).exists():
                    clang_exe = p
                    break
        if clang_exe:
            # clang++ needs -x c to compile C files
            x_flag = ["-x", "c"] if "clang++" in clang_exe else []
            if _try_cmd([clang_exe] + x_flag + base + omp + [str(SRC), "-o", str(OUT), "-lm"], "clang+omp"):
                return True
            if omp:
                if _try_cmd([clang_exe] + x_flag + base + [str(SRC), "-o", str(OUT), "-lm"], "clang"):
                    return True

        # cl.exe already in PATH
        if IS_WIN and shutil.which("cl"):
            omp_cl = [] if no_omp else ["/openmp"]
            if _try_cmd(["cl", "/O2", "/arch:AVX2"] + omp_cl +
                        ["/LD", str(SRC), f"/Fe:{OUT}"], "msvc(PATH)"):
                return True

        # MSVC via vswhere
        if IS_WIN:
            vcvars = _find_vcvars()
            if vcvars:
                if _try_vcvars(vcvars, omp=not no_omp):
                    return True
                if not no_omp:
                    if _try_vcvars(vcvars, omp=False):
                        return True

    # cffi fallback (any OS)
    return _build_cffi()


if __name__ == "__main__":
    no_omp     = "--no-omp" in sys.argv
    force_cffi = "--cffi"   in sys.argv
    sys.exit(0 if build(no_omp=no_omp, force_cffi=force_cffi) else 1)
