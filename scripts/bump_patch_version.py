#!/usr/bin/env python3
import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PACKAGE_NAME = "music-download-telegram-bot"


def bump_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"Only MAJOR.MINOR.PATCH versions are supported, got: {version}")

    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def read_pyproject_version() -> str:
    content = PYPROJECT.read_text()
    match = re.search(r'(?m)^version = "([^"]+)"$', content)
    if not match:
        raise RuntimeError("Could not find project version in pyproject.toml")
    return match.group(1)


def update_pyproject(version: str):
    content = PYPROJECT.read_text()
    content = re.sub(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        content,
        count=1,
    )
    PYPROJECT.write_text(content)


def update_uv_lock(version: str):
    if not UV_LOCK.exists():
        return

    content = UV_LOCK.read_text()
    pattern = (
        r'(\[\[package\]\]\n'
        rf'name = "{re.escape(PACKAGE_NAME)}"\n'
        r'version = ")[^"]+(")'
    )
    content, replacements = re.subn(pattern, rf'\g<1>{version}\2', content, count=1)
    if replacements == 0:
        raise RuntimeError(f"Could not find {PACKAGE_NAME} package entry in uv.lock")
    UV_LOCK.write_text(content)


def git_add(paths: list[Path]):
    subprocess.run(
        ["git", "add", *[str(path.relative_to(ROOT)) for path in paths if path.exists()]],
        cwd=ROOT,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description="Bump patch version in project metadata.")
    parser.add_argument("--stage", action="store_true", help="Stage changed version files with git add.")
    args = parser.parse_args()

    old_version = read_pyproject_version()
    new_version = bump_patch(old_version)

    update_pyproject(new_version)
    update_uv_lock(new_version)

    if args.stage:
        git_add([PYPROJECT, UV_LOCK])

    print(f"Bumped version: {old_version} -> {new_version}")


if __name__ == "__main__":
    main()
