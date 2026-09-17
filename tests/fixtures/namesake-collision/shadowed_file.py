from somepkg import old_helper


def old_helper(x):
    """Shadows the import above per Python scoping rules — this file's call site below actually calls
    this local function, not the imported one."""
    return x * 2


def run():
    return old_helper(1, 2, keyword="value")
