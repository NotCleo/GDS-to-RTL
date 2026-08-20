#!/usr/bin/env bash
# Builds and runs everything in this folder.
#
#   bash run.sh              the pipeline and the equivalence proof
#   bash run.sh --only pipe  just the pipeline, which is what writes the VCD
#
# Only iverilog is needed. The equivalence run also reads the extracted netlist
# and the cell models from ../puzzle-solution, which RUN.sh at the top of the
# repository produces from puzzle.gds.
set -e
cd "$(dirname "$0")"

ONLY="${2:-all}"
[ "${1:-}" = "--only" ] || ONLY=all

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if [ "$ONLY" = "all" ] || [ "$ONLY" = "pipe" ]; then
  echo "building tb_full_solver"
  iverilog -g2012 -o "$WORK/pipe" full_solver.v solver.v validator.v tb_full_solver.v
  vvp "$WORK/pipe"
fi

if [ "$ONLY" = "all" ] || [ "$ONLY" = "equiv" ]; then
  echo "building tb_validator_equiv"
  if [ ! -f ../puzzle-solution/02_extracted_netlist.v ]; then
    echo "  ../puzzle-solution is not built yet, run bash RUN.sh at the top first"
  else
    iverilog -g2012 -o "$WORK/equiv" \
      ../puzzle-solution/03_cell_models.v \
      ../puzzle-solution/02_extracted_netlist.v \
      ../puzzle-solution/08_recovered_rtl.v \
      validator.v tb_validator_equiv.v
    vvp "$WORK/equiv"
  fi
fi
