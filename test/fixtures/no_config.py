"""Same code, no embedded config."""
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
