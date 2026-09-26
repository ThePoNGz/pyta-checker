"""Build bundled/libs from server/requirements.lock using pure-Python packages only.

Usage:
  python scripts/bundle.py lock     # regenerate server/requirements.lock (universal, Python >= 3.10)
  python scripts/bundle.py build    # recreate bundled/libs and THIRD_PARTY_NOTICES.md, then verify
  python scripts/bundle.py verify   # import check against bundled/libs with an isolated interpreter
  python scripts/bundle.py tarball [OUT_DIR]         # write OUT_DIR/pyta-lsp-server-<version>.tar.gz (default dist/)
  python scripts/bundle.py check-tarball TARBALL      # extract it somewhere else and start the server from there
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from importlib.metadata import Distribution
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
REQ_IN = SERVER / "requirements.in"
LOCK = SERVER / "requirements.lock"
LIBS = ROOT / "bundled" / "libs"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
PYPROJECT = SERVER / "pyproject.toml"
DIST = ROOT / "dist"
# Editors that download the server look for a release asset with this prefix.
TARBALL_PREFIX = "pyta-lsp-server-"
# How an editor should start the server from a project root: `python -c` with this
# line. With `python -m pyta_lsp` the start directory is on sys.path before runpy
# imports anything, so a types.py at the root shadows the standard library on 3.10
# and on any version without PYTHONSAFEPATH. This takes the directory out first and
# imports nothing until it has. zed/src/logic.rs holds the same line, and a cargo
# test keeps the two equal.
SERVER_LAUNCHER = "import os, sys; here = os.path.normcase(os.path.realpath(os.getcwd())); sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.realpath(p)) != here]; import runpy; runpy.run_module('pyta_lsp', run_name='__main__', alter_sys=True)"
SERVER_ARGS = ("-m", "pyta_lsp")
MIN_PY = "3.10"
# No pure wheels on PyPI so we build these from sdist with the extensions off.
SDIST_ONLY = {"aiohttp", "markupsafe"}
# Packages whose optional C speedups can compile during an sdist build. We delete those binaries.
SPEEDUP_OK = {"markupsafe"}
COMPILED_NAME_RE = re.compile(r"\.(so|pyd|dylib|dll)(\.|$)")
_PY_VERSION_MARKER_VARS = {"python_version", "python_full_version"}
_MARKER_KEYWORDS = {"and", "or", "not", "in"}
_MARKER_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PURE_BUILD_ENV = {
    "AIOHTTP_NO_EXTENSIONS": "1",
    "MULTIDICT_NO_EXTENSIONS": "1",
    "YARL_NO_EXTENSIONS": "1",
    "FROZENLIST_NO_EXTENSIONS": "1",
    "PROPCACHE_NO_EXTENSIONS": "1",
}
_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)")
_VERSION_LINE = re.compile(r'^version = "([^"]+)"', re.MULTILINE)


def run(cmd: list, **kwargs) -> None:
    printable = [str(c) for c in cmd]
    print("+", " ".join(printable), flush=True)
    subprocess.run(printable, check=True, **kwargs)


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _version_key(version: str) -> Any:
    try:
        from packaging.version import Version
    except ImportError:  # a bare interpreter still has the pip vendored copy
        from pip._vendor.packaging.version import Version

    return Version(version)


def _marker_is_python_version_only(marker: str) -> bool:
    # A marker that only compares python_version or python_full_version means the
    # duplicate version it produced is just a Python version split, so taking the
    # max is safe. Anything else (sys_platform, extra, ...) means the versions are
    # specific to a platform or an environment, not a Python version split, so the
    # caller must not quietly pick one.
    without_literals = re.sub(r"'[^']*'|\"[^\"]*\"", "", marker)
    idents = set(_MARKER_IDENT.findall(without_literals)) - _MARKER_KEYWORDS
    return idents <= _PY_VERSION_MARKER_VARS


def read_pins(lock: Path) -> list[tuple[str, str]]:
    """Read name and version out of a lockfile, one pin per package.

    Args:
        lock: the lockfile to read, comments and environment markers included.

    Returns:
        Pairs of normalised name and version in the order the lockfile lists them.
        A package pinned twice by a Python version marker keeps the higher version,
        and any other kind of split raises instead of guessing.
    """
    entries: dict[str, list[tuple[str, str]]] = {}
    order: list[str] = []
    for raw in lock.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = _PIN.match(line)
        if not match:
            continue
        name = match.group(1).lower().replace("_", "-")
        version = match.group(2)
        rest = line[match.end():]
        marker = rest.split(";", 1)[1].strip() if ";" in rest else ""
        if name not in entries:
            order.append(name)
            entries[name] = []
        entries[name].append((version, marker))

    pins: dict[str, str] = {}
    for name in order:
        versions = entries[name]
        distinct = {v for v, _ in versions}
        if len(distinct) > 1:
            bad = [m for _, m in versions if not _marker_is_python_version_only(m)]
            if bad:
                raise SystemExit(
                    f"{name} has multiple versions ({', '.join(sorted(distinct))}) split by a "
                    f"marker that is not a plain Python-version bound ({bad[0]!r}); "
                    "refusing to guess which one to bundle"
                )
        pins[name] = max((v for v, _ in versions), key=_version_key)
    return [(name, pins[name]) for name in order]


def cmd_lock() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        venv.create(tmp, with_pip=True)
        py = _venv_python(Path(tmp))
        run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "uv"])
        run([
            py, "-m", "uv", "pip", "compile", REQ_IN,
            "--universal", "--python-version", MIN_PY,
            "--no-header", "--no-annotate",
            "--output-file", LOCK,
        ])
    print(f"wrote {LOCK}")
    return 0


def _pip_target() -> list:
    return [
        sys.executable, "-m", "pip", "install",
        "--target", LIBS, "--no-deps", "--no-compile", "--disable-pip-version-check",
    ]


def strip_bundle() -> None:
    """Clear everything out of the bundle that must not ship.

    Drops bin, include and every __pycache__, deletes the compiled speedups we allow
    to build, and raises when any other compiled file turns up, because the bundle
    has to stay pure Python to run on every platform.
    """
    shutil.rmtree(LIBS / "bin", ignore_errors=True)
    shutil.rmtree(LIBS / "include", ignore_errors=True)
    offenders: list[Path] = []
    for path in sorted(LIBS.rglob("*"), reverse=True):
        if path.is_dir() and path.name == "__pycache__":
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file() and COMPILED_NAME_RE.search(path.name):
            top = path.relative_to(LIBS).parts[0].lower()
            if top in SPEEDUP_OK:
                path.unlink()
            else:
                offenders.append(path)
    if offenders:
        names = ", ".join(str(p.relative_to(LIBS)) for p in offenders)
        raise SystemExit(f"compiled files in bundle (not allowed): {names}")


_HOMEPAGE_HINTS = ("home", "source", "repo", "github", "code")


def homepage_from_metadata(meta) -> str:
    """The best homepage link in package metadata, Home-page first then a Project-URL."""
    home_page = meta.get("Home-page")
    if home_page:
        return home_page
    candidates: list[tuple[str, str]] = []
    for url in meta.get_all("Project-URL", []):
        label, _, link = url.partition(",")
        label = label.strip().lower()
        link = link.strip()
        if link and any(hint in label for hint in _HOMEPAGE_HINTS):
            candidates.append((label, link))
    if not candidates:
        return ""
    for label, link in candidates:
        if "home" in label:
            return link
    return candidates[0][1]


def write_notices() -> None:
    """Rebuild THIRD_PARTY_NOTICES.md from the dist-info of everything in the bundle."""
    rows: list[tuple[str, str, str, str]] = []
    for info_dir in sorted(LIBS.glob("*.dist-info")):
        meta = Distribution.at(info_dir).metadata
        name = meta["Name"]
        if name.lower().replace("_", "-") == "pyta-lsp":
            continue
        version = meta["Version"]
        license_text = meta.get("License-Expression") or meta.get("License") or ""
        if not license_text or len(license_text) > 60:
            classifiers = [c for c in meta.get_all("Classifier", []) if c.startswith("License ::")]
            license_text = classifiers[-1].split("::")[-1].strip() if classifiers else (license_text[:57] + "...")
        homepage = homepage_from_metadata(meta)
        rows.append((name, version, license_text, homepage))
    lines = [
        "# Third-party notices",
        "",
        "PythonTA Checker bundles the following unmodified Python packages inside the extension "
        "(`bundled/libs/`). Each package's license text ships in its `*.dist-info` directory in the bundle "
        "where the package provides one. "
        "The extension's own code is MIT licensed (see `LICENSE`).",
        "",
        "Generated by `scripts/bundle.py`; do not edit by hand.",
        "",
        "| Package | Version | License | Homepage |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {n} | {v} | {lic} | {home} |" for n, v, lic, home in rows]
    lines += [
        "",
        "Note: python-ta's wheel ships no license file; its metadata declares MIT while the repository's "
        "LICENSE file is GPL-3.0. This project redistributes the wheel as published. "
        "See https://github.com/pyta-uoft/pyta.",
        "",
    ]
    NOTICES.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {NOTICES} ({len(rows)} packages)")


def cmd_verify() -> int:
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import python_ta, pygls, pyta_lsp, aiohttp, markupsafe, jinja2, pylint, astroid; "
        "assert python_ta.__file__.startswith(sys.argv[1]), python_ta.__file__; "
        "from importlib.metadata import version; "
        "print('bundle ok: python-ta', python_ta.__version__, '| pygls', version('pygls'))"
    )
    run([sys.executable, "-I", "-B", "-c", code, LIBS])
    return 0


def cmd_build() -> int:
    if not LOCK.exists():
        print("no lockfile; run `python scripts/bundle.py lock` first", file=sys.stderr)
        return 1
    if LIBS.exists():
        shutil.rmtree(LIBS)
    LIBS.mkdir(parents=True)
    pins = read_pins(LOCK)
    pure = [f"{n}=={v}" for n, v in pins if n not in SDIST_ONLY]
    sdist = [f"{n}=={v}" for n, v in pins if n in SDIST_ONLY]
    run(_pip_target() + [
        "--only-binary", ":all:", "--implementation", "py", "--python-version", MIN_PY,
        "--abi", "none", "--platform", "any", *pure,
    ])
    env = {**os.environ, **PURE_BUILD_ENV}
    for pin in sdist:
        run(_pip_target() + ["--no-binary", ":all:", pin], env=env)
    run(_pip_target() + [SERVER])
    strip_bundle()
    write_notices()
    return cmd_verify()


def server_version(pyproject: Path = PYPROJECT) -> str:
    """The version line of the server pyproject, which is what the tarball is named after."""
    match = _VERSION_LINE.search(pyproject.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"no version line in {pyproject}")
    return match.group(1)


def tarball_name(version: str) -> str:
    return f"{TARBALL_PREFIX}{version}.tar.gz"


def _anonymous(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def write_tarball(out_dir: Path, libs: Path = LIBS, version: str | None = None) -> Path:
    """Pack the bundle into one tarball with a single top level libs directory.

    The bundle already holds the pyta_lsp package next to its dependencies, so
    one PYTHONPATH entry pointing at the extracted libs directory is all an
    editor needs to run `python -m pyta_lsp`.

    Args:
        out_dir: where the tarball goes, created when missing.
        libs: the bundle to pack.
        version: what to name the tarball after, the server version by default.

    Returns:
        The tarball path.
    """
    if not (libs / "pyta_lsp" / "__init__.py").is_file():
        raise SystemExit(f"{libs} has no pyta_lsp package; run `python scripts/bundle.py build` first")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / tarball_name(version or server_version())
    with tarfile.open(target, "w:gz") as tar:
        for path in sorted(libs.rglob("*")):
            relative = path.relative_to(libs)
            if "__pycache__" in relative.parts:
                continue
            tar.add(path, arcname=f"libs/{relative.as_posix()}", recursive=False, filter=_anonymous)
    print(f"wrote {target}")
    return target


def extract_tarball(tarball: Path, into: Path) -> Path:
    """Unpack a server tarball and hand back its libs directory.

    Every entry has to sit under libs/ and be a plain file or directory, so a
    tarball from anywhere else cannot write outside the directory it was given.
    """
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar.getmembers():
            parts = PurePosixPath(member.name).parts
            if member.name.startswith("/") or ".." in parts or parts[:1] != ("libs",):
                raise SystemExit(f"{tarball.name} has an entry outside libs/: {member.name}")
            if "\\" in member.name:
                # A literal name on POSIX, but a separator on Windows, where the
                # interpreters without the data filter would follow it.
                raise SystemExit(f"{tarball.name} has an entry with a backslash in its name: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise SystemExit(f"{tarball.name} has an entry that is not a file or directory: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(into, filter="data")
        else:  # 3.10 and early 3.11, the check above already did the work
            tar.extractall(into)
    return into / "libs"


def _frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def _messages(data: bytes) -> list[dict[str, Any]]:
    """Split the framed JSON-RPC bytes a server wrote into messages."""
    messages: list[dict[str, Any]] = []
    while data:
        header, separator, rest = data.partition(b"\r\n\r\n")
        length_match = re.search(rb"Content-Length: *(\d+)", header)
        if not separator or not length_match:
            break
        length = int(length_match.group(1))
        if len(rest) < length:  # a partial message, the server died mid write
            break
        messages.append(json.loads(rest[:length].decode("utf-8")))
        data = rest[length:]
    return messages


def initialize_round_trip(
    python: str,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 60.0,
    args: tuple[str, ...] = SERVER_ARGS,
) -> dict[str, Any]:
    """Start the server in cwd, initialize it, shut it down, and return the initialize result.

    Everything goes down the pipe at once and the reply is read after the server
    exits, so no thread has to babysit a read with a timeout.

    Args:
        python: the interpreter to start.
        cwd: where to start it, the project root as far as an editor is concerned.
        env: the whole environment the server gets.
        timeout: seconds before the server is killed and the check fails.
        args: how the interpreter finds the server, `-m pyta_lsp` or the launcher.
    """
    proc = subprocess.Popen(
        [python, *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    script = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"processId": None, "rootUri": cwd.as_uri(), "capabilities": {}},
        },
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": None},
    ]
    try:
        out, err = proc.communicate(b"".join(_frame(m) for m in script), timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise SystemExit(f"the server did not answer initialize within {int(timeout)} seconds")
    stderr = err.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"the server exited with code {proc.returncode}:\n{stderr}")
    for message in _messages(out):
        if message.get("id") == 1:
            if "error" in message:
                raise SystemExit(f"initialize failed: {message['error']}\n{stderr}")
            return message["result"]
    raise SystemExit(f"the server never answered initialize:\n{stderr}")


def cmd_tarball(out_dir: Path) -> int:
    write_tarball(out_dir)
    return 0


def cmd_check_tarball(tarball: Path) -> int:
    """Prove the tarball works the way an editor uses it, from a directory of its own."""
    with tempfile.TemporaryDirectory() as tmp:
        libs = extract_tarball(tarball, Path(tmp) / "extracted")
        env = {
            **os.environ,
            "PYTHONPATH": str(libs),
            "PYTHONSAFEPATH": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        code = (
            "import sys, pyta_lsp, python_ta, pygls; "
            "libs = sys.argv[1]; "
            "bad = [m.__name__ for m in (pyta_lsp, python_ta, pygls) if not m.__file__.startswith(libs)]; "
            "assert not bad, f'imported from outside the tarball: {bad}'; "
            "print('tarball ok: pyta_lsp', pyta_lsp.__version__, '| python-ta', python_ta.__version__)"
        )
        run([sys.executable, "-c", code, str(libs)], cwd=tmp, env=env)
        # The project root an editor starts the server from, holding the worst files
        # a student can put there. json.py is imported after the guard in __main__,
        # types.py and operator.py are imported by runpy itself, before it.
        project = Path(tmp) / "project"
        project.mkdir()
        for name in ("json.py", "types.py", "operator.py"):
            (project / name).write_text(f"raise RuntimeError('the project {name} was imported')\n", encoding="utf-8")
        # An editor that uses -m has to set PYTHONSAFEPATH and lives with the 3.10
        # residual, so that check keeps to json.py from a root of its own.
        plain = Path(tmp) / "plain"
        plain.mkdir()
        (plain / "json.py").write_text("raise RuntimeError('the project json.py was imported')\n", encoding="utf-8")
        _expect_server(initialize_round_trip(sys.executable, plain, env), f"-m from {plain}")
        # The launcher has to hold up with nothing but PYTHONPATH set, on every
        # Python, and with the project root itself on that PYTHONPATH.
        bare = {k: v for k, v in env.items() if k != "PYTHONSAFEPATH"}
        bare["PYTHONPATH"] = os.pathsep.join([str(libs), str(project)])
        _expect_server(
            initialize_round_trip(sys.executable, project, bare, args=("-c", SERVER_LAUNCHER)),
            f"launcher from {project}",
        )
    return 0


def _expect_server(result: dict[str, Any], how: str) -> None:
    info = result.get("serverInfo") or {}
    if info.get("name") != "pyta-lsp":
        raise SystemExit(f"unexpected server ({how}): {info}")
    print(f"initialize ok ({how}): pyta-lsp {info.get('version')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["lock", "build", "verify", "tarball", "check-tarball"])
    parser.add_argument("path", nargs="?", help="tarball: the output directory. check-tarball: the tarball.")
    args = parser.parse_args(argv)
    if args.command == "tarball":
        return cmd_tarball(Path(args.path) if args.path else DIST)
    if args.command == "check-tarball":
        if not args.path:
            parser.error("check-tarball needs the tarball path")
        return cmd_check_tarball(Path(args.path))
    return {"lock": cmd_lock, "build": cmd_build, "verify": cmd_verify}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
