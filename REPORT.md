# Track C: Zero-trust between two microservices
Krishna Saraf, 2023A7PS0606P. Repo: https://github.com/KrishnaSaraf03/zero-trust-mtls
Companion notes: [STUCK.md](https://github.com/KrishnaSaraf03/zero-trust-mtls/blob/main/STUCK.md) (where I got stuck) and [WEEK2.md](https://github.com/KrishnaSaraf03/zero-trust-mtls/blob/main/WEEK2.md) (second-week plan).

## 1. Goal

Zero trust between two services means the callee trusts nothing about the network: every request must carry a cryptographic proof of who the caller is, and that identity must be explicitly allowed to do the thing it is asking for. I set out to show three things with two small Python services: one request that passes both checks, four that are blocked at the right layer, and what the extra security costs in latency.

## 2. Method

Two services run on one machine. `orders` is the caller and `inventory` is the callee that answers stock lookups on `GET /stock/<sku>`. Each workload gets its own X.509 certificate from a private CA I generate with the OpenSSL CLI. The identity is a SPIFFE-style URI in the certificate's subjectAltName, for example `spiffe://demo.local/ns/shop/sa/orders`, not the common name. Only certificates signed by `demo-ca` are trusted; a second CA, `evil-ca`, exists purely to produce an untrusted certificate.

Enforcement happens in two separate layers. The TLS 1.3 handshake (`verify_mode = CERT_REQUIRED` on the server) decides whether the peer is *someone we know*: no certificate or an untrusted signer ends the connection before any HTTP is read. The policy check decides whether that known identity is *allowed to do this*: after the handshake, `inventory` reads the URI from the peer certificate and looks for a rule matching caller, method and path prefix in `policy.json`. The layers are separate because they answer different questions and fail differently: a handshake failure gives the client a TLS alert instead of an HTTP response, with the detailed reason only in the server log, while a policy denial is a normal HTTP 403 that the caller can act on. `policy.json` holds one rule, `orders` may `GET /stock/`. Deny by default is literal in the code: the `allowed()` function returns `False` when the loop over rules finds no match.

The benchmark runs three server modes: `plain` HTTP, `mtls` with certificate verification but no policy, and `mtls-policy`. The middle mode exists only to separate the cost of TLS from the cost of the authorization check. Each mode is measured with a new connection per request and over one keep-alive connection, 5 rounds of 1000 requests per cell, with 100 warm-up requests discarded. Rounds are interleaved across modes so that any slow drift on the machine, such as thermal throttling or a background process, hits all modes equally rather than biasing one. Machine: Apple M1 Pro (6 performance + 2 efficiency cores), macOS 27.0.1, Python 3.12.15, OpenSSL 3.5.9, loopback, one client thread.

## 3. Results

| Request | Result | Rejected at |
|---|---|---|
| orders GET /stock/42 | 200, `{"sku": "42", "qty": 17}` | not rejected: rule matches |
| orders POST /admin/reset | 403 `denied by policy` | policy check (valid identity, no rule for POST /admin) |
| reporting GET /stock/42 | 403 `denied by policy` | policy check (valid cert from our CA, no rule for this identity) |
| no client certificate | TLS alert `CERTIFICATE_REQUIRED` | TLS handshake (`PEER_DID_NOT_RETURN_A_CERTIFICATE` in server log) |
| certificate from untrusted CA | TLS alert `UNKNOWN_CA` | TLS handshake (`CERTIFICATE_VERIFY_FAILED` in server log) |

| Median latency (µs) | Plain | mTLS | mTLS + policy |
|---|---|---|---|
| New connection | 240 | 1352 | 1365 |
| Keep-alive | 94 | 103 | 104 |

Opening a fresh mTLS connection costs about 1.1 ms more than plain HTTP, a 5.6x slowdown. On a reused connection the difference is about 10 µs per request, roughly a 10% overhead on an already tiny request. The per-connection cost is the handshake. I checked what was negotiated with `openssl s_client` (`results/tls_negotiated.txt`): the key exchange is the hybrid post-quantum group X25519MLKEM768, which OpenSSL 3.5 prefers by default, the certificate signatures are ECDSA P-256, and the cipher suite is TLS_AES_256_GCM_SHA384, with client and server on the same machine. The per-request cost is AES-256-GCM record encryption. The policy check is not measurable: it is a loop over one rule doing three string comparisons, expected to be well under a microsecond, while the round-to-round spread of the p50 (1345 to 1374 µs for mTLS, 1350 to 1409 µs for mTLS + policy) is tens of microseconds. Tail latencies tell the same story: p99 is 2.9 ms for a new mTLS connection against 0.4 ms for plain, but on keep-alive the p99 values (217, 243 and 200 µs) are within noise of each other. The practical implication is that mTLS is nearly free as long as services reuse connections. A caller that opens a new connection per request pays the handshake every time; a caller with a connection pool pays it once.

## 4. Main limitation

Everything runs on loopback on one machine, so there is no network round-trip. A TLS 1.3 handshake costs one extra round trip on top of TCP's, and that round trip is unmeasured here: it is small within a data centre, where the ~1 ms of handshake CPU I measured still dominates, and dominant across regions. Smaller limits: the server is Python's `http.server`, not an Envoy or Istio sidecar, so absolute numbers do not transfer, only the shape; there is one client thread, so nothing is said about concurrency or throughput; no TLS session resumption was tested, which would shrink the per-connection cost further; and the policy has one rule, so lookup cost with thousands of rules is unknown.

## 5. One attack this setup does not stop

A stolen `orders` key. Any process running as my user on this host can read `certs/orders.key.pem` and `certs/orders.crt.pem` from disk. The attacker copies them, builds a TLS client with that identity, and sends `GET /stock/42`. The handshake succeeds because the certificate is genuinely signed by `demo-ca`, and the policy check succeeds because the SPIFFE ID in the certificate really is `orders`. Both layers are working exactly as designed: mTLS authenticates the workload holding the key, not the intent behind the request or the user who triggered it. There is no revocation (no CRL or OCSP), so the only thing that limits the damage is the 7-day certificate lifetime. Reducing the damage means issuing keys per workload from an agent that never writes them to shared disk (SPIRE, or `istiod` in Istio), rotating in hours rather than days, and alerting when a known identity suddenly calls from a new process or at an unusual rate.

## Note on AI use

The initial code, benchmark design and a first draft of this report were produced with an AI assistant from my run outputs; I generated the certificates, ran the demo, benchmark and Linux-container reproduction on my own machine, checked every number in this report against the files in `results/`, and edited the text.
