# syntax=docker/dockerfile:1.7
# ci-tools: the single job image used by GitLab CI and Jenkins.
# Contains buildctl, trivy, copa, cosign, crane, jq, python3 and the repo's
# scripts' runtime dependencies.  No Docker client, no daemon.
#
# Every upstream is pulled through Artifactory; the GitHub release tarballs go
# through a generic remote (generic-github-remote -> https://github.com).
# Renovate bumps the ARG versions below.
ARG ART=artifactory.example.com

# renovate: datasource=docker depName=moby/buildkit
ARG BUILDKIT_VERSION=v0.18.2
# renovate: datasource=docker depName=aquasec/trivy
ARG TRIVY_VERSION=0.61.0
# renovate: datasource=docker depName=ghcr.io/sigstore/cosign/cosign
ARG COSIGN_VERSION=v2.4.3

FROM ${ART}/docker-hub-remote/moby/buildkit:${BUILDKIT_VERSION} AS buildkit
FROM ${ART}/docker-hub-remote/aquasec/trivy:${TRIVY_VERSION} AS trivy
FROM ${ART}/docker-ghcr-remote/sigstore/cosign/cosign:${COSIGN_VERSION} AS cosign

FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS tools
ARG ART
ARG TARGETARCH
# renovate: datasource=github-releases depName=project-copacetic/copacetic
ARG COPA_VERSION=0.10.0
# renovate: datasource=github-releases depName=google/go-containerregistry
ARG CRANE_VERSION=v0.20.3
ARG GITHUB_BASE=https://${ART}/artifactory/generic-github-remote
ARG PYPI_INDEX=https://${ART}/artifactory/api/pypi/pypi-remote/simple

COPY --from=buildkit /usr/bin/buildctl /usr/local/bin/buildctl
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=cosign /ko-app/cosign /usr/local/bin/cosign

# copa and crane publish per-arch tarballs; crane names arm64 "arm64" and amd64 "x86_64".
RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y upgrade --refresh --best --nodocs --setopt=install_weak_deps=0 \
 && microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      jq git python3 python3-pip python3-pyyaml tar gzip ca-certificates shadow-utils \
 && microdnf clean all \
 && pip3 install --no-cache-dir --index-url "${PYPI_INDEX}" yamllint shellcheck-py \
 && set -eux; \
    case "${TARGETARCH}" in amd64) crane_arch=x86_64 ;; arm64) crane_arch=arm64 ;; *) echo "unsupported arch ${TARGETARCH}" >&2; exit 1 ;; esac; \
    curl -fsSL "${GITHUB_BASE}/project-copacetic/copacetic/releases/download/v${COPA_VERSION}/copa_${COPA_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin copa; \
    curl -fsSL "${GITHUB_BASE}/google/go-containerregistry/releases/download/${CRANE_VERSION}/go-containerregistry_Linux_${crane_arch}.tar.gz" \
      | tar -xz -C /usr/local/bin crane; \
    chmod 0755 /usr/local/bin/copa /usr/local/bin/crane; \
    useradd --uid 1000 --create-home --shell /bin/bash ci; \
    buildctl --version; trivy --version; copa --version; cosign version; crane version; \
    yamllint --version; shellcheck --version

# The pipeline scripts run from the repository checkout, not from this image.
ENV TRIVY_CACHE_DIR=/home/ci/.cache/trivy \
    DOCKER_CONFIG=/home/ci/.docker
USER ci
WORKDIR /home/ci
CMD ["/bin/bash"]
