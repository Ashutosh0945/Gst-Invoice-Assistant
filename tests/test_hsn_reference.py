from backend.validation.hsn_reference import is_valid_format, lookup


def test_valid_format_lengths():
    assert is_valid_format("1006")
    assert is_valid_format("998314")
    assert not is_valid_format("12A4")
    assert not is_valid_format("123")


def test_lookup_hierarchical_fallback():
    # 998314 is in the seed table directly.
    assert lookup("998314") is not None
    # An 8-digit code sharing the 4-digit prefix "8471" should fall back.
    assert lookup("84713000") is not None
    assert lookup("00000000") is None
