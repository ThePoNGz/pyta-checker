"""Config is a variable, not a literal."""
CONFIG = {'max-line-length': 100}


def f() -> None:
    """Do nothing."""


if __name__ == '__main__':
    import python_ta
    python_ta.check_all(config=CONFIG)
