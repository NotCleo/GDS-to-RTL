# The pipeline, stage by stage

One file, `gds_to_rtl.py`. It runs the warm-up first to prove the tools, then
the puzzle. Total runtime about **5 seconds**. The full terminal output of the
run this page describes is in [`run.log`](run.log).

```
bash RUN.sh                 warm-up validation, then the puzzle
bash RUN.sh --only puzzle
bash RUN.sh --no-iverilog   skip the two independent-simulator checks
```

Inputs are only the files Jane Street shipped, in `puzzle/` and `warmup/`, plus
the sky130 PDK in `pdk/`. Nothing else is read. Everything in
`puzzle-solution/` and `warmup-solution/` is deleted and rebuilt every run.

---

## Why one file, and why it is fast

The first version of this was twenty numbered scripts calling out to `yosys` and
`iverilog` for every question, and it took about four minutes. Almost all of
that was process startup and Verilog elaboration, repeated hundreds of times to
ask hundreds of nearly identical questions. Folding it into one file that keeps
its state in memory took it to 17 seconds. Measuring where those went took it to
**5**.

The whole pipeline rests on two things.

| | what it replaced |
|---|---|
| **A bit-parallel simulator for the recovered gates.** Every net is one Python integer; bit *k* of that integer is the net's value in trial *k*. A NAND across 564 independent grids is one machine AND and one XOR, so 564 grids cost the same as one. The combinational block is compiled once into a straight-line Python function, 830 lines for the puzzle. | 121 separate `iverilog` runs for the cell probe, 25 more for the hypothesis test, and a `vvp` run per message class |
| **A Tseitin encoder over the same parsed cell functions.** The netlist unrolls into CNF once, at the deepest depth needed, and a shallower depth is the same formula with the goal literal asserted a step earlier. 43,111 clauses over 14,498 variables, both depths and the uniqueness proof answered in 0.17 s. | `yosys ... sat -seq K`, about 40 s per depth, and no way to ask for uniqueness |

Both read cell behaviour from the same place: the `function` and `ff` entries in
the sky130 Liberty file. No cell truth table is written by hand anywhere, and the
circuit that gets simulated is the same object that gets handed to the solver.

`iverilog` is still used, exactly twice, as an independent second opinion: once
on the warm-up against the golden netlist, once on the puzzle against the
recovered RTL. `yosys` is no longer needed at all.

### Where the time goes now

| stage | before | after | what changed |
|---|---|---|---|
| W2 + P2, geometry to netlist | 5.50 s | **1.07 s** | connected components taken directly over the raw polygons instead of unioning them first, all coordinate transforms in one numpy pass, union-find over integers |
| P8, depth and uniqueness | 1.15 s | **0.18 s** | one encoding for both depths, constant folding and structural sharing while encoding, one solver instead of three |
| P10, message enumeration | 1.82 s | **0.41 s** | the same encoder changes, plus the back end picked by measurement |
| P11, the 564-grid equivalence | 6.40 s | **2.15 s** | the simulation sharded across cores, collected in shard order so the transcript does not depend on the core count |
| the tool version banner | 0.5 s | **0** | it was a second Python process that existed to import four packages and print their versions |
| **total** | **17.0 s** | **4.9 s** | |

Dropping `shapely.unary_union` is the single largest item and it needs a word,
because it looks like a shortcut and is not one. What that call computes is an
exact merged outline, which nothing downstream reads. What is wanted is the
connected components of "these two polygons touch", and running that relation
over the raw polygons gives the identical partition, because the distance from a
point to a union of shapes is the smallest of the distances to its members.
Measured on `puzzle.gds` the two agree island for island on all six layers, and
the direct version is eleven times faster.

### The SAT back end

`python-sat` bundles several CDCL solvers. Rather than pick one on reputation,
all of them were timed on this design's own two workloads, best of three, same
formula, same machine:

| back end | P8 depth question | P10 enumeration | total |
|---|---|---|---|
| **CaDiCaL 3.0** | 0.031 s | **0.419 s** | **0.449 s** |
| CaDiCaL 1.5.3 | 0.021 s | 0.630 s | 0.651 s |
| MiniSat 2.2 | 0.019 s | 0.642 s | 0.661 s |
| MiniSat-GH | 0.021 s | 0.650 s | 0.672 s |
| CaDiCaL 1.9.5 | 0.026 s | 0.658 s | 0.683 s |
| Glucose 4.2 | 0.022 s | 0.695 s | 0.717 s |
| Mergesat 3 | 0.028 s | 1.872 s | 1.900 s |
| Lingeling | 0.050 s | 2.046 s | 2.096 s |
| MapleCM | 0.218 s | 3.148 s | 3.366 s |

