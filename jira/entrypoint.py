#!/usr/bin/env python3
"""Container entrypoint for Jira Software / Jira Service Management Data Center."""

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
    install_dir = env_str("JIRA_INSTALL_DIR", "/opt/atlassian/jira")
    home = env_str("JIRA_HOME", "/var/atlassian/application-data/jira")
    shared_home = env_str("JIRA_SHARED_HOME", f"{home}/shared")
    user = env_str("RUN_USER", "jira")
    group = env_str("RUN_GROUP", "jira")
    force = env_bool("ATL_FORCE_CFG_UPDATE", False)
    clustered = env_bool("CLUSTERED", False)

    prepare_home(home, user, group, extra_dirs=[shared_home] if clustered else [])

    ctx = template_context()
    ctx.setdefault("JIRA_SHARED_HOME", shared_home)
    ctx.setdefault("ATL_TOMCAT_PORT", "8080")
    ctx.setdefault("ATL_TOMCAT_CONTEXTPATH", "")

    have_db = bool(ctx.get("ATL_JDBC_URL"))
    if have_db and not ctx.get("ATL_DB_TYPE"):
        raise EntrypointError("ATL_JDBC_URL is set but ATL_DB_TYPE is not (postgres72, mysql8, oracle10g, mssql)")

    specs = [
        ("server.xml.j2", f"{install_dir}/conf/server.xml", True, True),
        ("dbconfig.xml.j2", f"{home}/dbconfig.xml", have_db, force or not os.path.exists(f"{home}/dbconfig.xml")),
        ("cluster.properties.j2", f"{home}/cluster.properties", clustered, True),
        ("jira-config.properties.j2", f"{home}/jira-config.properties", True, force or not os.path.exists(f"{home}/jira-config.properties")),
    ]
    render_all(specs, ctx)

    if argv[1:] and argv[1] != "/entrypoint.py":
        cmd = argv[1:]
    else:
        cmd = [f"{install_dir}/bin/start-jira.sh", "-fg"]
    log.info("starting Jira from %s with home %s", install_dir, home)
    exec_app(cmd, user, group, cwd=home)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except EntrypointError as exc:
        log.error("%s", exc)
        sys.exit(1)
