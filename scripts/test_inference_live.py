"""Test real inference against the live desktop API."""
import urllib.request, json, time, sys
def _safe(s): return "".join(c if ord(c) < 128 else "?" for c in s)

BASE = "http://127.0.0.1:8765"

def stream(prompt, history=None, label=""):
    payload = json.dumps({"prompt": prompt, "history": history or []}).encode()
    req = urllib.request.Request(
        BASE + "/infer-stream-v2", data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    t0 = time.time()
    tokens = []; meta = {}; buf = b""
    with urllib.request.urlopen(req, timeout=90) as r:
        while True:
            chunk = r.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line.startswith(b"data:"):
                    try:
                        d = json.loads(line[5:].strip())
                        if d.get("token"):
                            tokens.append(d["token"])
                        if d.get("done"):
                            meta = d
                            break
                    except Exception:
                        pass
            if meta.get("done"):
                break
    el = time.time() - t0
    txt = "".join(tokens)
    tps = len(tokens) / el if el > 0 else 0
    print(f"\n[{_safe(label)}]")
    print(f"  Q: {_safe(prompt[:70])}")
    print(f"  A: {_safe(txt[:300])}")
    print(f"  {len(tokens)} tokens | {el:.1f}s | {tps:.1f} tok/s | mode={meta.get('mode','?')}")
    sys.stdout.flush()
    return tps

speeds = []
speeds.append(stream("Hola, como estas?", label="TEST1 saludo"))
speeds.append(stream("Que es Python? Una oracion.", label="TEST2 conocimiento"))
speeds.append(stream("def factorial(n):", label="TEST3 codigo"))
h = [{"role": "user", "content": "Me llamo Carlos"}, {"role": "assistant", "content": "Hola Carlos!"}]
speeds.append(stream("Como me llamo?", history=h, label="TEST4 memoria"))

print(f"\nPROMEDIO: {sum(speeds)/len(speeds):.1f} tok/s")
