import importlib.util
from pathlib import Path

import pytest

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


def test_read_pins_handles_prereleases(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("foo==2.7.1rc1 ; python_version < '3.11'\nfoo==2.7.1 ; python_version >= '3.11'\n", encoding="utf-8")
    assert _load().read_pins(lock) == [("foo", "2.7.1")]


def test_read_pins_raises_on_non_python_version_split(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "foo==1.0.0 ; sys_platform == 'win32'\nfoo==1.1.0 ; sys_platform == 'linux'\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        _load().read_pins(lock)


def test_strip_bundle_flags_dll_and_versioned_shared_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _load()
    monkeypatch.setattr(bundle, "LIBS", tmp_path)
    pkg = tmp_path / "somepkg"
    pkg.mkdir()
    (pkg / "native.dll").write_bytes(b"")
    (pkg / "libfoo.so.1").write_bytes(b"")
    with pytest.raises(SystemExit):
        bundle.strip_bundle()


def test_server_version_reads_the_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "pyta-lsp"\nversion = "1.2.3"\n', encoding="utf-8")
    assert _load().server_version(pyproject) == "1.2.3"


def test_server_version_matches_the_package() -> None:
    import pyta_lsp

    assert _load().server_version() == pyta_lsp.__version__


def _fake_libs(root: Path) -> Path:
    libs = root / "libs-in"
    (libs / "pyta_lsp").mkdir(parents=True)
    (libs / "pyta_lsp" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    (libs / "pyta_lsp" / "__pycache__").mkdir()
    (libs / "pyta_lsp" / "__pycache__" / "__init__.cpython-313.pyc").write_bytes(b"")
    (libs / "somepkg").mkdir()
    (libs / "somepkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (libs / "somepkg-1.0.dist-info").mkdir()
    (libs / "somepkg-1.0.dist-info" / "METADATA").write_text("Name: somepkg\n", encoding="utf-8")
    return libs


def test_tarball_holds_one_libs_dir_without_pycache(tmp_path: Path) -> None:
    import tarfile

    bundle = _load()
    target = bundle.write_tarball(tmp_path / "out", libs=_fake_libs(tmp_path), version="9.9.9")

    assert target == tmp_path / "out" / "pyta-lsp-server-9.9.9.tar.gz"
    with tarfile.open(target, "r:gz") as tar:
        names = sorted(tar.getnames())
        owners = {(m.uid, m.gid, m.uname, m.gname) for m in tar.getmembers()}
    assert names == [
        "libs/pyta_lsp",
        "libs/pyta_lsp/__init__.py",
        "libs/somepkg",
        "libs/somepkg-1.0.dist-info",
        "libs/somepkg-1.0.dist-info/METADATA",
        "libs/somepkg/mod.py",
    ]
    assert owners == {(0, 0, "", "")}


def test_tarball_refuses_a_bundle_without_the_server(tmp_path: Path) -> None:
    libs = tmp_path / "libs-in"
    (libs / "somepkg").mkdir(parents=True)
    with pytest.raises(SystemExit, match="no pyta_lsp package"):
        _load().write_tarball(tmp_path / "out", libs=libs, version="9.9.9")


def test_extract_refuses_entries_outside_libs(tmp_path: Path) -> None:
    import io
    import tarfile

    bundle = _load()
    for bad in ("other/mod.py", "libs/../mod.py", "/libs/mod.py"):
        tarball = tmp_path / "bad.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            info = tarfile.TarInfo(bad)
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))
        with pytest.raises(SystemExit, match="outside libs/"):
            bundle.extract_tarball(tarball, tmp_path / "out")
    tarball = tmp_path / "backslash.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        # Fine on POSIX as a literal name, a traversal on Windows without the data filter.
        info = tarfile.TarInfo("libs/..\\..\\evil.py")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(SystemExit, match="backslash"):
        bundle.extract_tarball(tarball, tmp_path / "out")
    tarball = tmp_path / "link.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        info = tarfile.TarInfo("libs/mod.py")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(SystemExit, match="not a file or directory"):
        bundle.extract_tarball(tarball, tmp_path / "out")


def test_extract_round_trips_a_tarball(tmp_path: Path) -> None:
    bundle = _load()
    target = bundle.write_tarball(tmp_path / "out", libs=_fake_libs(tmp_path), version="9.9.9")
    libs = bundle.extract_tarball(target, tmp_path / "extracted")
    assert libs == tmp_path / "extracted" / "libs"
    assert (libs / "pyta_lsp" / "__init__.py").read_text(encoding="utf-8") == '__version__ = "0.0.0"\n'
    assert (libs / "somepkg" / "mod.py").is_file()


def test_messages_splits_framed_output() -> None:
    bundle = _load()
    first = b'{"jsonrpc": "2.0", "id": 1, "result": {}}'
    second = b'{"jsonrpc": "2.0", "method": "window/logMessage", "params": {}}'
    data = (
        b"Content-Length: " + str(len(first)).encode() + b"\r\nContent-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n" + first
        + b"Content-Length: " + str(len(second)).encode() + b"\r\n\r\n" + second
        + b"Content-Length: 999\r\n\r\n{\"trunc"
    )
    messages = bundle._messages(data)
    assert [m.get("id") for m in messages] == [1, None]
    assert messages[1]["method"] == "window/logMessage"


def test_initialize_round_trip_from_a_directory_that_shadows_json(tmp_path: Path) -> None:
    # An editor starts the server at the project root, and a student can keep a
    # json.py there. The server has to come up anyway, on every Python we support.
    import os
    import sys

    project = tmp_path / "project"
    project.mkdir()
    (project / "json.py").write_text("raise RuntimeError('the project json.py was imported')\n", encoding="utf-8")
    env = {**os.environ, "PYTHONSAFEPATH": "1", "PYTHONIOENCODING": "utf-8"}

    result = _load().initialize_round_trip(sys.executable, project, env)

    assert result["serverInfo"]["name"] == "pyta-lsp"
    assert "pyta.check" in result["capabilities"]["executeCommandProvider"]["commands"]


def test_the_launcher_survives_stdlib_names_at_the_project_root_on_any_python(tmp_path: Path) -> None:
    # With -m the start directory is on sys.path before runpy imports anything, so
    # on 3.10 (and on every version without PYTHONSAFEPATH) a types.py at the
    # project root is imported in place of the standard library one and the server
    # dies before the guard in __main__ runs. The -c launcher imports nothing
    # until the start directory is gone.
    import os
    import sys

    bundle = _load()
    project = tmp_path / "project"
    project.mkdir()
    for name in ("types.py", "operator.py", "json.py", "__future__.py"):
        (project / name).write_text(f"raise RuntimeError('the project {name} was imported')\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    # The project root on PYTHONPATH too (export PYTHONPATH=$PWD is common course
    # advice), and through a link, the way a shell reports its directory on macOS.
    link = tmp_path / "link"
    try:
        link.symlink_to(project, target_is_directory=True)
        via = link
    except (OSError, NotImplementedError):
        via = project
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env.get("PYTHONPATH"), str(via)]))

    result = bundle.initialize_round_trip(sys.executable, project, env, args=("-c", bundle.SERVER_LAUNCHER))

    assert result["serverInfo"]["name"] == "pyta-lsp"


