# namesake-collision

Two fixtures proving the import-guard's real coverage and its honest limit:

- `unrelated_file.py`: a local `old_helper` with no import of `somepkg` at all — the guard must skip this
  entirely, since the match would be a pure namesake coincidence.
- `shadowed_file.py`: imports `somepkg` (so the guard passes) but also defines a local `old_helper` that
  shadows the import per Python's own scoping rules — the call site resolves to the *local* function, not
  the imported one, and the guard cannot detect this. This is a known, documented residual risk, not a bug
  the guard is expected to close — see ast_grep_runner.py's module docstring, finding 10.
