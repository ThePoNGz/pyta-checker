from pyta_lsp.pyta_codes import PYTA_DOCUMENTED_CODES


def test_known_documented_codes_present() -> None:
    for code in ("E9989", "E9998", "E9999", "C0201", "R0912"):
        assert code in PYTA_DOCUMENTED_CODES


def test_known_undocumented_codes_absent() -> None:
    for code in ("C0114", "C0200", "R1705", "R9901"):
        assert code not in PYTA_DOCUMENTED_CODES


def test_codes_are_uppercase_five_chars() -> None:
    assert all(len(c) == 5 and c[0].isupper() and c[1:].isdigit() for c in PYTA_DOCUMENTED_CODES)
