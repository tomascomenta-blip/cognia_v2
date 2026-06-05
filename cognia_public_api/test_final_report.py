"""
Reporte final de la API publica de Cognia.
Ejecutar: python test_final_report.py [api_key]
"""
import sys
import time

import httpx

BASE = "http://localhost:7860"


def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 60)
    print("COGNIA PUBLIC API - REPORTE FINAL")
    print("=" * 60)

    # Health check
    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        print(f"Servidor: ACTIVO (HTTP {r.status_code})")
    except Exception as e:
        print(f"Servidor: INACTIVO ({e})")
        return

    # Status
    r = httpx.get(f"{BASE}/v1/status", timeout=5)
    s = r.json()
    print(f"Shard cargado: {s.get('shard_loaded', False)}")
    print(f"Coordinator: {s.get('coordinator', 'N/A')}")
    print(f"Version: {s.get('version', 'N/A')}")

    # API Key
    if api_key:
        print(f"\nAPI Key activa: {api_key}")

        # 3 requests de prueba
        print("\nTests de inferencia (3 prompts):")
        headers = {"Authorization": f"Bearer {api_key}"}
        prompts = [
            "Hola Cognia!",
            "Que es machine learning?",
            "Dame un tip de programacion.",
        ]
        total_time = 0.0
        for i, p in enumerate(prompts):
            t0 = time.time()
            r = httpx.post(
                f"{BASE}/v1/generate",
                json={"prompt": p},
                headers=headers,
                timeout=30,
            )
            t = time.time() - t0
            total_time += t
            d = r.json()
            print(
                f"  [{i+1}] {t:.2f}s | source={d.get('source')} | "
                f"'{d.get('text', '')[:60]}...'"
            )

        print(f"\nTiempo promedio: {total_time/3:.2f}s por request")
        print(f"Throughput estimado: {3/total_time:.2f} req/s")
    else:
        print(f"\nUSO: python test_final_report.py <api_key>")
        print(f"Ejemplo: python test_final_report.py cogn-2bcfb6317aaf14f3")

    print("\n" + "=" * 60)
    print("INSTRUCCIONES DE DEPLOY 24/7 GRATIS (sin tarjeta):")
    print("-" * 60)
    print("1. huggingface.co/new-space -> SDK: Docker -> CPU Basic (gratis)")
    print("2. Subir carpeta cognia_public_api/ al Space")
    print("3. Secrets: COORDINATOR_KEY, HF_TOKEN")
    print("4. Space URL: https://TU-USUARIO-cognia-api.hf.space")
    print("5. Keep-alive: agregar .github/workflows/keepalive_cognia_api.yml")
    print("   + agregar Secret COGNIA_SPACE_URL en GitHub repo")
    print("6. cron-job.org (alternativa): ping cada 5 min, gratis, sin cuenta")
    print("=" * 60)


if __name__ == "__main__":
    main()
