#!/usr/bin/env sh
set -eu

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/post-commit scripts/bump_patch_version.py
echo "Git hooks installed: core.hooksPath=.githooks"
