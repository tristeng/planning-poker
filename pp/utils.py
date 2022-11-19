import random

CODE_CHOICES = "abcdefghijklmnopqrstuvwxyz1234567890"
CODE_RE = r"^[a-z\d]{4,10}$"


def random_code(length: int = 4) -> str:
    """Returns a random code of lower case alphabetic characters and numbers.

    :param length: the length of the desired code, defaults to 4 characters
    :return: a random string
    """
    return "".join([random.choice(CODE_CHOICES) for _ in range(length)])
