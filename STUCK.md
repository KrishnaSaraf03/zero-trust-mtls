# Where I got stuck and how I fixed it

Companion to [REPORT.md](REPORT.md). All numbers in this note are from a Linux container (`python:3.12-slim` under Docker on the same Mac), not from the macOS benchmark in the report.

I reproduced the stall described in the working notes by commenting out the `wbufsize` and `TCP_NODELAY` lines in `services/inventory.py`. On my Mac nothing happened: keep-alive latency stayed at about 130 µs. That itself was the first surprise, so I ran the same broken server inside the Linux container (`results/stuck_nagle_before_fix.txt`) and there every cell except plain-new-connection read 41 to 44 ms. I ran one round of 50 requests, so the range across rounds says nothing, but p50 and p95 were within 3 ms of each other in every stalled cell, and the number was the same whether TLS was on or off. A latency that flat and that indifferent to crypto is a timer, not crypto.

The cause is Python's `http.server` writing headers and body as two small TCP segments; Linux's Nagle algorithm holds the second one until the delayed ACK fires about 40 ms later. Buffering the response into one write fixed keep-alive (41472 to 133 µs), and `TCP_NODELAY` fixed new mTLS connections, whose post-handshake messages hit the same trap (44253 to 1664 µs). Both fixed numbers are in `results/after_fix_linux_docker.txt`. A likely explanation for macOS not showing the stall is that its delayed-ACK behaviour on loopback differs; I did not test this.

Two other things broke on my machine. The default `python3` is 3.9 and the code needs 3.10+, so every command uses `python3.12`. And with OpenSSL 3.5 the no-certificate case returns a clear `certificate required` alert to the client rather than the generic EOF error the working notes describe.

Exact command for the container reproduction, run from a copy of the project with the two lines commented out:

```bash
docker run --rm -v "$PWD:/app" -w /app python:3.12-slim python3 scripts/bench.py --n 50 --rounds 1 --warmup 5
```
