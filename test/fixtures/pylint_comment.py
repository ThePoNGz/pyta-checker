"""Uses a forbidden pylint comment."""


def f() -> int:
    """Return one."""
    return 1  # pylint: disable=invalid-name
