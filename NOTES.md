# Working notes (raw material for the report, not the report)

## What was measured (sandbox run: 1 vCPU Linux VM, Python 3.12, OpenSSL 3.0.13, loopback)
5 rounds x 1000 requests per cell, p50 in microseconds:

| | plain | mTLS | mTLS + policy |
|---|---|---|---|
| new connection per request | 276 | 2813 | 2815 |
| keep-alive | 97 | 114 | 113 |

- New connection: about +2.5 ms per request. This is the handshake (two ECDSA P-256 signatures and
  verifications each side, client and server sharing one core).
- Keep-alive: about +17 us at p50 (record encryption). Policy check is below the noise
  (round-to-round p50 spread is larger than the mtls vs mtls-policy difference).
- So the cost of mTLS is almost entirely a per-connection cost, not a per-request cost.

## Allowed / blocked (results/demo_output.txt)
1. orders GET /stock/42 -> 200
2. orders POST /admin/reset -> 403 (identity fine, no rule for that method/path)
3. reporting GET /stock/42 -> 403 (valid cert from our CA, no rule for that identity)
4. no client cert -> handshake rejected (PEER_DID_NOT_RETURN_A_CERTIFICATE)
5. cert from other CA -> handshake rejected (CERTIFICATE_VERIFY_FAILED)

## Things that went wrong while building this
1. First benchmark said every mTLS request took ~44 ms, and even plain keep-alive took 44 ms
   (results/stuck_nagle_before_fix.txt). The flat 44 ms with almost no variance was the clue: that is
   a timer, not crypto. Cause: http.server writes headers and body as two small segments -> Nagle +
   delayed ACK. Fix: buffer the response (wbufsize) -> keep-alive dropped to ~0.1 ms.
2. New mTLS connections were still 44 ms after that. Same family of problem, in the TLS 1.3
   post-handshake messages. Fix: TCP_NODELAY on the accepted socket -> 2.8 ms.
   Had I reported the first number, the conclusion "mTLS adds 44 ms" would have been wrong by ~15x.
3. On a rejected client cert, the client only sees a generic "EOF occurred in violation of protocol".
   In TLS 1.3 the client finishes its side of the handshake before the server has checked the client
   cert, so the failure shows up on the first read, with no useful reason. The real reason is only in
   the server log. Bad for debugging, arguably good for not leaking information.
4. The cleanup command (pkill -f inventory.py) killed its own shell because the pattern matched the
   shell's command line. Replaced by scripts/killsrv.sh, which only matches python processes.

## Attacks this setup does not stop (pick one for the report)
- Compromised `orders` process or stolen orders key: attacker makes any request orders is allowed to
  make. mTLS authenticates the workload, not the intent or the end user. No revocation here (no
  CRL/OCSP); only mitigation is the 7-day cert lifetime.
- Keys sit unencrypted on disk next to each other; on one host, any process running as the same user
  can read orders.key.pem. A real setup issues keys per workload (SPIRE / Istio) and rotates in hours.
- Anything inside an allowed request: injection in the path, an allowed caller flooding /stock/.

## Limits of the measurement
- Loopback, one machine, one core shared by client and server, single client thread: no network RTT,
  no concurrency, so handshake cost is CPU-only and tail latencies mean little.
- Python stdlib server, not Envoy/Istio sidecars: absolute numbers do not transfer; the shape
  (per-connection cost >> per-request cost) should.
- No TLS session resumption measured; one cipher/key type (P-256); tiny payloads.
- Policy is one rule; lookup cost with thousands of rules was not tested.

## Week-2 ideas
Same two services on kind/minikube with Istio (STRICT PeerAuthentication + AuthorizationPolicy),
compare sidecar latency with these numbers; add concurrency (wrk/hey); short-lived certs with
rotation under load; session resumption; test the stolen-key scenario and what detects it.
