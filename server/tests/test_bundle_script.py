import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bundle.py"


def _load():
    spec = importlib.util.spec_from_file_location("bundle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_read_pins_strips_markers_comments_and_dedupes(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "# comment\n"
        "Python_TA==2.13.1\n"
        "colorama==0.4.6 ; sys_platform == 'win32'\n"
        "tomli==2.0.1 ; python_full_version < '3.11'\n"
        "tomli==2.2.1 ; python_full_version >= '3.11'\n"
        "    # indented comment\n"
        "\n",
        encoding="utf-8",
    )
    bundle = _load()
    assert bundle.read_pins(lock) == [
        ("python-ta", "2.13.1"),
        ("colorama", "0.4.6"),
        ("tomli", "2.2.1"),
    ]


class _Meta:
    def __init__(self, home, urls) -> None:
        self._home = home
        self._urls = urls

    def get(self, key, default=None):
        return self._home if key == "Home-page" else default

    def get_all(self, key, default=None):
        return list(self._urls) if key == "Project-URL" else (default or [])


def test_homepage_prefers_home_page_then_matching_project_urls() -> None:
    bundle = _load()
    assert bundle.homepage_from_metadata(_Meta("https://h", ["Source Code, https://s"])) == "https://h"
    assert bundle.homepage_from_metadata(_Meta(None, ["Source Code, https://s"])) == "https://s"
    assert bundle.homepage_from_metadata(_Meta(None, ["GitHub, https://g", "Homepage, https://h"])) == "https://h"
    assert bundle.homepage_from_metadata(_Meta(None, ["Code, https://c"])) == "https://c"
    assert bundle.homepage_from_metadata(_Meta(None, ["Funding, https://f"])) == ""
    assert bundle.homepage_from_metadata(_Meta(None, [])) == ""
