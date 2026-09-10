#!/bin/bash
# Mounted into /container-custom-entrypoint.d/. Enables HTTPS with client
# certificate verification using the certificates mounted at $SSLDIR.
set -e

INI=/etc/puppetlabs/puppetdb/conf.d/jetty.ini

sed -i 's|^# ssl-host = .*|ssl-host = 0.0.0.0|' "$INI"
sed -i 's|^# ssl-port = .*|ssl-port = 8081|' "$INI"
sed -i "s|^# ssl-key = .*|ssl-key = ${SSLDIR}/private_keys/server.key|" "$INI"
sed -i "s|^# ssl-cert = .*|ssl-cert = ${SSLDIR}/certs/server.crt|" "$INI"
sed -i "s|^# ssl-ca-cert = .*|ssl-ca-cert = ${SSLDIR}/certs/ca.pem|" "$INI"
sed -i 's|^client-auth = .*|client-auth = need|' "$INI"

echo "jetty.ini configured for mTLS:"
grep -E '^(ssl-|client-auth|port|host)' "$INI"
