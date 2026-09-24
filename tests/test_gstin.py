from backend.validation.gstin import checksum_valid, is_well_formed, state_code
from backend.synthetic.generate import _rand_gstin


def test_well_formed_rejects_garbage():
    assert not is_well_formed("not-a-gstin")
    assert not is_well_formed(None)


def test_synthetic_gstins_pass_checksum():
    for sc in ("27", "24", "07", "29"):
        g = _rand_gstin(sc)
        assert is_well_formed(g)
        assert checksum_valid(g)
        assert state_code(g) == sc


def test_checksum_detects_corruption():
    g = _rand_gstin("27")
    corrupted = g[:-1] + ("X" if g[-1] != "X" else "Y")
    assert not checksum_valid(corrupted)
