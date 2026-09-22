"""A file PythonTA should not complain about."""


def add(a: int, b: int) -> int:
    """Return the sum of a and b.

    >>> add(1, 2)
    3
    """
    return a + b


if __name__ == '__main__':
    import python_ta

    python_ta.check_all(config={'max-line-length': 100})
