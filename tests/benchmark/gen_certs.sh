#!/bin/sh
# Generates the CA, server and client certificates shared by both benchmark targets.
# Usage: gen_certs.sh <output-dir>
set -e

OUT="${1:?usage: gen_certs.sh <output-dir>}"
mkdir -p "$OUT"
cd "$OUT"

if [ -f client.crt ]; then
  echo "certificates already present in $OUT"
  exit 0
fi

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout ca.key -out ca.pem \
  -subj "/CN=pyppetdb-benchmark-ca" 2>/dev/null

cat > server.cnf <<'CNF'
[req]
distinguished_name = dn
[dn]
[ext]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:localhost, DNS:openvoxdb, DNS:pyppetdb, IP:127.0.0.1
CNF

openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr \
  -subj "/CN=localhost" 2>/dev/null
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out server.crt -days 3650 -extfile server.cnf -extensions ext 2>/dev/null

cat > client.cnf <<'CNF'
[req]
distinguished_name = dn
[dn]
[ext]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
CNF

openssl req -newkey rsa:2048 -nodes -keyout client.key -out client.csr \
  -subj "/CN=bench-client" 2>/dev/null
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out client.crt -days 3650 -extfile client.cnf -extensions ext 2>/dev/null

rm -f server.csr client.csr server.cnf client.cnf
chmod 644 *.key *.crt *.pem
echo "wrote CA, server and client certificates to $OUT"
