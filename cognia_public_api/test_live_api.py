"""
Test de la API publica de Cognia contra servidor local.
Ejecutar con: python test_live_api.py <api_key>
"""
import sys, httpx, time, statistics

BASE = "http://localhost:7860"

def test_health():
    r = httpx.get(f"{BASE}/health", timeout=5)
    assert r.status_code == 200
    print(f"[OK] /health -> {r.json()}")

def test_status():
    r = httpx.get(f"{BASE}/v1/status", timeout=5)
    assert r.status_code == 200
    data = r.json()
    print(f"[OK] /v1/status -> shard_loaded={data.get('shard_loaded')}, coordinator={data.get('coordinator')}")
    return data

def test_auth_required():
    r = httpx.post(f"{BASE}/v1/generate", json={"prompt": "test"}, timeout=5)
    assert r.status_code in (401, 403, 422), f"Expected 401/403/422, got {r.status_code}"
    print(f"[OK] /v1/generate sin auth -> {r.status_code} (correcto)")

def test_generate(api_key: str, n: int = 3):
    headers = {"Authorization": f"Bearer {api_key}"}
    prompts = [
        "Que es la inteligencia artificial?",
        "Explica el concepto de red neuronal en una linea.",
        "Hola Cognia, como estas?"
    ]
    times = []
    for i, prompt in enumerate(prompts[:n]):
        t0 = time.time()
        r = httpx.post(f"{BASE}/v1/generate", json={"prompt": prompt}, headers=headers, timeout=30)
        elapsed = time.time() - t0
        times.append(elapsed)
        if r.status_code == 200:
            data = r.json()
            text_preview = data.get("text", "")[:80].replace("\n", " ")
            print(f"[OK] prompt {i+1}: {elapsed:.2f}s | source={data.get('source')} | '{text_preview}...'")
        else:
            print(f"[WARN] prompt {i+1}: HTTP {r.status_code} en {elapsed:.2f}s -> {r.text[:100]}")

    if times:
        avg = statistics.mean(times)
        print(f"\n--- Resumen de velocidad ---")
        print(f"Prompts testeados: {len(times)}")
        print(f"Tiempo promedio: {avg:.2f}s")
        print(f"Tiempo min/max: {min(times):.2f}s / {max(times):.2f}s")
        print(f"Estimado tok/s (rough): N/A -- reportado por coordinator en data.tokens_per_second")

if __name__ == "__main__":
    api_key = sys.argv[1] if len(sys.argv) > 1 else None

    print("=== Cognia Public API - Test de integracion live ===\n")

    test_health()
    status = test_status()
    test_auth_required()

    if api_key:
        test_generate(api_key)
    else:
        print("\n[INFO] Para testear /v1/generate: python test_live_api.py <api_key>")

    print("\n=== Tests completados ===")
