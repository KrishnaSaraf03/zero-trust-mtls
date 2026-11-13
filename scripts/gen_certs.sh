#!/usr/bin/env bash
# Builds a tiny PKI: one trusted CA, one untrusted CA, and one leaf cert per workload.
# Identity lives in the URI SAN (SPIFFE-style), not in the CN.
set -euo pipefail
cd "$(dirname "$0")/../certs"
rm -f *.pem *.srl *.csr *.cnf

mkca() { # name
  openssl ecparam -name prime256v1 -genkey -noout -out "$1.key.pem"
  openssl req -x509 -new -key "$1.key.pem" -sha256 -days 30 -subj "/CN=$1" -out "$1.crt.pem"
}
mkleaf() { # name ca usage
  local name=$1 ca=$2 usage=$3
  openssl ecparam -name prime256v1 -genkey -noout -out "$name.key.pem"
  openssl req -new -key "$name.key.pem" -subj "/CN=$name" -out "$name.csr"
  cat > "$name.cnf" <<CNF
subjectAltName=URI:spiffe://demo.local/ns/shop/sa/$name,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=$usage
keyUsage=critical,digitalSignature
basicConstraints=CA:FALSE
CNF
  openssl x509 -req -in "$name.csr" -CA "$ca.crt.pem" -CAkey "$ca.key.pem" -CAcreateserial \
    -days 7 -sha256 -extfile "$name.cnf" -out "$name.crt.pem" 2>/dev/null
  rm -f "$name.csr" "$name.cnf"
}

mkca demo-ca
mkca evil-ca
mkleaf inventory demo-ca serverAuth      # the server
mkleaf orders    demo-ca clientAuth      # allowed caller
mkleaf reporting demo-ca clientAuth      # valid cert, but no policy rule -> must be denied
mkleaf intruder  evil-ca clientAuth      # cert from a CA we do not trust
rm -f *.srl
echo "certs written to $(pwd)"; ls -1
