"""Latency benchmark: plain HTTP vs mTLS vs mTLS+policy, new connection vs keep-alive.

Rounds are interleaved (plain, mtls, mtls-policy, plain, ...) so that slow drift on the
machine hits all modes equally. Raw per-request latencies go to results/bench_raw.csv.
"""
import argparse, csv, platform, ssl, statistics as st, subprocess, sys, time
sys.path.insert(0, "services")
from orders import connect, tls_context

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=1000, help="requests per (mode, conn, round)")
ap.add_argument("--rounds", type=int, default=5)
ap.add_argument("--warmup", type=int, default=100)
a = ap.parse_args()

MODES = {"plain": 8081, "mtls": 8442, "mtls-policy": 8443}
procs = [subprocess.Popen([sys.executable, "services/inventory.py", "--mode", m, "--port", str(p), "--quiet"],
                          stdout=subprocess.DEVNULL) for m, p in MODES.items()]
time.sleep(1.0)


def one_new(port, ctx):
    t = time.perf_counter_ns()
    c = connect(port, ctx); c.request("GET", "/stock/42"); r = c.getresponse(); r.read(); c.close()
    assert r.status == 200
    return (time.perf_counter_ns() - t) / 1e3  # microseconds


def run(mode, conn, n):
    port = MODES[mode]
    ctx = None if mode == "plain" else tls_context(identity="orders")
    if conn == "new":
        return [one_new(port, ctx) for _ in range(n)]
    c = connect(port, ctx); out = []
    for _ in range(n):
        t = time.perf_counter_ns()
        c.request("GET", "/stock/42"); r = c.getresponse(); r.read()
        out.append((time.perf_counter_ns() - t) / 1e3)
    c.close()
    return out


def pct(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


rows, data = [], {}
try:
    for m in MODES:
        for conn in ("new", "keepalive"):
            run(m, conn, a.warmup)
    for rnd in range(a.rounds):
        for conn in ("new", "keepalive"):
            for m in MODES:
                xs = run(m, conn, a.n)
                data.setdefault((m, conn), []).append(xs)
                rows += [(rnd, m, conn, f"{x:.1f}") for x in xs]
finally:
    for p in procs: p.terminate()

with open("results/bench_raw.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["round", "mode", "conn", "latency_us"]); w.writerows(rows)

print(f"python {platform.python_version()} | {ssl.OPENSSL_VERSION} | {platform.platform()}")
print(f"{a.rounds} rounds x {a.n} requests per cell, {a.warmup} warm-up requests discarded, loopback, 1 client thread\n")
print(f"{'conn':10s} {'mode':12s} {'p50':>8s} {'p95':>8s} {'p99':>8s} {'mean':>8s}  {'p50 range across rounds':>24s}   (microseconds)")
for conn in ("new", "keepalive"):
    for m in MODES:
        rounds = data[(m, conn)]; allx = [x for r in rounds for x in r]
        meds = [st.median(r) for r in rounds]
        print(f"{conn:10s} {m:12s} {st.median(allx):8.0f} {pct(allx,95):8.0f} {pct(allx,99):8.0f} {st.mean(allx):8.0f}  {min(meds):10.0f} .. {max(meds):<10.0f}")
    print()
