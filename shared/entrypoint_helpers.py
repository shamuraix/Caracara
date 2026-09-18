"""Helpers shared by the Jira, Confluence and Bitbucket container entrypoints.

The product entrypoints (``<product>/entrypoint.py``) declare which Jinja2
templates to render and which start command to exec; everything else lives
here so the three images behave the same way.

Design rules:

* Configuration comes from environment variables only.  Templates receive the
  whole environment, so any ``ATL_*`` or ``JVM_*`` variable can be used.
* The container normally runs as the unprivileged ``RUN_USER`` set in the
  Dockerfile.  If it is started as root (for example to fix permissions on a
  volume that was created by another UID) the entrypoint fixes ownership of
  the home directory and drops privileges before exec'ing the product.
* Secrets (``*_PASSWORD``, ``*_SECRET``, ``*_TOKEN``) are removed from the
  environment before the product starts so they cannot be read from
  ``/proc/<pid>/environ`` or leak into support zips.
"""

from __future__ import annotations

import grp
import logging
import os
import pwd
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import jinja2

log = logging.getLogger("entrypoint")

TEMPLATE_DIR = Path(os.environ.get("ATL_TEMPLATE_DIR", "/opt/atlassian/etc"))
SECURE_VAR_RE = re.compile(r".*(PASSWORD|SECRET|TOKEN|PASSWD)$")

# Jira/Confluence ``database-type`` and Bitbucket ``jdbc.driver`` derivation.
JDBC_DRIVERS: Mapping[str, str] = {
    "postgres72": "org.postgresql.Driver",
    "postgresql": "org.postgresql.Driver",
    "mysql8": "com.mysql.cj.jdbc.Driver",
    "mysql57": "com.mysql.jdbc.Driver",
    "mysql": "com.mysql.cj.jdbc.Driver",
    "oracle10g": "oracle.jdbc.OracleDriver",
    "oracle": "oracle.jdbc.OracleDriver",
    "mssql": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
}

# Confluence hibernate dialects keyed on ATL_DB_TYPE.
HIBERNATE_DIALECTS: Mapping[str, str] = {
    "postgresql": "com.atlassian.confluence.impl.hibernate.dialect.PostgreSQLDialect",
    "postgres72": "com.atlassian.confluence.impl.hibernate.dialect.PostgreSQLDialect",
    "mysql": "com.atlassian.confluence.impl.hibernate.dialect.MySQLDialect",
    "mysql8": "com.atlassian.confluence.impl.hibernate.dialect.MySQLDialect",
    "oracle": "com.atlassian.confluence.impl.hibernate.dialect.OracleDialect",
    "mssql": "com.atlassian.confluence.impl.hibernate.dialect.SQLServerDialect",
}


class EntrypointError(RuntimeError):
    """Raised for configuration problems that should stop the container."""


def setup_logging() -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def str2bool(value: str | None, default: bool = False) -> bool:
    """Parse the usual truthy/falsy spellings; ``None``/empty -> ``default``."""
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise EntrypointError(f"cannot interpret {value!r} as a boolean")


def env_bool(name: str, default: bool = False, environ: Mapping[str, str] | None = None) -> bool:
    environ = os.environ if environ is None else environ
    return str2bool(environ.get(name), default)


