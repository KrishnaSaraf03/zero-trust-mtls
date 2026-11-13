# Track C: Zero-trust between two microservices
Krishna Saraf, 2023A7PS0606P. Repo: https://github.com/KrishnaSaraf03/zero-trust-mtls

## 1. Goal

Zero trust between two services means the callee trusts nothing about the network: every request must carry a cryptographic proof of who the caller is, and that identity must be explicitly allowed to do the thing it is asking for. I set out to show three things with two small Python services: one request that passes both checks, four that are blocked at the right layer, and what the extra security costs in latency.

## 2. Method

Two services run on one machine. `orders` is the caller and `inventory` is the callee that answers stock lookups on `GET /stock/<sku>`. Each workload gets its own X.509 certificate from a private CA I generate with the OpenSSL CLI. The identity is a SPIFFE-style URI in the certificate's subjectAltName, for example `spiffe://demo.local/ns/shop/sa/orders`, not the common name. Only certificates signed by `demo-ca` are trusted; a second CA, `evil-ca`, exists purely to produce an untrusted certificate.

Enforcement happens in two separate layers. The TLS 1.3 handshake (`verify_mode = CERT_REQUIRED` on the server) decides whether the peer is *someone we know*: no certificate or an untrusted signer ends the connection before any HTTP is read. The policy check decides whether that known identity is *allowed to do this*: after the handshake, `inventory` reads the URI from the peer certificate and looks for a rule matching caller, method and path prefix in `policy.json`. The layers are separate because they answer different questions and fail differently: a handshake failure is visible only in the server log, while a policy denial is a normal HTTP 403 that the caller can act on. `policy.json` holds one rule, `orders` may `GET /stock/`. Deny by default is literal in the code: the `allowed()` function returns `False` when the loop over rules finds no match.

The benchmark runs three server modes: `plain` HTTP, `mtls` with certificate verification but no policy, and `mtls-policy`. The middle mode exists only to separate the cost of TLS from the cost of the authorization check. Each mode is measured with a new connection per request and over one keep-alive connection, 5 rounds of 1000 requests per cell, with 100 warm-up requests discarded. Rounds are interleaved across modes so that any slow drift on the machine, such as thermal throttling or a background process, hits all modes equally rather than biasing one. Machine: Apple M1 Pro (6 performance + 2 efficiency cores), macOS 27.0.1, Python 3.12.15, OpenSSL 3.5.9, loopback, one client thread.

## 3. Results

| Request | Result | Rejected at |
|---|---|---|
| orders GET /stock/42 | 200, `{"sku": "42", "qty": 17}` | not rejected: rule matches |
| orders POST /admin/reset | 403 `denied by policy` | policy check (valid identity, no rule for POST /admin) |
| reporting GET /stock/42 | 403 `denied by policy` | policy check (valid cert from our CA, no rule for this identity) |
| no client certificate | TLS failure, `TLSV13_ALERT_CERTIFICATE_REQUIRED` | TLS handshake (`PEER_DID_NOT_RETURN_A_CERTIFICATE` in server log) |
| certificate from untrusted CA | TLS failure, `TLSV1_ALERT_UNKNOWN_CA` | TLS handshake (`CERTIFICATE_VERIFY_FAILED` in server log) |

| Median latency (µs) | Plain | mTLS | mTLS + policy |
|---|---|---|---|
| New connection | 240 | 1352 | 1365 |
| Keep-alive | 94 | 103 | 104 |

Opening a fresh mTLS connection costs about 1.1 ms more than plain HTTP. On a reused connection the difference is about 10 µs per request, roughly a 10% overhead on an already tiny request. The per-connection cost is the handshake: an ECDHE key exchange plus ECDSA P-256 signing and verification on both sides, with client and server sharing the same CPU. The per-request cost is just AES-GCM record encryption. The policy check is not measurable at all: it is a loop over one rule doing three string comparisons, well under a microsecond, while the round-to-round spread of the p50 (1345 to 1374 µs for mTLS, 1350 to 1409 µs for mTLS + policy) is tens of microseconds. Tail latencies tell the same story: p99 is 2.9 ms for a new mTLS connection against 0.4 ms for plain, but on keep-alive the p99 values (217, 243 and 200 µs) are within noise of each other. The practical implication is that mTLS is nearly free as long as services reuse connections. A caller that opens a new connection per request pays the handshake every time and sees a 5x slowdown; a caller with a connection pool pays it once.

