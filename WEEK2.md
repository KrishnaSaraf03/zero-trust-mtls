# Second week

Companion to [REPORT.md](REPORT.md).

The question I most want answered is how much of the 1.1 ms per-connection cost survives when the two services are no longer on the same host, and whether a service mesh makes it better or worse. The experiment: deploy the same two services on a local kind cluster with Istio in STRICT PeerAuthentication mode and an AuthorizationPolicy expressing the same single rule, then run the same interleaved benchmark through the sidecars with and without a connection pool. Follow-ups: add concurrency with a load generator such as `hey` to see where the handshake CPU cost turns into queueing; and implement certificate rotation under load with short-lived certificates, to check that zero requests fail at the rotation boundary.
