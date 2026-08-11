#!/usr/bin/env bash
# =============================================================================
#  Jane Street ASIC reverse-engineering puzzle -- full reproduction
#
#    bash run.sh            everything (warm-up validation, then the puzzle)
#    bash run.sh warmup     only the warm-up (validates the toolchain)
#    bash run.sh puzzle     only the puzzle
#    bash run.sh eggs       only the easter-egg / floorplan sweeps
#
#  Every step echoes the exact command it runs, so any single step can be
#  re-run on its own by copy-pasting it. Inputs are only ever the files Jane
#  Street shipped plus the sky130 PDK in pdk/; everything under results/ is
#  regenerated from scratch.
#
#  Runtime: ~4 min total. The slow steps are P9 (121-trial cell probe, ~35 s),
#  P11 (bounded model checking, ~40 s) and P13 (540-grid equivalence, ~30 s).
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python

# Input locations. These are the only lines to touch if directories get renamed.
TOOLS=GDS-to-RTL         # the pipeline scripts
SRC_PUZZLE=puzzle-task   # puzzle.gds, example_inputs.vcd, layout.png
SRC_WARMUP=warmup-task   # the warm-up design, 00_source.v .. 04_final.gds

LIB=pdk/sky130_fd_sc_hd__tt_025C_1v80.lib
W=results/warmup
P=results/puzzle
TOP=puzzle_extracted

# The 121-bit answer, row-major. Steps P11/P12 rediscover it from the netlist;
# it is written here so the later steps can be re-run independently.
SOL=0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000

say() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
run() { printf '  $ %s\n' "$*"; eval "$@"; }

WHAT=${1:-all}
mkdir -p "$W" "$P"/{models,verify,structure,probe,solve,rtl,answer,eggs} solution

# =============================================================================
#  PART 1 -- WARM-UP.  Purpose: prove the extractor is exact before pointing it
#  at a design that has no answer key. The warm-up ships the golden RTL, netlist
#  and DEF, so here (and only here) the recovered netlist can be checked against
#  the truth rather than against a plausibility argument.
# =============================================================================
if [ "$WHAT" = all ] || [ "$WHAT" = warmup ]; then

say "W1  GDS inventory -- what cells exist and where (no connectivity yet)"
run "$PY $TOOLS/01_gds_inventory.py $SRC_WARMUP/04_final.gds $W | tail -25"

say "W2  Extract a netlist from raw polygons (want: driver-count != 1 -> 0)"
run "$PY $TOOLS/02_extract_netlist.py $SRC_WARMUP/04_final.gds $W"

say "W3  GOLDEN CHECK -- match GDS placements to the DEF, then compare"
say "    connectivity pin-by-pin against $SRC_WARMUP/01_netlist.v"
run "$PY $TOOLS/03_def_crosscheck.py $SRC_WARMUP/04_final.gds \
        $SRC_WARMUP/03_post_place_and_route.def $SRC_WARMUP/01_netlist.v $W"

say "W4  Liberty -> simulatable Verilog cell models"
run "$PY $TOOLS/04_gen_models.py $LIB $W/sky130_models.v"

say "W5  Simulate golden and extracted side by side, 3000 random cycles"
run "iverilog -g2012 -o $W/sim.vvp $W/sky130_models.v $SRC_WARMUP/01_netlist.v \
        $W/extracted_netlist.v $TOOLS/tb_warmup.v"
run "vvp $W/sim.vvp | tail -8"

say "W6  Solve the warm-up from the EXTRACTED netlist alone (BMC, no hand-tracing)"
say "    Expect A=11110101=245, B=11111011=251, 245+251=496, S=1 at cycle 9."
run "yosys -p \"read_verilog $W/sky130_models.v $W/extracted_netlist.v; \
        hierarchy -top adder_demo_extracted; proc; flatten; async2sync; opt; \
        sat -seq 9 -set-init-zero -set rst_n 1 -set en 1 -set-at 9 S 1 \
            -show A -show B -show S\" > $W/bmc_solve.log 2>&1 || true"
run "grep -E '^ +[0-9]+ .(A|B|S) ' $W/bmc_solve.log \
     | awk '{printf \"    cycle %2s  %s = %s\\n\", \$1, substr(\$2,2), \$3}'"
# cycles 1..8 load the two shift registers MSB-first; cycle 9 is the compare
run "$PY -c \"
import re,sys
b={'A':'','B':''}
for l in open('$W/bmc_solve.log'):
    m=re.match(r' +([0-9]+) .([AB]) +.*?([01])\\s*\$', l)
    if m and int(m.group(1))<=8: b[m.group(2)]+=m.group(3)
