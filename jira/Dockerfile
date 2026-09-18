# syntax=docker/dockerfile:1.7
# Jira Software / Jira Service Management Data Center on UBI 9 minimal.
#
# Build context is the repository root (shared/ is needed):
#   buildctl build --frontend dockerfile.v0 --local context=. --local dockerfile=jira ...
#
# The FROM line carries a tag and, once Renovate has run, a digest.  Red Hat
# republishes the tag, so the digest is what makes the build reproducible;
# Renovate bumps it and opens a merge request on every base change.
ARG ART=artifactory.example.com
FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS runtime

ARG ART
ARG TARGETARCH
ARG VERSION=11.3.11
# sha256 of the product tarball, from product-downloads' .sha256 file (scripts/pin-version.sh).
# Left empty on purpose: ADD --checksum fails the build when it is not supplied.
ARG SHA256
# atlassian-jira-software for Jira Software, atlassian-servicedesk for JSM.
ARG ARTEFACT=atlassian-jira-software
ARG DOWNLOAD_BASE=https://${ART}/artifactory/generic-atlassian-remote/software/jira/downloads
# Jira 11 requires Java 21; the JDK is an RPM so Copa can patch it.
ARG JAVA_PACKAGE=java-21-openjdk-headless

ENV RUN_USER=jira \
    RUN_GROUP=jira \
    RUN_UID=2001 \
    RUN_GID=2001 \
    JIRA_HOME=/var/atlassian/application-data/jira \
    JIRA_INSTALL_DIR=/opt/atlassian/jira \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/jre

LABEL org.opencontainers.image.title="Atlassian Jira Data Center" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.base.name="ubi9/ubi-minimal" \
      org.opencontainers.image.vendor="Atlassian (product); platform team (image)" \
      io.caracara.product="jira"

# Entrypoint and support scripts (shared/ + product-specific entrypoint).
COPY shared/entrypoint_helpers.py shared/shutdown-wait.sh jira/entrypoint.py /
COPY shared/support /opt/atlassian/support
COPY jira/config/ /opt/atlassian/etc/

# Checksum-verified download through the Artifactory generic remote; the build fails on mismatch.
ADD --checksum=sha256:${SHA256} \
    ${DOWNLOAD_BASE}/${ARTEFACT}-${VERSION}.tar.gz /tmp/product.tar.gz

# One layer: OS upgrade (this is where the weekly rebuild removes CVEs), runtime
# packages, user, product install, and cache cleanup.  /var/lib/rpm is kept so
# Trivy and Copa know what is installed; never `rpm -e --nodeps` or remove rpm/microdnf.
RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y upgrade --refresh --best --nodocs --setopt=install_weak_deps=0 \
 && microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      ${JAVA_PACKAGE} fontconfig python3 python3-jinja2 tini procps-ng which shadow-utils tar gzip \
 && groupadd --gid ${RUN_GID} ${RUN_GROUP} \
 && useradd --uid ${RUN_UID} --gid ${RUN_GID} --home-dir ${JIRA_HOME} --create-home --shell /bin/bash ${RUN_USER} \
 && mkdir -p ${JIRA_INSTALL_DIR} \
 && tar -xzf /tmp/product.tar.gz --strip-components=1 -C ${JIRA_INSTALL_DIR} && rm /tmp/product.tar.gz \
 && sed -i 's/^JVM_SUPPORT_RECOMMENDED_ARGS=""$/: ${JVM_SUPPORT_RECOMMENDED_ARGS:=""}/' ${JIRA_INSTALL_DIR}/bin/setenv.sh \
 && sed -i 's/^JVM_\(.*\)_MEMORY="\(.*\)"$/: ${JVM_\1_MEMORY:=\2}/' ${JIRA_INSTALL_DIR}/bin/setenv.sh \
 && chmod +x /entrypoint.py /shutdown-wait.sh /opt/atlassian/support/*.sh \
 && chown -R ${RUN_USER}:${RUN_GROUP} ${JIRA_INSTALL_DIR} ${JIRA_HOME} \
 && chmod -R u=rwX,g=rX,o=rX ${JIRA_INSTALL_DIR} && chmod 0750 ${JIRA_HOME} \
 && microdnf clean all

VOLUME ["${JIRA_HOME}"]
USER ${RUN_USER}
WORKDIR ${JIRA_HOME}
EXPOSE 8080 40001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/entrypoint.py"]
