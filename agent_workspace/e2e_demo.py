import os, sys
os.environ["COGNIA_AGENT_WORKSPACE"] = r"D:\Movido_desde_C\Downloads\cognia\cognia_v2\agent_workspace"
sys.path.insert(0, r"D:\Movido_desde_C\Downloads\cognia\cognia_v2")
from cognia.agents.workers.dev_tools import search_code, edit_file, run_tests

# Step A: find the bug
# search_code uses os.walk(root) relative to process cwd; must pass workspace-absolute path
ws = os.environ["COGNIA_AGENT_WORKSPACE"]
result_search = search_code(
    pattern=r"total / i\b",
    root=os.path.join(ws, "mini_repo"),
    glob="*.py"
)
print("SEARCH:", result_search)

# Step B: fix it
result_edit = edit_file(
    path="mini_repo/stats.py",
    old_string="result.append(total / i)",
    new_string="result.append(total / (i + 1))"
)
print("EDIT:", result_edit)

# Step C: verify the fix
result_test = run_tests(path="mini_repo")
print("TEST:", result_test)
print("LOOP COMPLETE:", "PASS" if result_test["passed"] == 4 and result_test["failed"] == 0 else "FAIL")
