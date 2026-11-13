"""Allowed vs blocked requests against inventory in mtls-policy mode."""
import subprocess, sys, time
sys.path.insert(0, "services")
from orders import call, tls_context

PORT = 8443
srv = subprocess.Popen([sys.executable, "services/inventory.py", "--mode", "mtls-policy", "--port", str(PORT)],
                       stdout=open("results/demo_server.log", "w"), stderr=subprocess.STDOUT)
time.sleep(0.8)
cases = [
    ("1 orders    GET  /stock/42     (rule matches)",        "GET",  "/stock/42",    tls_context(identity="orders")),
    ("2 orders    POST /admin/reset  (no rule for this path)", "POST", "/admin/reset", tls_context(identity="orders")),
    ("3 reporting GET  /stock/42     (valid cert, no rule)",  "GET",  "/stock/42",    tls_context(identity="reporting")),
    ("4 no client certificate",                               "GET",  "/stock/42",    tls_context(identity=None)),
    ("5 intruder  cert from untrusted CA",                    "GET",  "/stock/42",    tls_context(identity="intruder")),
]
try:
    for name, method, path, ctx in cases:
        status, body = call(PORT, method, path, ctx)
        print(f"{name:55s} -> {status}  {body}")
finally:
    time.sleep(0.3); srv.terminate(); srv.wait()
print("\n--- server log (results/demo_server.log) ---")
print(open("results/demo_server.log").read())
