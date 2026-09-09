"""Resolve PR #224's merge conflicts per hunk."""
import re
from pathlib import Path


def resolve(path: str, prefer: str = "head") -> int:
    """Resolve conflict hunks; main wins only when it carries **_kwargs."""
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    pattern = re.compile(
        r"<<<<<<< HEAD\n(.*?)=======\n(.*?)>>>>>>> origin/main\n",
        re.DOTALL,
    )
    resolved = 0

    def pick(m: re.Match) -> str:
        nonlocal resolved
        head, main = m.group(1), m.group(2)
        resolved += 1
        if "**_kwargs" in main and "**_kwargs" not in head:
            return main
        return head

    s2 = pattern.sub(pick, s)
    assert "<<<<<<<" not in s2, path
    import ast

    if path.endswith(".py"):
        ast.parse(s2)
    p.write_bytes(s2.encode("utf-8"))
    return resolved


n1 = resolve("tests/connectors/google/test_run_one_cli.py")
print("run_one_cli hunks:", n1)

# connectors_api: keep BOTH sides (HEAD's audit recording + main's close).
q = Path("tests/api/test_connectors_api.py")
t = q.read_text(encoding="utf-8")
old = """<<<<<<< HEAD
        self.audit_failure_calls: list[dict] = []
=======
        self.closed = False
>>>>>>> origin/main
<<<<<<< HEAD
    def audit_failed_before_start(self, **kwargs):
        \"\"\"Record the durable activation-failure handoff.\"\"\"
        self.audit_failure_calls.append(kwargs)
        return True
=======
    def close(self) -> None:
        \"\"\"Mirror the production executor lifecycle used by app shutdown.\"\"\"
        self.closed = True
>>>>>>> origin/main
"""
new = """        self.audit_failure_calls: list[dict] = []
        self.closed = False

    def audit_failed_before_start(self, **kwargs):
        \"\"\"Record the durable activation-failure handoff.\"\"\"
        self.audit_failure_calls.append(kwargs)
        return True

    def close(self) -> None:
        \"\"\"Mirror the production executor lifecycle used by app shutdown.\"\"\"
        self.closed = True
"""
assert t.count(old) == 1
t = t.replace(old, new, 1)
import ast

ast.parse(t)
q.write_bytes(t.encode("utf-8"))
print("connectors_api resolved (both sides kept)")