def env_str(name: str, default: str = "", environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    return default if value is None or value == "" else value


def template_context(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment plus derived values that every template may want."""
    environ = dict(os.environ if environ is None else environ)
    db_type = environ.get("ATL_DB_TYPE", "").lower()
    if db_type and not environ.get("ATL_DB_DRIVER"):
        driver = JDBC_DRIVERS.get(db_type)
        if driver:
            environ["ATL_DB_DRIVER"] = driver
    if db_type and not environ.get("ATL_DB_DIALECT"):
        dialect = HIBERNATE_DIALECTS.get(db_type)
        if dialect:
            environ["ATL_DB_DIALECT"] = dialect
    environ.setdefault("ATL_CONTAINER_ID", gen_container_id(environ))
    return environ


def gen_container_id(environ: Mapping[str, str] | None = None) -> str:
    """A stable-per-container identifier (used for cluster node ids)."""
    environ = os.environ if environ is None else environ
    hostname = environ.get("HOSTNAME") or os.uname().nodename
    return f"{hostname}-{uuid.uuid4().hex[:8]}"


def unset_secure_vars(environ: Mapping[str, str] | None = None) -> list[str]:
    """Remove password-like variables from ``os.environ`` (or the given mapping)."""
    target = os.environ if environ is None else environ
    removed = [k for k in list(target.keys()) if SECURE_VAR_RE.match(k)]
    for key in removed:
        del target[key]  # type: ignore[union-attr]
    if removed:
        log.info("removed %d secret variable(s) from the environment: %s", len(removed), ", ".join(sorted(removed)))
    return removed


def render_template(
    template: str | Path,
    context: Mapping[str, str],
    template_dir: Path = TEMPLATE_DIR,
) -> str:
    loader = jinja2.FileSystemLoader(str(template_dir))
    env = jinja2.Environment(
        loader=loader,
        undefined=jinja2.ChainableUndefined,
        keep_trailing_newline=True,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["bool"] = lambda v, d=False: str2bool(v, d) if isinstance(v, str) or v is None else bool(v)
    return env.get_template(str(template)).render(**context)


def gen_cfg(
    template: str,
    target: str | Path,
    context: Mapping[str, str],
    *,
    overwrite: bool = True,
    mode: int = 0o640,
    user: str | None = None,
    group: str | None = None,
    template_dir: Path = TEMPLATE_DIR,
) -> bool:
    """Render ``template`` to ``target``.  Returns True when a file was written."""
    target = Path(target)
    if target.exists() and not overwrite:
        log.info("%s exists and overwrite is disabled; leaving it alone", target)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_template(template, context, template_dir=template_dir)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    os.chmod(tmp, mode)
    if user or group:
        shutil.chown(tmp, user=user, group=group)
    os.replace(tmp, target)
    log.info("generated %s from %s", target, template)
    return True


def running_as_root() -> bool:
    return os.geteuid() == 0


def resolve_user(user: str) -> tuple[int, int]:
    try:
        entry = pwd.getpwnam(user)
    except KeyError as exc:
        raise EntrypointError(f"RUN_USER {user!r} does not exist in the image") from exc
    return entry.pw_uid, entry.pw_gid


def set_perms(path: str | Path, user: str, group: str, mode: int = 0o750, recursive: bool = True) -> None:
    """chown/chmod ``path`` (only meaningful when running as root)."""
    path = Path(path)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    shutil.chown(path, user=user, group=group)
    os.chmod(path, mode)
    if not recursive:
        return
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            p = Path(root) / name
            try:
                shutil.chown(p, user=user, group=group)
                st = os.lstat(p)
                if stat.S_ISDIR(st.st_mode):
                    os.chmod(p, (st.st_mode & 0o7777) | stat.S_IRWXU)
            except (OSError, LookupError) as exc:  # pragma: no cover - best effort
                log.warning("could not fix permissions on %s: %s", p, exc)


def check_perms(path: str | Path, uid: int, gid: int, mode: int = os.W_OK | os.R_OK | os.X_OK) -> bool:
    """True when ``uid``/``gid`` can access ``path`` with ``mode``."""
    path = Path(path)
    if not path.exists():
        return False
    st = path.stat()
    if st.st_uid == uid:
        perm = (st.st_mode >> 6) & 0o7
    elif st.st_gid == gid:
        perm = (st.st_mode >> 3) & 0o7
    else:
        perm = st.st_mode & 0o7
    wanted = 0
    if mode & os.R_OK:
        wanted |= 0o4
    if mode & os.W_OK:
        wanted |= 0o2
    if mode & os.X_OK:
        wanted |= 0o1
    return perm & wanted == wanted


def drop_privileges(user: str, group: str) -> None:
    uid, _ = resolve_user(user)
    gid = grp.getgrnam(group).gr_gid
    os.setgroups([gid])
    os.setgid(gid)
    os.setuid(uid)
    os.environ["HOME"] = pwd.getpwuid(uid).pw_dir
    os.environ["USER"] = user
    log.info("dropped privileges to %s:%s (%d:%d)", user, group, uid, gid)


def prepare_home(home: str | Path, user: str, group: str, extra_dirs: Iterable[str | Path] = ()) -> None:
    """Make sure the home volume is usable by the run user."""
    uid, gid = resolve_user(user)
    dirs = [Path(home), *map(Path, extra_dirs)]
    for d in dirs:
        if running_as_root():
            log.info("running as root: fixing ownership of %s for %s:%s", d, user, group)
            set_perms(d, user, group, mode=0o750, recursive=str2bool(os.environ.get("ATL_CHOWN_RECURSIVE"), True))
        else:
            d.mkdir(parents=True, exist_ok=True)
            if not check_perms(d, uid, gid):
                raise EntrypointError(
                    f"{d} is not writable by {user} (uid {uid}). "
                    "Fix the volume ownership or start the container as root once with ATL_CHOWN_RECURSIVE=true."
                )


def exec_app(cmd: Sequence[str], user: str, group: str, cwd: str | Path | None = None) -> None:
    """Replace this process with the product start script."""
    if running_as_root():
        drop_privileges(user, group)
    if cwd:
        os.chdir(cwd)
    unset_secure_vars()
    log.info("exec: %s", " ".join(cmd))
    sys.stdout.flush()
    os.execvp(cmd[0], list(cmd))


def render_all(specs: Iterable[tuple[str, str | Path, bool, bool]], context: Mapping[str, str]) -> list[Path]:
    """Render ``(template, target, enabled, overwrite)`` specs; returns written paths."""
    written: list[Path] = []
    for template, target, enabled, overwrite in specs:
        if not enabled:
            log.debug("skipping %s (disabled)", template)
            continue
        if gen_cfg(template, target, context, overwrite=overwrite):
            written.append(Path(target))
    return written
