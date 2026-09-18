#!/usr/bin/env bash
# Generate a private CA plus server and client certificates for buildkitd mTLS
# and print/apply the two Kubernetes Secrets the manifests expect:
#   buildkitd-server-certs   (namespace buildkit)      ca.pem cert.pem key.pem
#   buildkit-client-certs    (runner/agent namespaces) ca.pem cert.pem key.pem
#
# Usage: scripts/gen-buildkit-certs.sh [out-dir] [server-dns-name] [client-namespace ...]
# Apply with: kubectl apply -f <out-dir>/*.yaml
# For production prefer cert-manager (k8s/buildkit/certificates.yaml); this is
# the bootstrap path and rotates nothing.
set -euo pipefail
out="${1:-./certs}"
server_dns="${2:-buildkitd.buildkit.svc}"
shift 2 2>/dev/null || true
client_namespaces=("${@:-gitlab-runner}")
days="${CERT_DAYS:-365}"

command -v openssl >/dev/null || { echo "openssl required" >&2; exit 1; }
mkdir -p "${out}" && cd "${out}"

openssl req -x509 -newkey rsa:4096 -nodes -sha256 -days "${days}" \
  -subj "/CN=buildkit-ca" -keyout ca-key.pem -out ca.pem >/dev/null 2>&1

openssl req -newkey rsa:4096 -nodes -sha256 -subj "/CN=${server_dns}" \
  -keyout server-key.pem -out server.csr >/dev/null 2>&1
cat > server.ext <<EXT
subjectAltName=DNS:${server_dns},DNS:${server_dns%%.*},DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
EXT
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
  -days "${days}" -sha256 -extfile server.ext -out server-cert.pem >/dev/null 2>&1

openssl req -newkey rsa:4096 -nodes -sha256 -subj "/CN=buildkit-client" \
  -keyout client-key.pem -out client.csr >/dev/null 2>&1
printf 'extendedKeyUsage=clientAuth\n' > client.ext
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
  -days "${days}" -sha256 -extfile client.ext -out client-cert.pem >/dev/null 2>&1
rm -f ./*.csr ./*.ext

secret() {
  local name="$1" ns="$2" cert="$3" key="$4"
  cat <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: ${name}
  namespace: ${ns}
type: Opaque
data:
  ca.pem: $(base64 -w0 ca.pem)
  cert.pem: $(base64 -w0 "${cert}")
  key.pem: $(base64 -w0 "${key}")
YAML
}

secret buildkitd-server-certs buildkit server-cert.pem server-key.pem > buildkitd-server-certs.yaml
for ns in "${client_namespaces[@]}"; do
  secret buildkit-client-certs "${ns}" client-cert.pem client-key.pem > "buildkit-client-certs-${ns}.yaml"
done
chmod 0600 ./*-key.pem
echo "certificates and Secret manifests written to ${out}/ (keep ca-key.pem offline)"
