# Track C: zero-trust between two microservices (mTLS + deny-by-default)

Two small services on one machine, Python standard library only (Python 3.10+, OpenSSL CLI).

- `services/inventory.py`: callee. Requires a client certificate signed by our CA (TLS 1.3), reads the
  caller's SPIFFE-style ID from the URI SAN, and checks it against `policy.json`. No matching rule = 403.
- `services/orders.py`: caller. Presents its own certificate and verifies the server's.
- `policy.json`: one rule: `orders` may `GET /stock/*`. Everything else is denied.

## Exact commands

```bash
./scripts/gen_certs.sh                          # CA, untrusted CA, 4 leaf certs
python3 scripts/demo.py   | tee results/demo_output.txt     # 1 allowed + 4 blocked requests
python3 scripts/bench.py --n 1000 --rounds 5 | tee results/bench_summary.txt
./scripts/killsrv.sh                            # only if a run was interrupted
```

## Raw outputs (`results/`)

| file | what |
|---|---|
| `demo_output.txt`, `demo_server.log` | client view and server decision log for the 5 demo cases |
| `bench_summary.txt` | percentile table |
| `bench_raw.csv` | every single request latency (round, mode, conn, microseconds) |
| `stuck_nagle_before_fix.txt` | the misleading first benchmark, kept on purpose (see NOTES.md) |

## Benchmark design

Three server modes (`plain`, `mtls`, `mtls-policy`) x two connection styles (new connection per request,
keep-alive). Rounds are interleaved across modes; warm-up requests are discarded. `mtls` without policy
exists only to separate the cost of TLS from the cost of the authorization check.
