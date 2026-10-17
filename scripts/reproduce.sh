#!/bin/sh
# Every table in results/ and every README figure, from the downloaded data, in one run.
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY scripts/run_calibration.py
$PY scripts/longshot_rule.py
$PY scripts/simulate_lookahead.py
$PY scripts/plot_figures.py
