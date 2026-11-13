"""inventory service (the callee).

Modes:
  plain        HTTP, no auth at all (latency baseline)
  mtls         TLS 1.3, client cert required, but no authorization check
  mtls-policy  mTLS + deny-by-default policy on the caller's SPIFFE ID

Every decision is written to stdout as one JSON line.
"""
import argparse, json, socket, ssl, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STOCK = {"42": 17, "7": 0}


def log(**kw):
    kw["ts"] = round(time.time(), 3)
    print(json.dumps(kw), flush=True)


def spiffe_id(cert):
    for kind, value in (cert or {}).get("subjectAltName", ()):
        if kind == "URI" and value.startswith("spiffe://"):
            return value
    return None


def allowed(policy, caller, method, path):
    for r in policy["rules"]:
        if r["from"] == caller and method in r["methods"] and path.startswith(r["path_prefix"]):
            return True
    return False  # deny by default: no matching rule means no access


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, so we can measure reused connections
    # Buffer headers + body into one write. Unbuffered, they go out as two small segments,
    # and Nagle + delayed ACK stalls every response by ~40 ms (see results/stuck_nagle_before_fix.txt).
    wbufsize = 65536
    caller = None

    def setup(self):
        super().setup()
        # Same reason as wbufsize below: without NODELAY the TLS 1.3 post-handshake messages
        # get stuck behind Nagle and every *new* mTLS connection costs an extra ~40 ms.
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.server.mode != "plain":
            try:
                self.request.do_handshake()
                self.caller = spiffe_id(self.request.getpeercert())
            except (ssl.SSLError, OSError) as e:
                if not self.server.quiet:
                    log(event="handshake_rejected", peer=self.client_address[0],
                        reason=getattr(e, "reason", None) or str(e))
                self.close_connection = True
                self.handshake_failed = True

    def handle(self):
        if getattr(self, "handshake_failed", False):
            return
        super().handle()

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve(self):
        if self.server.mode == "mtls-policy":
            ok = allowed(self.server.policy, self.caller, self.command, self.path)
            if not self.server.quiet:
                log(event="authz", caller=self.caller, method=self.command,
                    path=self.path, decision="allow" if ok else "deny")
            if not ok:
                return self._reply(403, {"error": "denied by policy", "caller": self.caller})
        if self.command == "GET" and self.path.startswith("/stock/"):
            sku = self.path.rsplit("/", 1)[-1]
            return self._reply(200, {"sku": sku, "qty": STOCK.get(sku, 0)})
        if self.command == "POST" and self.path == "/admin/reset":
            return self._reply(200, {"reset": True})
        self._reply(404, {"error": "not found"})

    do_GET = do_POST = _serve

    def log_message(self, *a):  # silence default access log
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["plain", "mtls", "mtls-policy"], required=True)
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--certs", default="certs")
    ap.add_argument("--policy", default="policy.json")
    ap.add_argument("--quiet", action="store_true", help="no per-request logs (for benchmarks)")
    a = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.mode, srv.quiet = a.mode, a.quiet
    srv.policy = json.load(open(a.policy))
    if a.mode != "plain":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(f"{a.certs}/inventory.crt.pem", f"{a.certs}/inventory.key.pem")
        ctx.load_verify_locations(f"{a.certs}/demo-ca.crt.pem")
        ctx.verify_mode = ssl.CERT_REQUIRED  # this is the "mutual" part
        # handshake is done per-connection in Handler.setup so a bad client cannot block accept()
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    log(event="listening", mode=a.mode, port=a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