P8 is too small to separate them. P10 is fourteen incremental queries against a
solver that has to keep and reuse what it learned between them, and that is where
CDCL implementations differ. `SAT_BACKEND` at the top of `gds_to_rtl.py` is the
only line that has to change to swap it.

---

## Warm-up stages

The warm-up ships its own answer key: source, gate netlist, placed-and-routed
DEF, and GDS. It is the only place the extractor can be checked against a known
correct result.

| stage | what it does | result | writes |
|---|---|---|---|
| **W1** | Inventory `04_final.gds` | 1,099 placements: 79 logic in 16 types, 869 vias, 151 physical. Ports `A B S clk en rst_n` | `01_gds_inventory.txt` |
| **W2** | Extract a netlist from polygons | **84 nets, 0 with a driver count other than one** | `02_extracted_netlist.v` |
| **W3** | Check against the shipped DEF and netlist | **79 of 79** placements matched, **84 exact net matches, 0 mismatches** against a golden netlist of 84 nets | `04_golden_crosscheck.txt`, `07_name_map.json` |
| **W4** | Cell models from Liberty | 18 cells | `03_cell_models.v` |
| **W5** | Simulate golden and extracted side by side | 3,000 random cycles, **0 mismatches**; `S` equals `A+B==496` on **200 of 200** byte pairs | `05_equivalence.txt` |
| **W6** | Solve the warm-up from the extracted gates alone | minimum depth **8 clock edges**; `A = 248`, `B = 248`, **A + B = 496** | `06_sat_solve.txt` |

### What W3 actually proves

Two netlists are the same circuit exactly when they cut the same set of pins into
the same groups with the same ports attached. That is a statement about set
partitions, and names play no part in it, so exactness gets proved while every
instance is still called `u17` and every net `net_412`. The DEF match is only
there to recover the names afterwards.

### Three failure modes in W2 and W3

None of them crash. All three produce a netlist that parses cleanly and describes
a different circuit.

| trap | what goes wrong | why it is silent | the fix |
|---|---|---|---|
| Pin geometry from GDS labels | A text label tags exactly **one** polygon, but a real pin is often several polygons in different places in the cell, and the router may land on any of them | Pins go missing, and nets that should have joined stay separate | Read every `PIN / PORT / RECT` from the PDK LEF. That list is authoritative |
| Antenna diodes skipped as inert | The router uses a diode as a convenient place to change layers and **lands on it twice** | Skipping it tears one real net into two halves that never reconnect | Treat it as an electrical bridge: its connections are one net |
| Cell outline from the geometric bounding box | The nwell implant **overhangs** the cell outline, so every box is consistently too big | Every corner is wrong by the same amount, so **0 of 79** components match | sky130 draws the real abutment box on its own layer, **81/4** |

### W6, solving the warm-up without reading its source

The warm-up could be read: it is 79 cells and the source is provided. It was
solved by SAT instead, because that is the technique the puzzle needs later.
Unroll, encode, ask one question, read the answer. No gate traced by hand.

The solver returned `A = 248, B = 248`, which is 496 halved. Earlier runs of
this pipeline returned `242, 254` and `245, 251`. All three are correct: `A` and
`B` are eight bits each, so `A + B = 496` has exactly **15** solutions, `A` from
241 to 255, and the solver is free to return any of them. 496 is also the third
perfect number, `1+2+4+8+16+31+62+124+248`.

---

## Puzzle stages

Same extractor, no answer key. Validation now comes from a recording of the real
chip, from two tools agreeing, and finally from a behavioural model proved
cycle-equivalent to the gates.

