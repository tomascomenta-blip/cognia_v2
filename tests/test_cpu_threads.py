"""
tests/test_cpu_threads.py
Tests de regresion para node/cpu_threads.py y sus consumidores.

Cubre la medicion del 2026-07-23 (llama-bench, Qwen3-1.7B Q4_K_M, -ngl 0, tg32):
  - 6c/12t: 12 hilos -> 39.81 tok/s vs 6 hilos -> 45.65 tok/s (+14.7%)
    => en maquinas con muchos nucleos hay que CAPPEAR a los fisicos.
  - analogo i3 (afinidad a 4 CPUs logicas = 2 fisicas): 2 hilos -> 25.86 tok/s
    vs 4 hilos -> 39.03 tok/s (+51%)
    => "nucleos fisicos" pelado castiga a la maquina objetivo; piso 4.

Sin estos tests, cualquiera de los dos extremos vuelve a colarse (los dos
estuvieron en produccion a la vez: llama_backend usaba todos los logicos y el
perfil 'cpu' usaba solo los fisicos).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from node import cpu_threads as ct


def _fijar_maquina(monkeypatch, logicos: int, fisicos: int) -> None:
    """Simula una maquina de N logicos / M fisicos para hilos_cpu_optimos."""
    monkeypatch.setattr(ct.os, "cpu_count", lambda: logicos)
    monkeypatch.setattr(ct, "nucleos_fisicos", lambda: fisicos)


class TestHilosCpuOptimos:

    def test_maquina_grande_cappea_a_fisicos(self, monkeypatch):
        """6 fisicos / 12 logicos -> 6, no 12. Medido: 45.65 vs 39.81 tok/s."""
        _fijar_maquina(monkeypatch, logicos=12, fisicos=6)
        assert ct.hilos_cpu_optimos() == 6
        # con el techo historico del camino in-process (max(4, cpu_count)=12)
        assert ct.hilos_cpu_optimos(12) == 6
        # con el techo historico del camino llama-server (cpu_count-1 = 11)
        assert ct.hilos_cpu_optimos(11) == 6

    def test_maquina_i3_conserva_el_default_historico(self, monkeypatch):
        """2 fisicos / 4 logicos -> 4, NO 2. Medido: 39.03 vs 25.86 tok/s."""
        _fijar_maquina(monkeypatch, logicos=4, fisicos=2)
        assert ct.hilos_cpu_optimos() == 4
        # camino in-process: default historico max(4, 4) = 4 -> intacto
        assert ct.hilos_cpu_optimos(4) == 4
        # camino llama-server: default historico cpu_count-1 = 3 -> intacto,
        # porque la medicion del i3 en llama_backend.py ("el 4o hilo logico
        # compite con el SO") sigue mandando como TECHO.
        assert ct.hilos_cpu_optimos(3) == 3

    def test_nunca_sube_hilos_sobre_el_default_previo(self, monkeypatch):
        """El techo es duro: este cambio solo puede BAJAR hilos, nunca subirlos."""
        for logicos, fisicos in ((4, 2), (8, 4), (12, 6), (16, 8), (32, 16), (2, 1)):
            _fijar_maquina(monkeypatch, logicos=logicos, fisicos=fisicos)
            for previo in (max(4, logicos), max(1, logicos - 1)):
                assert ct.hilos_cpu_optimos(previo) <= previo

    def test_nunca_supera_los_logicos_ni_baja_de_uno(self, monkeypatch):
        """Sobre-suscribir mide peor (12 hilos en 4 CPUs -> 32.17 tok/s)."""
        _fijar_maquina(monkeypatch, logicos=2, fisicos=1)
        n = ct.hilos_cpu_optimos()
        assert 1 <= n <= 2
        _fijar_maquina(monkeypatch, logicos=1, fisicos=1)
        assert ct.hilos_cpu_optimos() == 1

    def test_piso_cuatro_en_maquinas_de_pocos_fisicos(self, monkeypatch):
        """Con >=4 logicos, nunca devolver menos de 4 (el bug del perfil 'cpu')."""
        _fijar_maquina(monkeypatch, logicos=8, fisicos=2)
        assert ct.hilos_cpu_optimos() == ct.PISO_HILOS == 4

    def test_nucleos_fisicos_es_positivo_en_esta_maquina(self):
        n = ct.nucleos_fisicos()
        assert isinstance(n, int) and n >= 1


class TestConsumidores:

    def test_llama_backend_usa_el_helper(self, monkeypatch):
        """_n_threads() ya no devuelve todos los hilos logicos."""
        import node.llama_backend as lb
        monkeypatch.delenv("LLAMA_N_THREADS", raising=False)
        _fijar_maquina(monkeypatch, logicos=12, fisicos=6)
        assert lb._n_threads() == 6

    def test_llama_backend_respeta_el_override_de_entorno(self, monkeypatch):
        """LLAMA_N_THREADS sigue mandando sobre cualquier default calculado."""
        import node.llama_backend as lb
        monkeypatch.setenv("LLAMA_N_THREADS", "3")
        assert lb._n_threads() == 3

    def test_perfil_cpu_no_baja_del_piso(self):
        """El perfil 'cpu' aplicado en un i3 no debe fijar 2 hilos (-34%)."""
        from cognia import perf_profiles as pp
        import os
        hilos = int(pp.PROFILES["cpu"]["LLAMA_N_THREADS"])
        logicos = os.cpu_count() or 4
        assert hilos == min(logicos, max(ct.nucleos_fisicos(), ct.PISO_HILOS))
        assert hilos >= min(logicos, ct.PISO_HILOS)

    def test_perfil_gpu_sigue_usando_todos_los_logicos(self):
        """En GPU el CPU solo alimenta a la placa: el cap no aplica."""
        from cognia import perf_profiles as pp
        import os
        assert int(pp.PROFILES["gpu"]["LLAMA_N_THREADS"]) == (os.cpu_count() or 4)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
