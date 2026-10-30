#!/bin/bash
cd "$(dirname "$0")" || exit 1
"${PLOT_FORGE_PYTHON:-python3}" launch.py
