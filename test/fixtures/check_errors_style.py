"""Uses check_errors with a bare name import."""
from python_ta import check_errors


def add(a: int, b: int) -> int:
    """Add."""
    return a + b


if __name__ == '__main__':
    check_errors(config={'max-line-length': 100})
