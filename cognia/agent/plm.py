# -*- coding: utf-8 -*-
"""
cognia/agent/plm.py
===================
Mantener DESPIERTAS las apps de la Store (UWP) que viven en la mesa
(2026-09-09). MEDIDO: Windows suspende una app empaquetada cuando su ventana
no esta en el escritorio visible (Process Lifecycle Management): en la mesa
`CalculatorApp.exe` pasa a estado `stopped` a los pocos segundos de abrir, y
una app suspendida NO expone su arbol de UI Automation (1 nodo) ni procesa
Invoke; traida al escritorio visible vuelve a 50 nodos, devuelta a la mesa
vuelve a 1. Por eso `mesa_invocar` acertaba los primeros botones y luego "no
encontraba" el siguiente.

El mecanismo oficial para eximir a un paquete de la suspension es
`IPackageDebugSettings::EnableDebugging(packageFullName, NULL, NULL)` (lo que
hace la herramienta PLMDebug del SDK con /enableDebug; no exige admin). Se
recuerda cada paquete eximido y `liberar()` (atexit y /escritorio limpiar)
llama a DisableDebugging para dejar Windows como estaba.
"""
from __future__ import annotations

import atexit
import ctypes
import os
from ctypes import wintypes

_EXIMIDOS: set = set()
_ULTIMO: dict = {"error": ""}

_IID = "{F27C3930-8029-4AD1-94E3-3DBA417810C1}"
_CLSID = "{B1AEC16F-2383-4852-B0E9-8F0B1DC66B4D}"


def paquete_de_pid(pid: int) -> str:
    """Nombre completo del paquete (Store) del proceso, o '' si no es una app
    empaquetada (GetPackageFullName -> APPMODEL_ERROR_NO_PACKAGE)."""
    if os.name != "nt":
        return ""
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, int(pid))         # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        n = wintypes.UINT(0)
        k.GetPackageFullName(h, ctypes.byref(n), None)
        if n.value == 0:
            return ""
        buf = ctypes.create_unicode_buffer(n.value)
        if k.GetPackageFullName(h, ctypes.byref(n), buf) != 0:
            return ""
        return buf.value
    finally:
        k.CloseHandle(h)


def _settings():
    import comtypes  # type: ignore
    from comtypes import GUID, COMMETHOD, HRESULT, IUnknown, CoCreateInstance  # type: ignore

    class IPackageDebugSettings(IUnknown):
        _iid_ = GUID(_IID)
        _methods_ = [
            COMMETHOD([], HRESULT, "EnableDebugging",
                      (["in"], ctypes.c_wchar_p, "packageFullName"),
                      (["in"], ctypes.c_wchar_p, "debuggerCommandLine"),
                      (["in"], ctypes.c_wchar_p, "environment")),
            COMMETHOD([], HRESULT, "DisableDebugging", (["in"], ctypes.c_wchar_p, "packageFullName")),
            COMMETHOD([], HRESULT, "Suspend", (["in"], ctypes.c_wchar_p, "packageFullName")),
            COMMETHOD([], HRESULT, "Resume", (["in"], ctypes.c_wchar_p, "packageFullName")),
            COMMETHOD([], HRESULT, "TerminateAllProcesses", (["in"], ctypes.c_wchar_p, "packageFullName")),
        ]
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    return CoCreateInstance(GUID(_CLSID), interface=IPackageDebugSettings)


def mantener_despierta(pid: int) -> dict:
    """Exime de la suspension al paquete del proceso `pid` (y lo reanuda si ya
    estaba suspendido). {ok, paquete, motivo}. Si no es app de la Store, ok=True
    con paquete='' (no hace falta)."""
    paq = ""
    try:
        paq = paquete_de_pid(pid)
    except Exception as exc:
        return {"ok": False, "paquete": "", "motivo": "GetPackageFullName: %s" % exc}
    if not paq:
        return {"ok": True, "paquete": "", "motivo": "no es una app empaquetada"}
    if paq in _EXIMIDOS:
        return {"ok": True, "paquete": paq, "motivo": "ya eximido"}
    try:
        s = _settings()
        s.EnableDebugging(paq, None, None)
        try:
            s.Resume(paq)
        except Exception:
            pass
        _EXIMIDOS.add(paq)
        return {"ok": True, "paquete": paq, "motivo": "eximido de la suspension (PLM)"}
    except Exception as exc:
        _ULTIMO["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        return {"ok": False, "paquete": paq, "motivo": _ULTIMO["error"]}


def liberar() -> int:
    """DisableDebugging de todo lo eximido. Devuelve cuantos."""
    n = 0
    if not _EXIMIDOS:
        return 0
    try:
        s = _settings()
    except Exception:
        return 0
    for paq in list(_EXIMIDOS):
        try:
            s.DisableDebugging(paq)
            n += 1
        except Exception:
            pass
        _EXIMIDOS.discard(paq)
    return n


atexit.register(liberar)


def estado() -> dict:
    return {"eximidos": sorted(_EXIMIDOS), "error": _ULTIMO["error"]}
