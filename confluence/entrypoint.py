#!/usr/bin/env python3
"""Container entrypoint for Confluence Data Center."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entrypoint_helpers import (  # noqa: E402
    EntrypointError,
    env_bool,
    env_str,
    exec_app,
    log,
    prepare_home,
    render_all,
    setup_logging,
    template_context,
)


def main(argv: list[str]) -> None:
    setup_logging()
    install_dir = env_str("CONFLUENCE_INSTALL_DIR", "/opt/atlassian/confluence")
    home = env_str("CONFLUENCE_HOME", "/var/atlassian/application-data/confluence")
    shared_home = env_str("CONFLUENCE_SHARED_HOME", f"{home}/shared-home")
    user = env_str("RUN_USER", "confluence")
    group = env_str("RUN_GROUP", "confluence")
    force = env_bool("ATL_FORCE_CFG_UPDATE", False)
    clustered = bool(env_str("ATL_CLUSTER_TYPE"))  # tcp_ip, multicast, kubernetes or aws

    prepare_home(home, user, group, extra_dirs=[shared_home] if clustered else [])

    ctx = template_context()
    ctx.setdefault("CONFLUENCE_SHARED_HOME", shared_home)
    ctx.setdefault("ATL_TOMCAT_PORT", "8090")
    ctx.setdefault("ATL_TOMCAT_CONTEXTPATH", "")
    ctx["ATL_CLUSTERED"] = "true" if clustered else "false"
    ctx.setdefault("ATL_PRODUCT_HOME", home)

    have_db = bool(ctx.get("ATL_JDBC_URL"))
    if have_db and not ctx.get("ATL_DB_TYPE"):
        raise EntrypointError("ATL_JDBC_URL is set but ATL_DB_TYPE is not (postgresql, mysql, oracle, mssql)")

    cfg_exists = os.path.exists(f"{home}/confluence.cfg.xml")
    specs = [
        ("server.xml.j2", f"{install_dir}/conf/server.xml", True, True),
        ("confluence-init.properties.j2", f"{install_dir}/confluence/WEB-INF/classes/confluence-init.properties", True, True),
        ("confluence.cfg.xml.j2", f"{home}/confluence.cfg.xml", have_db, force or not cfg_exists),
    ]
    render_all(specs, ctx)

    if argv[1:] and argv[1] != "/entrypoint.py":
        cmd = argv[1:]
    else:
        cmd = [f"{install_dir}/bin/start-confluence.sh", "-fg"]
    log.info("starting Confluence from %s with home %s", install_dir, home)
    exec_app(cmd, user, group, cwd=home)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except EntrypointError as exc:
        log.error("%s", exc)
        sys.exit(1)