| stage | what it does | result | writes |
|---|---|---|---|
| **P1** | Inventory `puzzle.gds` | bounding box 200 x 352.72 um, which is a 200 x 300 die plus something drawn below y = 0; 9,875 placements: **728 logic in 66 types**, 8,221 vias, 880 physical, 10 diodes, **36 that are not standard cells** | `01_gds_inventory.txt` |
| **P2** | Extract a netlist from polygons | **738 nets, 728 logic cells, 0 with a driver count other than one, 0 undriven** | `02_extracted_netlist.v` |
| **P3** | Cell models, and build the simulator | 66 cells; 738 nets, 642 gate outputs, 92 flops, 830 generated lines | `03_cell_models.v` |
| **P4** | Replay `example_inputs.vcd` | 312 rising edges, **624 outputs compared, 0 mismatches**. Every flop clock traces back to `clk` alone | `04_vcd_replay.txt` |
| **P5** | Register graph, Tarjan SCC, and decompile the one thing worth reading | 92 flops, 26 feedback groups, **23 of them two-bit pairs**. `success` is one latched flop, `u28_dfrtp_2`, and its set condition decompiles into **11 + 11** near-identical two-bit comparisons | `05_register_structure.txt` |
| **P6** | Falsify the first hypothesis | 25 grids with two per row, two per column, none touching: **0 accepted**, all 25 answered `TRY AGAIN` | |
| **P7** | 121 single-cell probes | **11 column counters, 11 irregular groups, 1 shared row counter**. Region sizes `14 21 7 5 28 8 11 9 6 8 4`, sum **121** | `06_region_map.txt` |
| **P8** | Gate-exact SAT | GF(2) linearity test: **20 of 20** predictions fail, so no linear algebra shortcut exists. **K=121 UNSAT, K=122 SAT** over 43,111 clauses; blocking clause re-solve **UNSAT**, so **the key is unique** | `07_sat_proof.txt` |
| **P9** | Independent solve with z3 | **exactly 1** solution to the probed constraints, and it **equals** the SAT key | |
| **P10** | Enumerate every string the chip can print | **5 messages**, 14 SAT queries, the last UNSAT | `10_message_catalogue.txt` |
| **P11** | Behavioural RTL, cycle equivalence | **0 success mismatches, 0 O mismatches over 564 grids** | `08_recovered_rtl.v`, `09_equivalence.txt` |
| **P12** | Drive the answer in, read `O[7:0]` | **`(* TWO STARS *)`**, `success` on enabled rising edge **122** | |
| **P13** | Render the answer and the waveform | `success` first high at t = 1,255,000 ps, rising edge 126 | `11_`, `12_`, `13_`, `14_success_inputs.vcd` |

### P2, the extraction, in three lines

1. Flatten every conductor polygon to top-level coordinates, then join any two on
   the same layer that overlap, so each group is one contiguous piece of metal.
2. Every via cut joins the metal below it to the metal above it.
3. Union-find over both, then look up which group covers each cell pin.

Same-layer overlap means connected. Different layers mean nothing without a cut
between them. That is the whole electrical content of a GDS file.

| conductor | shapes | conductors out |
|---|---|---|
| li1 | 10,819 | 5,472 |
| met1 | 12,606 | 3,001 |
| met2 | 8,517 | 2,060 |
| met3 | 2,560 | 811 |
| met4 | 867 | 45 |
| met5 | 162 | 18 |

The check that says the layer map and the coordinate transforms are right: a via
that landed on nothing would be floating in space.

| cut | bridged |
|---|---|
| mcon, li1 to met1 | 17,188 / 17,188 |
| via, met1 to met2 | 3,779 / 3,779 |
| via2, met2 to met3 | 951 / 951 |
| via3, met3 to met4 | 687 / 687 |
| via4, met4 to met5 | 108 / 108 |

**22,713 of 22,713** cuts bridged, none floating.

### P4, the replay against recorded silicon

`example_inputs.vcd` is a recording of the real chip: known inputs, and the
outputs it produced. Driving those inputs into a netlist built from polygon
coordinates alone and getting the same outputs back is the strongest check
available without an answer key, because the trace cannot have been fitted to.

If P4 ever reports a mismatch the pipeline stops, because every later stage would
be interpreting a circuit that does not exist.

### P7, the single-cell probe

Decompiling a counter's logic cone tells you it is gated on some value. It does
not tell you what that value means physically, and the 22 counter cones expand
into megabytes of repeated subexpression, so decompiling is not usable here.

Probing instead: put a star at exactly one grid position, clock the whole frame
through, and see which counters moved. A counter that ticks for cell (r, c) is
watching cell (r, c). 121 trials, one bit-parallel pass, 0.04 s.

Eleven columns and eleven irregular blobs come back. Eleven rows do not, for a
reason that is useful. The row counter is cleared at every row boundary, so at
the end of the frame it always reads zero. Sampling it in the cycle each star
arrives instead, it moves in **110** of 121 trials, and the 11 it misses are
exactly cells `10 21 32 43 54 65 76 87 98 109 120`, which is column 10 of every
row: the last cell of a row, where the counter is bumped and cleared in the same
cycle. One shared row counter only works if the grid arrives row-major at one
cell per clock, so exactly one row is ever in flight, which gives the input
format.

### P8, solving 2^121 possibilities

