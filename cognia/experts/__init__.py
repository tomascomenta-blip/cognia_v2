"""
cognia/experts
==============
Registro persistente de expertos (perfiles de modelo con dedicacion).
API publica re-exportada desde registry.py.
"""

from .registry import (
    BACKENDS,
    BUILTIN_EXPERTS,
    Expert,
    add_expert,
    experts_dir,
    get_expert,
    load_registry,
    registry_path,
    remove_expert,
    render_modelos_table,
    save_custom,
    set_enabled,
    system_prompt_path,
)

__all__ = [
    "BACKENDS",
    "BUILTIN_EXPERTS",
    "Expert",
    "add_expert",
    "experts_dir",
    "get_expert",
    "load_registry",
    "registry_path",
    "remove_expert",
    "render_modelos_table",
    "save_custom",
    "set_enabled",
    "system_prompt_path",
]
