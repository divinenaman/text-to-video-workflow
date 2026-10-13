#!/bin/bash

pre-commit run --all-files

# mypy --ignore-missing-imports --show-error-codes --check-untyped-defs *.py
