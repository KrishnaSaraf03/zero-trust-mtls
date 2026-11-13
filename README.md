# Track C: zero-trust between two microservices (mTLS + deny-by-default)

Two small services on one machine, Python standard library only (Python 3.10+, OpenSSL CLI).
On my machine the default `python3` is 3.9, so every command below uses `python3.12` explicitly.

Report: [REPORT.md](REPORT.md). Companion notes: [STUCK.md](STUCK.md), [WEEK2.md](WEEK2.md).

- `services/inventory.py`: callee. Requires a client certificate signed by our CA (TLS 1.3), reads the
  caller's SPIFFE-style ID from the URI SAN, and checks it against `policy.json`. No matching rule = 403.
- `services/orders.py`: caller. Presents its own certificate and verifies the server's.
- `policy.json`: one rule: `orders` may `GET /stock/*`. Everything else is denied.

## Exact commands

```bash
./scripts/gen_certs.sh                          # CA, untrusted CA, 4 leaf certs
python3.12 scripts/demo.py   | tee results/demo_output.txt     # 1 allowed + 4 blocked requests
python3.12 scripts/bench.py --n 1000 --rounds 5 | tee results/bench_summary.txt
./scripts/killsrv.sh                            # only if a run was interrupted
```

The Nagle stall (see `STUCK.md`) does not show on macOS, so it was reproduced in a Linux container. From a copy
of the project with the `wbufsize` and `TCP_NODELAY` lines in `services/inventory.py` commented out:

```bash
docker run --rm -v "$PWD:/app" -w /app python:3.12-slim python3 scripts/bench.py --n 50 --rounds 1 --warmup 5
```

Negotiated TLS parameters were checked with (server started in `mtls` mode on port 8442):

```bash
openssl s_client -connect 127.0.0.1:8442 -cert certs/orders.crt.pem -key certs/orders.key.pem -CAfile certs/demo-ca.crt.pem -brief
```

## Raw outputs (`results/`)

| file | what |
|---|---|
| `demo_output.txt`, `demo_server.log` | client view and server decision log for the 5 demo cases |
| `bench_summary.txt` | percentile table |
| `bench_raw.csv` | every single request latency (round, mode, conn, microseconds) |
| `stuck_nagle_before_fix.txt` | the misleading benchmark with the two fixes removed, Linux container (see STUCK.md) |
| `after_fix_linux_docker.txt` | same container, fixes restored, for a like-for-like before/after |
| `tls_negotiated.txt` | `openssl s_client` output: TLS 1.3, X25519MLKEM768, ECDSA P-256, AES-256-GCM |

## Benchmark design

Three server modes (`plain`, `mtls`, `mtls-policy`) x two connection styles (new connection per request,
keep-alive). Rounds are interleaved across modes; warm-up requests are discarded. `mtls` without policy
exists only to separate the cost of TLS from the cost of the authorization check.
