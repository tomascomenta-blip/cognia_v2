import platform
import sys
import time
import os


class StateInspector:
    """
    Captura snapshot del estado interno de Cognia para debugging.
    """

    def get_system_info(self) -> dict:
        return {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "pid": os.getpid(),
            "uptime_hint": "see /metrics for uptime",
        }

    def get_singleton_states(self, app_context: dict) -> dict:
        """
        app_context: dict de nombre -> objeto singleton
        Para cada singleton, llama un método de inspección si existe,
        o retorna {"type": type_name, "available": bool}
        """
        states = {}
        for name, obj in app_context.items():
            if obj is None:
                states[name] = {"available": False}
                continue
            # Try inspection methods in priority order; stop at first hit
            for method_name in ["get_stats", "get_summary", "list_personas", "list_webhooks"]:
                method = getattr(obj, method_name, None)
                if method and callable(method):
                    try:
                        result = method()
                        states[name] = {
                            "available": True,
                            "type": type(obj).__name__,
                            "state": result,
                        }
                        break
                    except Exception as e:
                        states[name] = {
                            "available": True,
                            "type": type(obj).__name__,
                            "error": str(e)[:100],
                        }
                        break
            else:
                states[name] = {"available": True, "type": type(obj).__name__}
        return states

    def full_snapshot(self, app_context: dict) -> dict:
        return {
            "ts": time.time(),
            "system": self.get_system_info(),
            "singletons": self.get_singleton_states(app_context),
        }
