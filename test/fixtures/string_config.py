"""Config given as a path string."""
import random


def pick() -> int:
    """Return a random number."""
    return random.randint(1, 6)


if __name__ == '__main__':
    import python_ta
    python_ta.check_all(config='pyta_config.txt')