a,c=int(b['A'],2),int(b['B'],2)
print(f'    -> A = {b[\\\"A\\\"]} = {a},  B = {b[\\\"B\\\"]} = {c},  A+B = {a+c}')\""

say "W7  For contrast: run the FORWARD flow, 00_source.v -> gates"
say "    Same library in, same shape of cell mix out -- 01_netlist.v is just"
say "    yosys output, and the reverse direction is undoing exactly this."
run "yosys -s $TOOLS/05_resynth.ys > $W/resynth.log 2>&1 || true"
run "sed -n '/^6. Printing statistics/,/^7\./p' $W/resynth.log | head -32"

fi

# =============================================================================
#  PART 2 -- THE PUZZLE.  Same extractor, no answer key. Validation now comes
#  from the recorded silicon waveform, from cross-tool agreement, and finally
#  from a full behavioural model proved cycle-equivalent to the gates.
# =============================================================================
if [ "$WHAT" = all ] || [ "$WHAT" = puzzle ]; then

say "P1  GDS inventory -- die size, cell histogram, surviving port labels"
run "$PY $TOOLS/01_gds_inventory.py $SRC_PUZZLE/puzzle.gds $P | tail -25"

say "P2  Extract the netlist (want: 738 nets, driver-count != 1 -> 0)"
say "    Two silent traps live here: LEF pin geometry, and antenna diodes."
run "$PY $TOOLS/02_extract_netlist.py $SRC_PUZZLE/puzzle.gds $P"

say "P3  Cell models for exactly this design's cell set"
say "    Reset-bearing flops carry their own init value (dfrtp->0, dfstp->1),"
say "    which is why P11 must NOT be given -set-init-zero."
run "$PY $TOOLS/04_gen_models.py $LIB $P/models/puzzle_models.v \
        \$(grep -oE 'sky130_fd_sc_hd__[a-z0-9_]+' $P/extracted_netlist.v | sort -u)"

say "P4  GROUND TRUTH -- replay $SRC_PUZZLE/example_inputs.vcd (want: 0 mismatches)"
say "    The recorded waveform holds the real chip's outputs. Matching them"
say "    bit-for-bit is what proves the polygons were read correctly."
run "$PY $TOOLS/06_vcd_replay.py $SRC_PUZZLE/example_inputs.vcd $TOP $P/verify/tb_replay.v"
run "iverilog -g2012 -o $P/verify/replay.vvp $P/models/puzzle_models.v \
        $P/extracted_netlist.v $P/verify/tb_replay.v"
run "vvp $P/verify/replay.vvp | tail -3"

say "P5  Register graph + Tarjan SCC -- recover the blocks synthesis flattened"
run "$PY $TOOLS/07_structure.py $P/extracted_netlist.v $P/structure | head -30"

say "P6  Decompile the control logic into boolean equations (Liberty-driven)"
say "    Only the control flops: the 22 counter cones expand to megabytes of"
say "    repeated subexpression and say nothing that step P9 does not say better."
run "$PY $TOOLS/08_decompile.py $P/extracted_netlist.v $LIB success \
        > $P/structure/decompile.txt 2>&1 || true"
for F in u28_dfrtp_2 u26_dfrtp_2 u350_dfrtp_2 u390_dfrtp_2 u419_dfrtp_2; do
  run "$PY $TOOLS/08_decompile.py $P/extracted_netlist.v $LIB --flop \$F \
          >> $P/structure/decompile.txt 2>&1 || true"
done
run "cat $P/structure/decompile.txt"

say "P7  Which counter value gates each flop pair (11 on a column index, 11 not)"
run "$PY $TOOLS/09_slots.py $P/extracted_netlist.v $LIB \
        $P/structure/structure.json $P/structure | tail -12"

say "P8  FALSIFY the first hypothesis: feed 25 'rows+cols+no-touch' grids to the"
say "    netlist. All 25 rejected => extra constraints exist. The netlist is the"
say "    oracle; a reading of the gates is not."
run "$PY $TOOLS/10_uniqueness.py $P/extracted_netlist.v $P/models/puzzle_models.v \
        $TOP 25 $P/probe | tail -6"

say "P9  Read the region map straight out of the silicon: 121 single-cell trials"
say "    -- drive I=1 at exactly one position, see which counters increment."
run "$PY $TOOLS/11_probe_cells.py $P/extracted_netlist.v $P/models/puzzle_models.v \
        $TOP $P/structure/structure.json $P/probe"

say "P10 Identify the 8-flop register success compares against (star-count sweep),"
say "    and recover the full message catalogue by deliberately failing."
run "$PY $TOOLS/12_misc_probe.py $P/extracted_netlist.v $P/models/puzzle_models.v \
        $TOP $P/probe $SOL | tail -8"

