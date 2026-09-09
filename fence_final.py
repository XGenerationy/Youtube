"""One deterministic pass: --no-acl + mutation fencing for both replays."""
import ast
from pathlib import Path

p = Path("backend/ums_smart_revenue/ops/database_backup/postgres.py")
s = p.read_text(encoding="utf-8")

# ---- 1. --no-acl on pg_dump ----
old_dump = '''            "pg_dump",
            "--format=custom",
            "--compress=6",
            "--no-owner",
            "--no-password",'''
assert s.count(old_dump) == 1, "dump argv"
s = s.replace(
    old_dump,
    '''            "pg_dump",
            "--format=custom",
            "--compress=6",
            "--no-owner",
            "--no-acl",
            "--no-password",''',
    1,
)

# ---- 2. Helpers before apply_sql_file ----
helpers = '''

def _mutation_tag() -> str:
    """Return a unique application_name tagging one mutating restore session."""
    return f"ums-restore-mutation-{secrets.token_hex(8)}"


def _tag_from_argv(argv: list[str]) -> str:
    """Return the PGAPPNAME tag one fenced argv carries."""
    for index, item in enumerate(argv):
        if item.startswith("PGAPPNAME=") and index and argv[index - 1] == "-e":
            return item.split("=", 1)[1]
    raise BackupToolError("fenced mutation argv carries no PGAPPNAME tag", exit_code=4)


def _terminate_tagged_backends(
    runner: CommandRunner,
    *,
    container: str,
    user: str,
    database: str,
    tag: str,
) -> None:
    """Cancel and terminate the tagged mutating backend, proving it stopped.

    A host-side timeout kills only the local Docker client; the in-container
    psql/pg_restore keeps mutating the server. After cancelling and
    terminating every pg_stat_activity backend carrying this invocation's
    application_name, the loop requires the backend to be ABSENT on two
    consecutive observations before returning, so a refusal never races a
    still-running mutation.
    """
    import time as _time

    absent_streak = 0
    for _ in range(60):
        listing = runner.text(
            [
                "docker",
                "exec",
                *_LIBPQ_CLEAR_ARGS,
                "-e",
                "PGAPPNAME=ums-restore-fence",
                container,
                "psql",
                "--no-psqlrc",
                "--no-password",
                "--quiet",
                "--tuples-only",
                "--no-align",
                f"--username={user}",
                f"--dbname={database}",
                "-c",
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                f"WHERE application_name = '{tag}' AND pid <> pg_backend_pid()",
            ],
            exit_code=4,
        )
        if listing.strip() == "0":
            absent_streak += 1
            if absent_streak >= 2:
                return
        else:
            absent_streak = 0
            runner.text(
                [
                    "docker",
                    "exec",
                    *_LIBPQ_CLEAR_ARGS,
                    "-e",
                    "PGAPPNAME=ums-restore-fence",
                    container,
                    "psql",
                    "--no-psqlrc",
                    "--no-password",
                    "--quiet",
                    f"--username={user}",
                    f"--dbname={database}",
                    "-c",
                    "SELECT pg_catalog.pg_terminate_backend(pid) "
                    "FROM pg_catalog.pg_stat_activity "
                    f"WHERE application_name = '{tag}' "
                    "AND pid <> pg_backend_pid()",
                ],
                exit_code=4,
            )
        _time.sleep(0.5)
    raise BackupToolError(
        "timed-out restore mutation could not be proven stopped; inspect the "
        "target before retrying",
        exit_code=4,
    )


def _run_fenced_mutation(
    runner: CommandRunner,
    argv: list[str],
    *,
    container: str,
    user: str,
    database: str,
    feed: Path | BinaryIO,
) -> None:
    """Run one mutating replay; on timeout, fence its server backend first.

    FIX: restores the fencing the modular rewrite dropped (commit 1e266fdce):
    a host timeout previously returned a refusal while the in-container
    psql/pg_restore kept mutating the target. The mutating session runs under
    a unique PGAPPNAME tag; on TimeoutExpired the tagged backend is cancelled,
    terminated, and proven absent before the refusal surfaces.
    """
    from subprocess import TimeoutExpired

    if isinstance(feed, Path):
        with feed.open("rb") as stream:
            _run_fenced_stream(
                runner, argv, stream, container=container, user=user, database=database
            )
    else:
        _run_fenced_stream(
            runner, argv, feed, container=container, user=user, database=database
        )


def _run_fenced_stream(
    runner: CommandRunner,
    argv: list[str],
    stream: BinaryIO,
    *,
    container: str,
    user: str,
    database: str,
) -> None:
    """Stream one pinned feed through the argv with timeout fencing."""
    from subprocess import TimeoutExpired

    try:
        runner.stream_to_text(argv, stream, exit_code=6)
    except BackupToolError as exc:
        if isinstance(exc.__cause__, TimeoutExpired):
            _terminate_tagged_backends(
                runner,
                container=container,
                user=user,
                database=database,
                tag=_tag_from_argv(argv),
            )
        raise

'''
anchor = "\ndef apply_sql_file("
assert s.count(anchor) == 1
s = s.replace(anchor, helpers + anchor, 1)

