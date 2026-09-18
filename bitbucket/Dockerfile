# syntax=docker/dockerfile:1.7
# Bitbucket Data Center on UBI 9 minimal.
#
# Resources (product tarball, tini, git source) come from
# hardening_manifest.yaml via scripts/build.sh as <ARG>_URL / <ARG>_SHA256
# build args; ADD --checksum verifies each one.  git is compiled from the
# pinned kernel.org tarball in the git-builder stage, as Iron Bank does, so
# the version Bitbucket hosts with is chosen here and not by the UBI repo.
# Build from the repository root: scripts/build.sh bitbucket/lts
#
# Runtime notes: the bundled OpenSearch needs vm.max_map_count >= 262144 on
# the node (k8s/policy/sysctl-max-map-count.yaml); set SEARCH_ENABLED=false
# to run search separately.
ARG ART=artifactory.example.com
ARG TARGETARCH

# --- tini (one stage per architecture; FROM tini-${TARGETARCH} selects) ---
FROM scratch AS tini-amd64
ARG TINI_AMD64_URL
ARG TINI_AMD64_SHA256
ADD --checksum=sha256:${TINI_AMD64_SHA256} --chmod=0755 ${TINI_AMD64_URL} /tini

FROM scratch AS tini-arm64
ARG TINI_ARM64_URL
ARG TINI_ARM64_SHA256
ADD --checksum=sha256:${TINI_ARM64_SHA256} --chmod=0755 ${TINI_ARM64_URL} /tini

FROM tini-${TARGETARCH} AS tini

# --- git from source ---
FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS git-builder
ARG TARGETARCH
ARG GIT_URL
ARG GIT_SHA256
ADD --checksum=sha256:${GIT_SHA256} ${GIT_URL} /tmp/git.tar.xz
# NO_PERL/NO_TCLTK/NO_GETTEXT/NO_PYTHON: hosting needs the core commands and
# the https/ssh transports only; USE_LIBPCRE2 for `git grep -P` and pickaxe.
RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      gcc make xz tar libcurl-devel openssl-devel zlib-devel expat-devel pcre2-devel \
 && mkdir -p /tmp/git && tar -xJf /tmp/git.tar.xz --strip-components=1 -C /tmp/git \
 && cd /tmp/git \
 && make -j"$(nproc)" prefix=/opt/git NO_PERL=1 NO_TCLTK=1 NO_GETTEXT=1 NO_PYTHON=1 USE_LIBPCRE2=1 \
      CFLAGS="-O2 -g0 -fstack-protector-strong -D_FORTIFY_SOURCE=2" all \
 && make prefix=/opt/git NO_PERL=1 NO_TCLTK=1 NO_GETTEXT=1 NO_PYTHON=1 USE_LIBPCRE2=1 install \
 && strip /opt/git/bin/* /opt/git/libexec/git-core/* 2>/dev/null || true \
 && /opt/git/bin/git --version

# --- runtime ---
FROM ${ART}/docker-redhat-remote/ubi9/ubi-minimal:9.7 AS runtime

ARG TARGETARCH
ARG VERSION
ARG ARTEFACT=atlassian-bitbucket
# Bitbucket 10.x runs on Java 21 (the manifest's JAVA_PACKAGE arg overrides this default).
ARG JAVA_PACKAGE=java-21-openjdk-headless
ARG PRODUCT_URL
ARG PRODUCT_SHA256

ENV RUN_USER=bitbucket \
    RUN_GROUP=bitbucket \
    RUN_UID=2003 \
    RUN_GID=2003 \
    BITBUCKET_HOME=/var/atlassian/application-data/bitbucket \
    BITBUCKET_INSTALL_DIR=/opt/atlassian/bitbucket \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/jre \
    PATH=/opt/git/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

LABEL org.opencontainers.image.title="Atlassian Bitbucket Data Center" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.base.name="ubi9/ubi-minimal" \
      org.opencontainers.image.vendor="Atlassian (product); platform team (image)" \
      io.caracara.product="bitbucket"

COPY --from=tini /tini /usr/bin/tini
COPY --from=git-builder /opt/git /opt/git
COPY shared/entrypoint_helpers.py shared/shutdown-wait.sh bitbucket/entrypoint.py /
COPY shared/support /opt/atlassian/support
COPY bitbucket/config/ /opt/atlassian/etc/

ADD --checksum=sha256:${PRODUCT_SHA256} ${PRODUCT_URL} /tmp/product.tar.gz

# git's runtime libraries (libcurl, openssl, zlib are in the base; expat and
# pcre2 are not); openssh-clients for git+ssh mirrors and hooks.  Bitbucket
# ships its own embedded SSH server, so openssh-server is not installed.
# /var/lib/rpm is kept for Trivy and Copa.
RUN --mount=type=cache,id=dnf-${TARGETARCH},target=/var/cache/dnf,sharing=locked \
    microdnf -y upgrade --refresh --best --nodocs --setopt=install_weak_deps=0 \
 && microdnf -y install --nodocs --setopt=install_weak_deps=0 \
      ${JAVA_PACKAGE} expat pcre2 openssh-clients fontconfig python3 python3-jinja2 procps-ng which shadow-utils tar gzip \
 && groupadd --gid ${RUN_GID} ${RUN_GROUP} \
 && useradd --uid ${RUN_UID} --gid ${RUN_GID} --home-dir ${BITBUCKET_HOME} --create-home --shell /bin/bash ${RUN_USER} \
 && mkdir -p ${BITBUCKET_INSTALL_DIR} ${BITBUCKET_HOME}/shared \
 && tar -xzf /tmp/product.tar.gz --strip-components=1 -C ${BITBUCKET_INSTALL_DIR} && rm /tmp/product.tar.gz \
 && ln -s /opt/git/bin/git /usr/bin/git \
 && chmod +x /entrypoint.py /shutdown-wait.sh /opt/atlassian/support/*.sh \
 && chown -R ${RUN_USER}:${RUN_GROUP} ${BITBUCKET_INSTALL_DIR} ${BITBUCKET_HOME} \
 && chmod -R u=rwX,g=rX,o=rX ${BITBUCKET_INSTALL_DIR} && chmod 0750 ${BITBUCKET_HOME} \
 && microdnf clean all \
 && /usr/bin/tini --version && git --version

VOLUME ["${BITBUCKET_HOME}"]
USER ${RUN_USER}
WORKDIR ${BITBUCKET_HOME}
EXPOSE 7990 7999
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/entrypoint.py"]