def test_initialize_round_trip_reports_a_server_that_dies(tmp_path: Path) -> None:
    import os
    import sys

    # A pyta_lsp that outranks the real one and exits before it answers anything.
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "empty"), "PYTHONSAFEPATH": "1"}
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "pyta_lsp").mkdir()
    (empty / "pyta_lsp" / "__init__.py").write_text("", encoding="utf-8")
    (empty / "pyta_lsp" / "__main__.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exited with code 3"):
        _load().initialize_round_trip(sys.executable, tmp_path, env)


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "bundled" / "libs" / "pyta_lsp").is_dir(),
    reason="needs bundled/libs, built by `python scripts/bundle.py build`",
)
def test_check_tarball_end_to_end(tmp_path: Path) -> None:
    bundle = _load()
    target = bundle.write_tarball(tmp_path / "out")
    assert bundle.cmd_check_tarball(target) == 0


def test_the_launcher_line_is_the_one_the_server_uses_for_the_runner() -> None:
    # Three copies of one line: here for check-tarball, in pyta_lsp.paths for the
    # runner spawn, and in the Zed extension. A cargo test pins the third to this
    # one, and this pins the second.
    from pyta_lsp.paths import module_launcher

    assert module_launcher("pyta_lsp") == ["-c", _load().SERVER_LAUNCHER]