The netlist is unrolled over K clock edges and every gate is Tseitin encoded from
the same Liberty functions the simulator uses, plus one clause: `success = 1`.
The cone of influence of `success` is 471 of 738 nets, which drops the whole
output generator and is why this is cheap.

One unrolling to 122 edges, **14,498 variables and 43,111 clauses**, encoded in
0.09 s. A K-edge question is that same formula with the success literal asserted
one step earlier, so the shorter depth needs no re-encoding. The encoder folds a
gate whose inputs are already constant (113,959 times here, mostly because
`rst_n`, `enable` and `clk` are constants across the window) and shares a gate
identical to one already written (1,928 times), which is what takes the formula
down from the 130,385 variables and 390,772 clauses a naive encoding produces.

| K | result |
|---|---|
| 121 | **UNSAT** |
| 122 | **SAT** |

122 is therefore the shortest unlock: 121 cells in, verdict on the next edge.
Adding a blocking clause on the 121 recovered bits and re-solving returns
**UNSAT**, so the key is unique at gate level, not just unique under an
assumption about what the puzzle is.

### P10, and the fifth message

The old version of this pipeline drove four grid classes, read `O[7:0]`, and
reported four messages. That was a list of the grids tried rather than a
measurement of the ROM, and it was one message short.

The replacement: unroll from reset with all 121 input bits free and let the
solver enumerate every value the output bus can take on the first output edge,
then every value it can take on the second given the first. Two characters
separate every message, so when the enumeration returns UNSAT the catalogue is
closed.

Four first characters are reachable, `(`, `B`, `E`, `T`, and five two-character
prefixes, because `T` splits. Each prefix hands back the grid that produced it,
which then gets simulated to read the rest of the string.

| message | success | what triggers it |
|---|---|---|
| `EMPTY SKY` | 0 | an empty grid |
| `BIG BANG` | 0 | every cell a star |
| `TRY AGAIN` | 0 | any other wrong grid |
| **`TWO NOT TOUCH`** | 0 | every count right, two per row and per column and per region, and at least one touching pair |
| `(* TWO STARS *)` | 1 | the one grid that satisfies every rule |

`TWO NOT TOUCH` is the other name of Star Battle. The chip prints it only when
every count is correct and the no-touch rule is the one broken, which is a class
of grid a random sweep does not reach.

### P11, and why the vector set changed

Finding a fifth message means the four-verdict RTL was wrong, and the old
540-grid equivalence run passed only because none of its 540 grids reached the
fifth case. So P11 now asks z3 for **24** grids that satisfy every count and
touch, and adds them to the vector set: **564 grids, 0 success mismatches, 0
output mismatches**.

An equivalence run is only as good as its vectors, and these vectors were
extended by a solver result rather than by guesswork.

---

## Loose ends

| | |
|---|---|
| **Undriven nets** | none. All 738 nets have exactly one driver, first try, on both designs |
| **Nets with more than one driver** | none |
| **Combinational loops** | none. The topological sort of the gate graph completes, which is checked, not assumed |
| **Clock tree** | every one of the 92 flop clock pins traces back through buffers to the single primary input `clk`. There is no gated clock in this design |
| **The four un-reset flops** | `u34` to `u37` are `dfxtp_2`, no reset, so real silicon powers them up randomly. The pipeline runs the answer with them initialised low and again initialised high: `success = 1` and `(* TWO STARS *)` both times, so their power-up state is provably irrelevant to the result |
| **The same-layer gap tolerance** | The extractor treats two shapes on the same layer as one conductor if they come within 60 nm of each other without formally overlapping, which happens on 23 li1 groups on the puzzle and nowhere else. I checked whether the answer depends on that number, and it does not: at 0 nm, 20 nm, 60 nm and 120 nm the recovered net partition is byte-identical on both designs, so it is not a fitting parameter |
| **Every via cut lands on metal on both sides** | 22,713 of 22,713 on the puzzle. This is the check that says the rotations and mirrors were applied correctly, and it needs no answer key, so it works on the puzzle as well as the warm-up |

## Determinism

Every number on this page is byte-identical run to run. The region letters are
assigned by sorting regions on their lowest cell index rather than on set
iteration order, the counter pairs are sorted on instance index, the simulation
shards are collected in shard order rather than completion order, and nothing in
the pipeline depends on dictionary ordering.

Two places are allowed to move if the SAT back end is swapped, and only two. W6
has 15 valid answers and the solver may return any of them. And each message in
the P10 catalogue is illustrated by *an* example grid that produces it, where any
grid in the class would do. Neither is a result.
