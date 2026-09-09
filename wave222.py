"""PR #222: fix the seven newest review findings."""
import ast
import re
from pathlib import Path

p = Path("backend/ums_smart_revenue/ops/database_backup/postgres.py")
s = p.read_text(encoding="utf-8")

# ---- 1. Full libpq clear-set at every in-container exec ----
FULL_SET = [
    "PGHOST=", "PGHOSTADDR=", "PGPORT=", "PGUSER=", "PGDATABASE=",
    "PGSERVICE=", "PGSERVICEFILE=", "PGPASSWORD=", "PGPASSFILE=",
    "PGSSLMODE=", "PGOPTIONS=", "PGAPPNAME=", "PGCONNECT_TIMEOUT=",
]
OLD_SET = ["PGHOST=", "PGHOSTADDR=", "PGSERVICE=", "PGPASSWORD=", "PGDATABASE="]

# Every site currently lists the old five in the same order; replace each
# five-entry run with the full set (both indentations).
old_12 = "".join(f'            "-e", "{v}",\n' for v in OLD_SET)
new_12 = "".join(f'            "-e", "{v}",\n' for v in FULL_SET)
old_8 = "".join(f'        "-e", "{v}",\n' for v in OLD_SET)
new_8 = "".join(f'        "-e", "{v}",\n' for v in FULL_SET)
n12 = s.count(old_12)
n8 = s.count(old_8)
s = s.replace(old_12, new_12).replace(old_8, new_8)
print("libpq sites: 12-sp", n12, "8-sp", n8)

# wait_for_postgres pg_isready: add clears too (it currently has none).
old_ready = '''                [
                    "docker",
                    "exec",
                    source.container,
                    "pg_isready",
                    "--quiet",
                    f"--username={source.user}",
                    f"--dbname={source.database}",
                ],'''
new_ready = '''                [
                    "docker",
                    "exec",
                    *_LIBPQ_CLEAR_ARGS,
                    source.container,
                    "pg_isready",
                    "--quiet",
                    f"--username={source.user}",
                    f"--dbname={source.database}",
                ],
                timeout_seconds=_remaining_budget(deadline, runner.timeout_seconds),'''
assert s.count(old_ready) == 1, "ready"
s = s.replace(old_ready, new_ready, 1)

# Constant + budget helper before the CommandRunner class.
anchor = "\nclass CommandRunner:"
assert s.count(anchor) == 1
helpers = '''
# Every in-container PostgreSQL client invocation clears the full set of
# libpq connection-redirect variables: a container created with any of these
# inherited could otherwise send the dump, the replays, or the readiness probe
# to a different server, port, or identity than the one validation inspected.
_LIBPQ_CLEAR_ARGS: tuple[str, ...] = tuple(
    arg
    for value in (
        "PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGDATABASE",
        "PGSERVICE", "PGSERVICEFILE", "PGPASSWORD", "PGPASSFILE",
        "PGSSLMODE", "PGOPTIONS", "PGAPPNAME", "PGCONNECT_TIMEOUT",
    )
    for arg in ("-e", f"{value}=")
)


def _remaining_budget(deadline: float, default_seconds: int) -> int:
    """Cap one command attempt by the seconds left before the deadline."""
    remaining = int(deadline - time.monotonic())
    return max(1, min(default_seconds, remaining))

''' + anchor
s = s.replace(anchor, helpers, 1)

# text(): optional per-call timeout override.
old_text = '''    def text(
        self,
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        environment: Mapping[str, str] | None = None,
        exit_code: int = 5,
    ) -> str:'''
new_text = '''    def text(
        self,
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        environment: Mapping[str, str] | None = None,
        exit_code: int = 5,
        timeout_seconds: int | None = None,
    ) -> str:'''
assert s.count(old_text) == 1, "text sig"
s = s.replace(old_text, new_text, 1)

# Find text()'s subprocess.run timeout and use the override.
m = re.search(
    r'(    def text\(.*?)(timeout=self\.timeout_seconds,)',
    s, re.DOTALL,
)
assert m, "text timeout"
s = s[:m.start(2)] + "timeout=timeout_seconds or self.timeout_seconds," + s[m.end(2):]

# Also update text()'s docstring Args to mention the override.
old_args = '''            exit_code: int. BackupToolError exit code used when the command fails.

    Returns:
        The command's captured standard output.'''
new_args = '''            exit_code: int. BackupToolError exit code used when the command fails.
            timeout_seconds: int | None. Per-call timeout override; the runner's
                own bound applies when omitted.

    Returns:
        The command's captured standard output.'''
assert s.count(old_args) == 1, "text doc"
s = s.replace(old_args, new_args, 1)

ast.parse(s)
p.write_bytes(s.encode("utf-8"))
print("postgres.py updated")