## 4. Main limitation

Everything runs on loopback on one machine, so there is no network round-trip. In a real deployment the TLS 1.3 handshake costs one extra RTT on top of TCP's, and across a data centre or region that RTT dwarfs the ~1 ms of CPU I measured here. Smaller limits: the server is Python's single-process `http.server`, not an Envoy or Istio sidecar, so absolute numbers do not transfer, only the shape; there is one client thread, so nothing is said about concurrency or throughput; no TLS session resumption was tested, which would shrink the per-connection cost further; and the policy has one rule, so lookup cost with thousands of rules is unknown.

## 5. One attack this setup does not stop

A stolen `orders` key. Any process running as my user on this host can read `certs/orders.key.pem` and `certs/orders.crt.pem` from disk. The attacker copies them, builds a TLS client with that identity, and sends `GET /stock/42`. The handshake succeeds because the certificate is genuinely signed by `demo-ca`, and the policy check succeeds because the SPIFFE ID in the certificate really is `orders`. Both layers are working exactly as designed: mTLS authenticates the workload holding the key, not the intent behind the request or the user who triggered it. There is no revocation (no CRL or OCSP), so the only thing that limits the damage is the 7-day certificate lifetime. Reducing the damage means issuing keys per workload from an agent that never writes them to shared disk (SPIRE, Istio's citadel), rotating in hours rather than days, restricting the allowed operations for `orders` to the minimum, and alerting when a known identity suddenly calls from a new process or at an unusual rate.

## 6. Where I got stuck and how I fixed it

I reproduced the stall described in the notes by commenting out the `wbufsize` and `TCP_NODELAY` lines in `inventory.py`. On my Mac nothing happened: keep-alive latency stayed at about 130 µs. That itself was the first surprise, so I ran the same broken server inside a Linux container (`python:3.12-slim` under Docker) and there every cell except plain-new-connection read 41 to 44 ms, with a p50 range of exactly zero across rounds. A latency that is flat to the microsecond regardless of whether TLS is on is a timer, not crypto. The cause is Python's `http.server` writing headers and body as two small TCP segments; Linux's Nagle algorithm holds the second one until the delayed ACK fires about 40 ms later. Buffering the response into one write fixed keep-alive (41472 → 133 µs), and `TCP_NODELAY` fixed new mTLS connections, whose post-handshake messages hit the same trap (44253 → 1664 µs). macOS does not show the stall because its delayed-ACK behaviour on loopback differs. Two other things broke on my machine: the default `python3` is 3.9 and the code needs 3.10+, so every command uses `python3.12`; and with OpenSSL 3.5 the no-certificate case returns a clear `certificate required` alert to the client rather than the generic EOF error the notes describe.

## 7. Second week

The question I most want answered is how much of the 1.1 ms per-connection cost survives when the two services are no longer on the same host, and whether a service mesh makes it better or worse. The experiment: deploy the same two services on a local kind cluster with Istio in STRICT PeerAuthentication mode and an AuthorizationPolicy expressing the same single rule, then run the same interleaved benchmark through the sidecars with and without a connection pool. Follow-ups: add concurrency with a load generator such as `hey` to see where the handshake CPU cost turns into queueing; and implement certificate rotation under load with short-lived certificates, to check that zero requests fail at the rotation boundary.

## Note on AI use

The initial code, benchmark design and a first draft of this report were produced with an AI assistant from my run outputs; I generated the certificates, ran the demo, benchmark and Linux-container reproduction on my own machine, checked every number in this report against the files in `results/`, and edited the text.
