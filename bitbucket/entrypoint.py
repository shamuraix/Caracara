#!/usr/bin/env python3
"""Container entrypoint for Bitbucket Data Center."""

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
    install_dir = env_str("BITBUCKET_INSTALL_DIR", "/opt/atlassian/bitbucket")
    home = env_str("BITBUCKET_HOME", "/var/atlassian/application-data/bitbucket")
    shared_home = env_str("BITBUCKET_SHARED_HOME", f"{home}/shared")
    user = env_str("RUN_USER", "bitbucket")
    group = env_str("RUN_GROUP", "bitbucket")
    force = env_bool("ATL_FORCE_CFG_UPDATE", False)
    search_enabled = env_bool("SEARCH_ENABLED", env_bool("ELASTICSEARCH_ENABLED", True))

    prepare_home(home, user, group, extra_dirs=[shared_home])

    ctx = template_context()
    ctx.setdefault("BITBUCKET_SHARED_HOME", shared_home)
    ctx.setdefault("SERVER_PORT", "7990")
    ctx.setdefault("SERVER_CONTEXT_PATH", "/")

    have_db = bool(ctx.get("JDBC_URL") or ctx.get("ATL_JDBC_URL"))
    if have_db:
        # Accept both the Bitbucket-style and the ATL_* names used by Jira/Confluence.
        ctx.setdefault("JDBC_URL", ctx.get("ATL_JDBC_URL", ""))
        ctx.setdefault("JDBC_USER", ctx.get("ATL_JDBC_USER", ""))
        ctx.setdefault("JDBC_PASSWORD", ctx.get("ATL_JDBC_PASSWORD", ""))
        ctx.setdefault("JDBC_DRIVER", ctx.get("ATL_DB_DRIVER", ""))
        if not ctx["JDBC_DRIVER"]:
            raise EntrypointError("JDBC_URL is set but neither JDBC_DRIVER nor ATL_DB_TYPE is")

    props = f"{shared_home}/bitbucket.properties"
    specs = [
        ("bitbucket.properties.j2", props, True, force or not os.path.exists(props)),
    ]
    render_all(specs, ctx)

    if argv[1:] and argv[1] != "/entrypoint.py":
        cmd = argv[1:]
    else:
        cmd = [f"{install_dir}/bin/start-bitbucket.sh", "-fg"]
        if not search_enabled:
            cmd.insert(1, "--no-search")
    log.info("starting Bitbucket from %s with home %s", install_dir, home)
    exec_app(cmd, user, group, cwd=home)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except EntrypointError as exc:
        log.error("%s", exc)
        sys.exit(1)
