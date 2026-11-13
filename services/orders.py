"""orders service (the caller). Small client used by the demo and the benchmark."""
import http.client, json, ssl


def tls_context(certs="certs", identity=None, ca="demo-ca"):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_verify_locations(f"{certs}/{ca}.crt.pem")  # client verifies the server too
    if identity:
        ctx.load_cert_chain(f"{certs}/{identity}.crt.pem", f"{certs}/{identity}.key.pem")
    return ctx


def connect(port, ctx=None):
    if ctx is None:
        return http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    return http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=5)


def call(port, method, path, ctx=None):
    """Returns (status, body) or ('TLS-FAIL', reason)."""
    c = connect(port, ctx)
    try:
        c.request(method, path)
        r = c.getresponse()
        return r.status, json.loads(r.read())
    except (ssl.SSLError, ConnectionError, http.client.HTTPException) as e:
        return "TLS-FAIL", f"{type(e).__name__}: {e}"
    finally:
        c.close()
