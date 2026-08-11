# Running the pipeline

From `puzzle.gds` to the answer string, in one command. 

---

### 1. Prerequisites

Three things are not Python and have to come from your package manager:

```bash
sudo apt install yosys iverilog python3-tk
```


Verified on Python 3.12.3.

Waveform Viewer Installation: Surfer (Better Alternate to GTKWave)

```
mkdir -p ~/Downloads/surfer_install && cd ~/Downloads/surfer_install
wget "https://gitlab.com/api/v4/projects/42073614/jobs/artifacts/main/raw/surfer_linux.zip?job=linux_build" -O surfer_linux.zip
unzip surfer_linux.zip
chmod +x surfer
mkdir -p ~/.local/bin
mv surfer ~/.local/bin/
export PATH="$HOME/.local/bin:$PATH"
surfer *.vcd
```

---

## 2. Install

```bash
git clone https://github.com/NotCleo/GDS-to-RTL.git
cd GDS-to-RTL
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Verify by:
```bash
.venv/bin/python -c "import gdstk, shapely, z3; print('ok')"
```


---

## 3. Run it

```bash
bash run.sh 
```
To start completely clean:

```bash
rm -rf results solution success_inputs.vcd && bash run.sh
```

---

## 4. What you should see

Fourteen checkpoints. If all of them appear, the run is good.

| step | expected output |
|---|---|
| W2 | `nets: 84   nets with driver-count != 1: 0` |
| W3 | `84 exact matches, 0 mismatches`. The extracted netlist **is** the golden netlist |
| W5 | `ALL CHECKS PASSED: extracted netlist == golden netlist, and S <=> (A+B==496)` |
| W6 | `A = 11110101 = 245,  B = 11111011 = 251,  A+B = 496` |
| P2 | `nets: 738   nets with driver-count != 1: 0` |
| P4 | `REPLAY: 22 checks, 0 mismatches` / `EXTRACTION VALIDATED vs recorded silicon outputs` |
| P8 | `0 of 25 row/col/no-touch grids are ACCEPTED by the netlist` |
| P9 | `rows found: 0   cols found: 11   irregular groups: 11` |
| P11 | `K=122: no model found` then `K=123: model found` |
| P12 | `SOLUTIONS FOUND: 1` and `matches BMC answer: True` |
| P13 | `EQUIVALENCE: 0 success mismatches, 0 O mismatches over 540 grids` |
| P14 | `MESSAGE (one char per run): '(* TWO STARS *)'` |
| E1 | `MORSE   : PER ARENAM AD ASTRA` |
| E3 | `MESSAGE: 'The night sky awaits'` |

**P4 is the one that matters most.** It replays Puzzle's own recorded
waveform through the netlist recovered from raw polygons and compares against
the real chip's outputs. If it reports mismatches, stop, every later step will
be interpreting a circuit that does not exist.

---

## 5. What you get

A run writes `results/` and `solution/`. Only `results/` is gitignored, because
it is 7 MB of intermediates. Everything in it is also filed permanently in the
repo, so you can read the outputs without running anything:

| a run writes | the permanent copy in the repo |
|---|---|
| `results/puzzle/` | `puzzle-task/puzzle-recovery-files/` |
| `results/warmup/` | `warmup-task/warmup-work/warmup-results/` |
| `solution/` | committed at the root |
| the three egg files | `Easter-Eggs/` |

### `solution/`: the deliverables

Collected automatically at the end of a `puzzle` or full run.

| file | what it is |
|---|---|
| `answer.txt` | The recovered string: `(* TWO STARS *)` |
| `solution_grid.txt` | The region map, the unique solution grid, and the puzzle rules in plain text |
| `input_sequence.txt` | The 121-bit row-major stimulus and the clocking protocol: how to drive the chip |
| `puzzle_recovered.v` | Behavioural RTL for the whole design, proved cycle-equivalent to the extracted gates |
| `easter_eggs.txt` | Layer-set diff vs the warm-up, the rasterised logo, and the decoded Morse |
| `floorplan.txt` | Recovered blocks mapped back to die coordinates: the 11 + 11 + 1 hint, measured |
| `vcd_message.txt` | The two header fields, and the hidden ASCII decoded out of the *inputs* of `example_inputs.vcd` |

### `success_inputs.vcd`, at the repo root

Open it in Surfer and set `O` to ASCII format to watch the string stream out.

### `results/warmup/`: toolchain validation

| file | from | what it is |
|---|---|---|
| `instances.csv` | W1 | Every placement: cell type, x, y, orientation |
| `labels.csv` | W1 | Every surviving text label in the GDS |
| `extracted_netlist.v` | W2 | The netlist recovered from polygons alone |
| `extracted.json` | W2 | Same, machine-readable: instances + nets with pins and drivers |
| `undriven_nets.txt` | W2 | Nets with no driver (should be empty here) |
| `name_map.json` | W3 | **The golden check.** Each extracted `uNNN` mapped to its real DEF/netlist name |
| `sky130_models.v` | W4 | Simulatable cell models generated from Liberty `function :` strings |
| `sim.vvp` | W5 | Compiled testbench: golden and extracted netlists side by side |
| `warmup.vcd` | W5 | Waveform from that run |
| `bmc_solve.log` | W6 | Yosys SAT log, where A=245 and B=251 came from |
| `resynth_netlist.v` | W7 | The *forward* flow's output, for contrast with `01_netlist.v` |
| `resynth.log` | W7 | Yosys synthesis log, including the cell-count statistics |

### `results/puzzle/`: the real work

Top level, from P1 and P2:

| file | what it is |
|---|---|
| `instances.csv` | 9,875 placements: 728 logic cells, 8,221 vias, 676 taps, 204 decaps, 10 diodes, 36 Morse bars |
| `labels.csv` | Every text label, inside cells and at the top level |
| `extracted_netlist.v` | **The netlist.** 728 logic instances, 738 nets, 92 flip-flops, 67 cell types |
| `extracted.json` | Same, machine-readable. This is what steps P5 to P7 read |
| `undriven_nets.txt` | Nets with no driver |

| directory | from | contents |
|---|---|---|
| `models/` | P3 | `puzzle_models.v`, 66 cell models for exactly this design's cell set, with the correct flop init values (`dfrtp`→0, `dfstp`→1) |
| `verify/` | P4 | `tb_replay.v` (testbench built from the recorded VCD) and `replay.vvp`. The ground-truth check |
| `structure/` | P5 to P7 | `structure.txt` / `.json` (register graph + Tarjan SCC: 26 feedback groups), `decompile.txt` (control logic as boolean equations), `slots.txt` / `.json` (which scan-counter value gates each flop pair) |
| `probe/` | P8 to P10 | `uniqueness.json` (the 25 falsified grids), `regions.txt` / `.json` (**the region map, read out of the silicon**), `probe.log` (all 121 single-cell trials), `misc_probe.log` (star-count sweep + message catalogue), plus the testbenches and compiled sims |
| `solve/` | P11, P13, P14 | `en1_122.log` (UNSAT) and `en1_123.log` (SAT) from BMC, `eq.vvp` (the 540-grid equivalence sim), `dump.log` + `dump.vcd` + `message.txt` (the raw per-cycle `O[7:0]` and the decoded string) |
| `rtl/` | P13 | `puzzle_recovered.v` and `tb_equiv.v`. The behavioural model and its equivalence testbench |
| `answer/` | P16 | `solution_grid.txt` and `input_sequence.txt`, before they are copied to `solution/` |
| `eggs/` | E1 to E3 | `easter_eggs.txt`, `floorplan.txt`, `vcd_message.txt` |

`results/` totals about 7 MB.

---

## 6. Re-running one step

Every step prints the exact command it runs. Copy that `$ ...` line and edit it.
No step depends on hidden state.

`GDS-to-RTL/README.md` lists all 20 scripts with their inputs, outputs and
purpose. The number is the order they run in, and the `step` column is the
label `run.sh` prints.

If you move directories around, the only lines to change are the three at the
top of `run.sh`:

```bash
TOOLS=GDS-to-RTL         # the pipeline scripts
SRC_PUZZLE=puzzle-task   # puzzle.gds, example_inputs.vcd, layout.png
SRC_WARMUP=warmup-task   # the warm-up design, 00_source.v .. 04_final.gds
```

(`GDS-to-RTL/05_resynth.ys` is the one exception, since a yosys script cannot read a
shell variable, so its `read_verilog warmup-task/00_source.v` line is hardcoded.)

Two useful knobs on the extractor:

```bash
# island stitch threshold; the netlist is identical for anything in 0.00-0.13
GAP=0 .venv/bin/python GDS-to-RTL/02_extract_netlist.py puzzle-task/puzzle.gds /tmp/scan

# report the nearest foreign island per layer, with bounding boxes, so you can
# jump to that coordinate in KLayout
PROBE=enable,net_624 .venv/bin/python GDS-to-RTL/02_extract_netlist.py puzzle-task/puzzle.gds /tmp/scan
```

