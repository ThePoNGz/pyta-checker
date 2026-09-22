import pyta_lsp


def test_version_is_semver() -> None:
    major, minor, patch = pyta_lsp.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))
