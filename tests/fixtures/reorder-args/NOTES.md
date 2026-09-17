# reorder-args

Synthetic fixture (not tied to a real package — clearly marked as such per this project's own standard for
invented examples) exercising REORDER: `connect(host, port, timeout=30)` -> `connect(port, host, timeout=30)`.
Deliberately includes the trailing `timeout=30` keyword argument, since an earlier version of the pattern
generator only matched exactly the reordered arguments and silently failed to match anything when additional
arguments were present — see ast_grep_runner.py's module docstring.