say "P11 Bounded model checking on the gates: shortest unlock is provably 122"
say "    clock edges (yosys -seq K counts K-1 edges: K=122 UNSAT, K=123 SAT)."
for K in 122 123; do
  run "yosys -p \"read_verilog $P/models/puzzle_models.v $P/extracted_netlist.v; \
        hierarchy -top $TOP; proc; flatten; async2sync; dffunmap; opt; \
        sat -seq $K -set enable 1 -set-at $K success 1 -show I\" \
        > $P/solve/en1_$K.log 2>&1 || true"
  echo "    K=$K: $(grep -oE 'SAT solving finished - (model found|no model found)' "$P/solve/en1_$K.log")"
done

say "P12 Independent solve: z3 on the RECOVERED constraints + uniqueness proof"
say "    Different tool, different encoding. Must land on the same 121 bits."
run "$PY $TOOLS/13_starbattle.py $P/probe/regions.json $SOL"

say "P13 Recovered behavioural RTL, proved cycle-equivalent over 540 grids"
run "$PY $TOOLS/14_gen_rtl.py $P/probe/regions.json $SOL $P/rtl"
run "iverilog -g2012 -o $P/solve/eq.vvp $P/models/puzzle_models.v \
        $P/extracted_netlist.v $P/rtl/puzzle_recovered.v $P/rtl/tb_equiv.v"
run "vvp $P/solve/eq.vvp | tail -3"

say "P14 Drive the answer in and read O[7:0] -- the final string"
run "$PY $TOOLS/15_dump_output.py $P/extracted_netlist.v $P/models/puzzle_models.v \
        $TOP ${SOL}00 40 $P/solve | tail -22"

say "P15 The waveform Jane Street did NOT give us: success actually high"
run "$PY $TOOLS/16_make_vcd.py $P/extracted_netlist.v $P/models/puzzle_models.v \
        $TOP $SOL success_inputs.vcd"

say "P16 Render the human-readable answer files"
run "$PY $TOOLS/17_write_answer.py $P/probe/regions.json $SOL $P/answer"

fi

# =============================================================================
#  PART 3 -- the parts that are not needed to solve it, but are the fun bits.
# =============================================================================
if [ "$WHAT" = all ] || [ "$WHAT" = eggs ]; then

say "E1  Easter-egg sweep: diff the puzzle's layer set against the warm-up's,"
say "    then rasterise any drawn artwork and decode the Morse strip."
run "$PY $TOOLS/18_easter_eggs.py $SRC_PUZZLE/puzzle.gds $P/eggs $SRC_WARMUP/04_final.gds \
        | tail -60"

say "E2  Put the recovered blocks back on the die -- the physical hint, measured"
run "$PY $TOOLS/19_floorplan.py $SRC_PUZZLE/puzzle.gds $P/probe/regions.json $P/eggs | head -34"

say "E3  The sample inputs are not a failed solve -- they are a message"
run "$PY $TOOLS/20_vcd_message.py $SRC_PUZZLE/example_inputs.vcd $P/eggs \
        | grep -E '^VCD |^MESSAGE'"

fi

# =============================================================================
#  Collect the deliverables in one place.
# =============================================================================
if [ "$WHAT" = all ] || [ "$WHAT" = puzzle ]; then
say "Collecting deliverables into solution/"
cp "$P/answer/solution_grid.txt" "$P/answer/input_sequence.txt" solution/
cp "$P/rtl/puzzle_recovered.v" solution/
[ -f "$P/eggs/easter_eggs.txt" ] && cp "$P/eggs/easter_eggs.txt" solution/ || true
[ -f "$P/eggs/floorplan.txt"   ] && cp "$P/eggs/floorplan.txt"   solution/ || true
[ -f "$P/eggs/vcd_message.txt" ] && cp "$P/eggs/vcd_message.txt" solution/ || true
tr -d '\n' < "$P/solve/message.txt" > solution/answer.txt; echo >> solution/answer.txt
ls -1 solution/

cat <<'EOT'

--------------------------------------------------------------------------
DONE.
  the answer string      solution/answer.txt
  the grid + region map  solution/solution_grid.txt
  how to drive the chip  solution/input_sequence.txt
  recovered RTL          solution/puzzle_recovered.v
  easter eggs            solution/easter_eggs.txt, solution/vcd_message.txt
  winning waveform       success_inputs.vcd      (open in Surfer)
  what every step did    RUN.md, $TOOLS/README.md
--------------------------------------------------------------------------
EOT
fi
