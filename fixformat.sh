#!/bin/sh
set -e
poetry run isort . --profile black
poetry run black .
poetry run autoflake -r --in-place --remove-unused-variables .
poetry run pre-commit run --all-files