# ---- 3. apply_sql_file: tag + fence ----
old_apply_clear = '''        "-e", "PGOPTIONS=",
        "-e", "PGAPPNAME=",
        "-e", "PGCONNECT_TIMEOUT=",
        container,
        "psql",'''
assert s.count(old_apply_clear) == 1, "apply clear"
s = s.replace(
    old_apply_clear,
    '''        "-e", "PGOPTIONS=",
        "-e", f"PGAPPNAME={_mutation_tag()}",
        "-e", "PGCONNECT_TIMEOUT=",
        container,
        "psql",''',
    1,
)
old_apply_feed = '''    if isinstance(source, Path):
        runner.file_to_text(argv, source, exit_code=6)
    else:
        runner.stream_to_text(argv, source, exit_code=6)


def restore_dump('''
assert s.count(old_apply_feed) == 1, "apply feed"
s = s.replace(
    old_apply_feed,
    '''    _run_fenced_mutation(
        runner, argv, container=container, user=user, database=database, feed=source
    )


def restore_dump(''',
    1,
)

# ---- 4. restore_dump: --no-acl + tag + fence ----
old_restore_argv = '''        container,
        "pg_restore",
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-password",'''
assert s.count(old_restore_argv) == 1, "restore argv"
s = s.replace(
    old_restore_argv,
    '''        container,
        "pg_restore",
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-acl",
        "--no-password",''',
    1,
)
old_restore_clear = '''        "-e", "PGOPTIONS=",
        "-e", "PGAPPNAME=",
        "-e", "PGCONNECT_TIMEOUT=",
        container,
        "pg_restore",'''
assert s.count(old_restore_clear) == 1, "restore clear"
s = s.replace(
    old_restore_clear,
    '''        "-e", "PGOPTIONS=",
        "-e", f"PGAPPNAME={_mutation_tag()}",
        "-e", "PGCONNECT_TIMEOUT=",
        container,
        "pg_restore",''',
    1,
)
old_restore_feed = '''    if isinstance(source, Path):
        runner.file_input(argv, source, exit_code=6)
    else:
        runner.stream_to_text(argv, source, exit_code=6)'''
assert s.count(old_restore_feed) == 1, "restore feed"
s = s.replace(
    old_restore_feed,
    '''    _run_fenced_mutation(
        runner, argv, container=container, user=user, database=database, feed=source
    )''',
    1,
)

import re
s = re.sub(r"\n{4,}(def )", r"\n\n\n\1", s)
ast.parse(s)
p.write_bytes(s.encode("utf-8"))
print("fencing + no-acl wired in one pass")
