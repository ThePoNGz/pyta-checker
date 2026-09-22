"""Sample CSC148-style file with an embedded PythonTA config."""
import random
from datetime import datetime


def roll(n: int) -> int:
    """Roll n dice.

    >>> roll(0)
    0
    """
    total=0
    for i in range(n):
        total += random.randint(1, 6)
    print(total)
    return total


if __name__ == '__main__':
    import doctest

    doctest.testmod(verbose=True)

    import python_ta

    python_ta.check_all(config={
        'extra-imports': ['random', 'datetime'],
        'allowed-io': ['roll'],
        'max-line-length': 100,
        'disable': ['C0200']
    })
