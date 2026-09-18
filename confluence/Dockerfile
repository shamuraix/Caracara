# syntax=docker/dockerfile:1.7
# Confluence Data Center on UBI 9 minimal.
#
# Resources (product tarball, tini) come from hardening_manifest.yaml via
# scripts/build.sh as <ARG>_URL / <ARG>_SHA256 build args; ADD --checksum
# verifies each one.  Build from the repository root: scripts/build.sh confluence/lts
ARG ART=artifactory.example.com
ARG TARGETARCH

FROM scratch AS tini-amd64
ARG TINI_AMD64_URL
ARG TINI_AMD64_SHA256
ADD --checksum=sha256:${TINI_AMD64_SHA256} --chmod=0755 ${TINI_AMD64_URL} /tini

FROM scratch AS tini-arm64
ARG TINI_ARM64_URL
ARG TINI_ARM64_SHA256
ADD --checksum=sha256:${TINI_ARM64_SHA256} --chmod=0755 ${TINI_ARM64_URL} /tini

FROM tini-${TARGETARCH} AS tini

FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS runtime

ARG TARGETARCH
ARG VERSION
ARG ARTEFACT=atlassian-confluence
# Confluence 10.x runs on Java 21 (the manifest's JAVA_PACKAGE arg overrides this default).
ARG JAVA_PACKAGE=java-21-openjdk-headless
ARG PRODUCT_URL
ARG PRODUCT_SHA256

ENV RUN_USER=confluence \
    RUN_GROUP=confluence \
    RUN_UID=2002 \
    RUN_GID=2002 \
    CONFLUENCE_HOME=/var/atlassian/application-data/confluence \
    CONFLUENCE_INSTALL_DIR=/opt/atlassian/confluence \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/jre

LABEL org.opencontainers.image.title="Atlassian Confluence Data Center" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.base.name="ubi9/ubi-minimal" \
      org.opencontainers.image.vendor="Atlassian (product); platform team (image)" \
      io.caracara.product="confluence"

COPY --from=tini /tini /usr/bin/tini
COPY shared/entrypoint_helpers.py shared/shutdown-wait.sh confluence/entrypoint.py /
COPY shared/support /opt/atlassian/support
COPY confluence/config/ /opt/atlassian/etc/

ADD --checksum=sha256:${PRODUCT_SHA256} ${PRODUCT_URL} /tmp/product.tar.gz

# procps-ng is required by Confluence's start scripts (ps); fontconfig by the
# bundled Synchrony/diagram rendering.  /var/lib/rpm is kept for Trivy and Copa.
RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y upgrade --refresh --best --nodocs --setopt=install_weak_deps=0 \
 && microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      ${JAVA_PACKAGE} fontconfig python3 python3-jinja2 procps-ng which shadow-utils tar gzip \
 && groupadd --gid ${RUN_GID} ${RUN_GROUP} \
 && useradd --uid ${RUN_UID} --gid ${RUN_GID} --home-dir ${CONFLUENCE_HOME} --create-home --shell /bin/bash ${RUN_USER} \
 && mkdir -p ${CONFLUENCE_INSTALL_DIR} \
 && tar -xzf /tmp/product.tar.gz --strip-components=1 -C ${CONFLUENCE_INSTALL_DIR} && rm /tmp/product.tar.gz \
 && sed -i 's/^JVM_SUPPORT_RECOMMENDED_ARGS=""$/: ${JVM_SUPPORT_RECOMMENDED_ARGS:=""}/' ${CONFLUENCE_INSTALL_DIR}/bin/setenv.sh \
 && sed -i 's/^JVM_\(.*\)_MEMORY="\(.*\)"$/: ${JVM_\1_MEMORY:=\2}/' ${CONFLUENCE_INSTALL_DIR}/bin/setenv.sh \
 && sed -i 's/^CATALINA_OPTS="-XX:ReservedCodeCacheSize=\(.*\)"$/: ${CODE_CACHE_SIZE:=\1}\nCATALINA_OPTS="-XX:ReservedCodeCacheSize=${CODE_CACHE_SIZE}"/' ${CONFLUENCE_INSTALL_DIR}/bin/setenv.sh \
 && chmod +x /entrypoint.py /shutdown-wait.sh /opt/atlassian/support/*.sh \
 && chown -R ${RUN_USER}:${RUN_GROUP} ${CONFLUENCE_INSTALL_DIR} ${CONFLUENCE_HOME} \
 && chmod -R u=rwX,g=rX,o=rX ${CONFLUENCE_INSTALL_DIR} && chmod 0750 ${CONFLUENCE_HOME} \
 && microdnf clean all \
 && /usr/bin/tini --version

VOLUME ["${CONFLUENCE_HOME}"]
USER ${RUN_USER}
WORKDIR ${CONFLUENCE_HOME}
EXPOSE 8090 8091
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/entrypoint.py"]
