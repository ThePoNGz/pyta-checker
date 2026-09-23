import pyta_lsp


def test_version_is_semver() -> None:
    major, minor, patch = pyta_lsp.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))


def test_version_matches_the_package_and_the_extension() -> None:
    # The release steps in the README bump three places. Only the tag check in
    # release.yml compares any of them, and it only sees package.json.
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "server" / "pyproject.toml").read_text(encoding="utf-8")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))

    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert match is not None
    assert match.group(1) == pyta_lsp.__version__
    assert package["version"] == pyta_lsp.__version__
