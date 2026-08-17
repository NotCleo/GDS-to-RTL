#!/usr/bin/env bash
# =============================================================================
#  Jane Street ASIC reverse-engineering puzzle, full reproduction.
#
#      bash RUN.sh                 warm-up validation, then the puzzle
#      bash RUN.sh --only warmup
#      bash RUN.sh --only puzzle
#      bash RUN.sh --no-iverilog   skip the two independent-simulator checks
#
#  Inputs are only the files Jane Street shipped, in puzzle/ and warmup/, plus
#  the sky130 PDK in pdk/. Everything in puzzle-solution/ and warmup-solution/
#  is deleted and rebuilt. Runtime is about 15 seconds.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "no .venv here yet, creating one"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

echo "tools"
printf '  %-10s %s\n' python "$($PY --version 2>&1)"
for t in iverilog vvp; do
  if command -v "$t" >/dev/null; then
    printf '  %-10s %s\n' "$t" "$($t -V 2>&1 | head -1)"
  else
    printf '  %-10s MISSING, the two cross-checks will be skipped\n' "$t"
  fi
done
$PY - <<'EOF'
import gdstk, shapely, z3
from pysat.solvers import Cadical153
print(f"  {'gdstk':10s} {gdstk.__version__}")
print(f"  {'shapely':10s} {shapely.__version__}")
print(f"  {'z3':10s} {z3.get_version_string()}")
print(f"  {'python-sat':10s} Cadical153 available")
EOF

rm -rf puzzle-solution warmup-solution
$PY GDS-to-RTL/gds_to_rtl.py "$@"

echo
echo "deliverables"
for d in warmup-solution puzzle-solution; do
  [ -d "$d" ] || continue
  echo "  $d/"
  for f in "$d"/*; do printf '    %s\n' "$(basename "$f")"; done
done
cat <<'EOT'

  the answer string        puzzle-solution/13_output_string.txt
  the grid and region map  puzzle-solution/11_solution_grid.txt
  how to drive the chip    puzzle-solution/12_input_sequence.txt
  the recovered RTL        puzzle-solution/08_recovered_rtl.v
  the winning waveform     puzzle-solution/14_success_inputs.vcd   (open in Surfer)
  what every stage did     GDS-to-RTL/summary.md, GDS-to-RTL/run.log
EOT
