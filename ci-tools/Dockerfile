# syntax=docker/dockerfile:1.7
# ci-tools: the single job image used by GitLab CI and Jenkins.
# Contains buildctl, trivy, copa, cosign, crane, jq, python3, yamllint and
# shellcheck.  No Docker client, no daemon.
#
# buildctl, trivy and cosign are copied from their upstream images (pulled
# through Artifactory; Renovate bumps the ARG versions).  copa and crane are
# GitHub release tarballs pinned in hardening_manifest.yaml and verified with
# ADD --checksum; scripts/build.sh ci-tools passes the URL/sha256 build args.
ARG ART=artifactory.example.com
ARG TARGETARCH

# renovate: datasource=docker depName=moby/buildkit
ARG BUILDKIT_VERSION=v0.18.2
# renovate: datasource=docker depName=aquasec/trivy
ARG TRIVY_VERSION=0.61.0
# renovate: datasource=docker depName=ghcr.io/sigstore/cosign/cosign
ARG COSIGN_VERSION=v2.4.3

FROM ${ART}/docker-hub-remote/moby/buildkit:${BUILDKIT_VERSION} AS buildkit
FROM ${ART}/docker-hub-remote/aquasec/trivy:${TRIVY_VERSION} AS trivy
FROM ${ART}/docker-ghcr-remote/sigstore/cosign/cosign:${COSIGN_VERSION} AS cosign

# --- release tarballs, one fetch stage per architecture ---
FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS fetch-amd64
ARG COPA_AMD64_URL
ARG COPA_AMD64_SHA256
ARG CRANE_AMD64_URL
ARG CRANE_AMD64_SHA256
ADD --checksum=sha256:${COPA_AMD64_SHA256} ${COPA_AMD64_URL} /tmp/copa.tgz
ADD --checksum=sha256:${CRANE_AMD64_SHA256} ${CRANE_AMD64_URL} /tmp/crane.tgz
RUN mkdir -p /out && tar -xzf /tmp/copa.tgz -C /out copa && tar -xzf /tmp/crane.tgz -C /out crane

FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS fetch-arm64
ARG COPA_ARM64_URL
ARG COPA_ARM64_SHA256
ARG CRANE_ARM64_URL
ARG CRANE_ARM64_SHA256
ADD --checksum=sha256:${COPA_ARM64_SHA256} ${COPA_ARM64_URL} /tmp/copa.tgz
ADD --checksum=sha256:${CRANE_ARM64_SHA256} ${CRANE_ARM64_URL} /tmp/crane.tgz
RUN mkdir -p /out && tar -xzf /tmp/copa.tgz -C /out copa && tar -xzf /tmp/crane.tgz -C /out crane

FROM fetch-${TARGETARCH} AS fetch

# --- tools image ---
FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS tools
ARG ART
ARG TARGETARCH
ARG PYPI_INDEX=https://${ART}/artifactory/api/pypi/pypi-remote/simple

COPY --from=buildkit /usr/bin/buildctl /usr/local/bin/buildctl
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=cosign /ko-app/cosign /usr/local/bin/cosign
COPY --from=fetch --chmod=0755 /out/copa /out/crane /usr/local/bin/

RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y upgrade --refresh --best --nodocs --setopt=install_weak_deps=0 \
 && microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      jq git python3 python3-pip python3-pyyaml tar gzip ca-certificates shadow-utils \
 && microdnf clean all \
 && pip3 install --no-cache-dir --index-url "${PYPI_INDEX}" yamllint shellcheck-py \
 && useradd --uid 1000 --create-home --shell /bin/bash ci \
 && buildctl --version && trivy --version && copa --version && cosign version && crane version \
 && yamllint --version && shellcheck --version

# The pipeline scripts run from the repository checkout, not from this image.
ENV TRIVY_CACHE_DIR=/home/ci/.cache/trivy \
    DOCKER_CONFIG=/home/ci/.docker
USER ci
WORKDIR /home/ci
CMD ["/bin/bash"]
