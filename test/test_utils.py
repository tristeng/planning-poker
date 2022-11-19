from pp.utils import random_code, CODE_CHOICES


def test_random_code():
    code = random_code()
    assert len(code) == 4
    assert all([ch in CODE_CHOICES for ch in code])


def test_random_code_non_default():
    code = random_code(length=10)
    assert len(code) == 10
    assert all([ch in CODE_CHOICES for ch in code])
