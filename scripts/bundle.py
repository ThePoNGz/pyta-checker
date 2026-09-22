"""Build bundled/libs from server/requirements.lock using pure-Python packages only.

Usage:
  python scripts/bundle.py lock     # regenerate server/requirements.lock (universal, Python >= 3.10)
  python scripts/bundle.py build    # recreate bundled/libs and THIRD_PARTY_NOTICES.md, then verify
  python scripts/bundle.py verify   # import check against bundled/libs with an isolated interpreter
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from importlib.metadata import Distribution
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
REQ_IN = SERVER / "requirements.in"
LOCK = SERVER / "requirements.lock"
LIBS = ROOT / "bundled" / "libs"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
MIN_PY = "3.10"
# No pure wheels on PyPI; built from sdist with extensions disabled.
SDIST_ONLY = {"aiohttp", "markupsafe"}
# Packages whose optional C speedups may compile during an sdist build; the binaries are deleted.
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
    except ImportError:  # a bare interpreter still has pip's vendored copy
        from pip._vendor.packaging.version import Version

    return Version(version)


def _marker_is_python_version_only(marker: str) -> bool:
    # A marker only compares python_version/python_full_version means the
    # duplicate version it produced is just a Python-version split, safe to
    # resolve by taking the max. Anything else (sys_platform, extra, ...)
    # means the versions are platform- or environment-specific, not a
    # Python-version split, so the caller must not silently pick one.
    without_literals = re.sub(r"'[^']*'|\"[^\"]*\"", "", marker)
    idents = set(_MARKER_IDENT.findall(without_literals)) - _MARKER_KEYWORDS
    return idents <= _PY_VERSION_MARKER_VARS


def read_pins(lock: Path) -> list[tuple[str, str]]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["lock", "build", "verify"])
    args = parser.parse_args(argv)
    return {"lock": cmd_lock, "build": cmd_build, "verify": cmd_verify}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
