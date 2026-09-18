# syntax=docker/dockerfile:1.7
# Bitbucket Data Center on UBI 9 minimal.
#
# Build context is the repository root (shared/ is needed):
#   buildctl build --frontend dockerfile.v0 --local context=. --local dockerfile=bitbucket ...
#
# Runtime notes: the bundled OpenSearch needs vm.max_map_count >= 262144 on
# the node (a sysctl DaemonSet or a privileged init container); set
# SEARCH_ENABLED=false to run search separately.
ARG ART=artifactory.example.com
FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS runtime

ARG ART
ARG TARGETARCH
ARG VERSION=9.4.5
# sha256 of the product tarball (scripts/pin-version.sh); the build fails when empty.
ARG SHA256
ARG ARTEFACT=atlassian-bitbucket
ARG DOWNLOAD_BASE=https://${ART}/artifactory/generic-atlassian-remote/software/stash/downloads
# Bitbucket 9.x supports Java 17 and 21.
ARG JAVA_PACKAGE=java-17-openjdk-headless

ENV RUN_USER=bitbucket \
    RUN_GROUP=bitbucket \
    RUN_UID=2003 \
    RUN_GID=2003 \
    BITBUCKET_HOME=/var/atlassian/application-data/bitbucket \
    BITBUCKET_INSTALL_DIR=/opt/atlassian/bitbucket \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/jre

LABEL org.opencontainers.image.title="Atlassian Bitbucket Data Center" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.base.name="ubi9/ubi-minimal" \
      org.opencontainers.image.vendor="Atlassian (product); platform team (image)" \
      io.caracara.product="bitbucket"

COPY shared/entrypoint_helpers.py shared/shutdown-wait.sh bitbucket/entrypoint.py /
COPY shared/support /opt/atlassian/support
COPY bitbucket/config/ /opt/atlassian/etc/

ADD --checksum=sha256:${SHA256} \
    ${DOWNLOAD_BASE}/${ARTEFACT}-${VERSION}.tar.gz /tmp/product.tar.gz

# git (>= 2.31) is required for hosting; openssh-clients for git+ssh mirrors
# and hooks.  Bitbucket ships its own embedded SSH server, so openssh-server is
# not installed (smaller CVE surface).  /var/lib/rpm is kept for Trivy and Copa.
RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y upgrade --refresh --best --nodocs --setopt=install_weak_deps=0 \
 && microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      ${JAVA_PACKAGE} git openssh-clients fontconfig python3 python3-jinja2 tini procps-ng which shadow-utils tar gzip \
 && groupadd --gid ${RUN_GID} ${RUN_GROUP} \
 && useradd --uid ${RUN_UID} --gid ${RUN_GID} --home-dir ${BITBUCKET_HOME} --create-home --shell /bin/bash ${RUN_USER} \
 && mkdir -p ${BITBUCKET_INSTALL_DIR} ${BITBUCKET_HOME}/shared \
 && tar -xzf /tmp/product.tar.gz --strip-components=1 -C ${BITBUCKET_INSTALL_DIR} && rm /tmp/product.tar.gz \
 && chmod +x /entrypoint.py /shutdown-wait.sh /opt/atlassian/support/*.sh \
 && chown -R ${RUN_USER}:${RUN_GROUP} ${BITBUCKET_INSTALL_DIR} ${BITBUCKET_HOME} \
 && chmod -R u=rwX,g=rX,o=rX ${BITBUCKET_INSTALL_DIR} && chmod 0750 ${BITBUCKET_HOME} \
 && microdnf clean all

VOLUME ["${BITBUCKET_HOME}"]
USER ${RUN_USER}
WORKDIR ${BITBUCKET_HOME}
EXPOSE 7990 7999
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/entrypoint.py"]
