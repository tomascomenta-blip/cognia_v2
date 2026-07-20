"""
cognia_v3/core/sandbox_tester.py
================================
Prueba en sandbox el codigo de un modulo auto-generado por SelfArchitect, SIN tocar
el sistema real: valida sintaxis (AST) y lo ejecuta aislado (scan de imports bloqueados
+ timeout, en subprocess) via cognia_v3/interfaces/code_executor.py. Devuelve un reporte
con criterios pass/fail.

self_architect.test_proposal() lo usa:
    SandboxTester(db).test_module_from_code(code, module_name, proposal_id) -> report

(Antes self_architect importaba 'from sandbox_tester import SandboxTester' de un modulo
inexistente y test_proposal siempre devolvia error; esto cierra ese gating.)
"""

from __future__ import annotations

from datetime import datetime


class SandboxTester:
    """Valida y ejecuta en sandbox el codigo de un modulo propuesto."""

    def __init__(self, db_path: str = None) -> None:
        # db_path se acepta por compatibilidad con la llamada de self_architect; el
        # test NO toca la DB real (el codigo corre aislado en un subprocess).
        self.db = db_path

    def test_module_from_code(self, code: str, module_name: str = "module",
                              proposal_id: int = 0) -> dict:
        """Reporte: {passed, timestamp, summary, details:{criteria:{name:{passed,value}}}}."""
        from cognia_v3.interfaces.code_executor import (
            validate_python, run_python, validate_generated_module_imports)

        val = validate_python(code or "")
        # validate_python mezcla errores de sintaxis y de imports peligrosos
        # (estos contienen 'peligroso'); separarlos para atribuir bien los criterios.
        blocked_errs = [e for e in val.errors if "peligroso" in e.lower()]
        syntax_errs = [e for e in val.errors if "peligroso" not in e.lower()]
        syntax_ok = not syntax_errs
        no_blocked = not blocked_errs
        # Allowlist (regla 9): el codigo auto-generado solo puede importar stdlib seguro;
        # rechaza imports validos-pero-no-previstos que la blocklist no conoce.
        allow_ok, allow_offending = validate_generated_module_imports(code or "")
        # Solo ejecutar si pasa sintaxis + blocklist + allowlist (no gastar el subprocess en basura).
        exec_res = run_python(code) if (syntax_ok and no_blocked and allow_ok) else None

        # OJO: run_python.success exige stdout no vacio (linea 380); un MODULO que solo
        # define una clase no imprime nada -> aqui "ejecuta" = exit 0, sin stderr ni timeout.
        if exec_res is None:
            executes = False
            exec_val = "no ejecutado (sintaxis/imports invalidos)"
        elif exec_res.exit_code == 0 and not exec_res.timed_out and not (exec_res.errors or "").strip():
            executes = True
            exec_val = (exec_res.output or "")[:500] or "ok (exit 0, sin salida)"
        else:
            executes = False
            exec_val = (exec_res.errors or f"exit={exec_res.exit_code}")[:500]

        criteria = {
            "syntax_valid": {
                "passed": syntax_ok,
                "value": "; ".join(syntax_errs) if syntax_errs else "ok",
            },
            "no_blocked_imports": {
                "passed": no_blocked,
                "value": "; ".join(blocked_errs) if blocked_errs else "ok",
            },
            "imports_allowlisted": {
                "passed": allow_ok,
                "value": "ok" if allow_ok else
                         ("fuera de allowlist: " + ", ".join(allow_offending)),
            },
            "executes": {
                "passed": executes,
                "value": exec_val,
            },
        }
        passed = all(c["passed"] for c in criteria.values())
        if passed:
            summary = (f"{module_name}: OK (sintaxis valida, ejecuta en sandbox sin "
                       f"imports bloqueados)")
        else:
            fails = [k for k, v in criteria.items() if not v["passed"]]
            summary = f"{module_name}: FAIL en {', '.join(fails)}"

        return {
            "passed": passed,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "details": {"criteria": criteria, "proposal_id": proposal_id},
        }
