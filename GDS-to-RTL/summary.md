# The pipeline, stage by stage

One file, `gds_to_rtl.py`. It runs the warm-up first to prove the tools, then
the puzzle. Total runtime about **15 seconds**. The full terminal output of the
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
ask hundreds of nearly identical questions.

The whole pipeline now rests on two things instead.

| | what it replaced |
|---|---|
| **A bit-parallel simulator for the recovered gates.** Every net is one Python integer; bit *k* of that integer is the net's value in trial *k*. A NAND across 564 independent grids is one machine AND and one XOR, so 564 grids cost the same as one. The combinational block is compiled once into a straight-line Python function, 830 lines for the puzzle. | 121 separate `iverilog` runs for the cell probe, 25 more for the hypothesis test, and a `vvp` run per message class |
| **A Tseitin encoder over the same parsed cell functions.** The netlist unrolls into CNF and goes to CaDiCaL. 390,772 clauses over 130,385 variables, answered in 0.44 s. | `yosys ... sat -seq K`, about 40 s per depth, and no way to ask for uniqueness |

Both read cell behaviour from the same place: the `function` and `ff` entries in
the sky130 Liberty file. No cell truth table is written by hand anywhere, and the
circuit that gets simulated is the same object that gets handed to the solver.

`iverilog` is still used, exactly twice, as an independent second opinion: once
on the warm-up against the golden netlist, once on the puzzle against the
recovered RTL. `yosys` is no longer needed at all.

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
| **W6** | Solve the warm-up from the extracted gates alone | minimum depth **8 clock edges**; `A = 242`, `B = 254`, **A + B = 496** | `06_sat_solve.txt` |

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

The solver returned `A = 242, B = 254`. An earlier run returned `245` and `251`.
Both are correct: `A` and `B` are eight bits each, so `A + B = 496` has exactly
**15** solutions, `A` from 241 to 255, and the solver is free to return any of
them. 496 is also the third perfect number, `1+2+4+8+16+31+62+124+248`.

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
| **P8** | Gate-exact SAT | GF(2) linearity test: **20 of 20** predictions fail, so no linear algebra shortcut exists. **K=121 UNSAT, K=122 SAT** over 390,772 clauses; blocking clause re-solve **UNSAT**, so **the key is unique** | `07_sat_proof.txt` |
| **P9** | Independent solve with z3 | **exactly 1** solution to the probed constraints, and it **equals** the SAT key | |
| **P10** | Enumerate every string the chip can print | **5 messages**, 14 SAT queries, the last UNSAT | `10_message_catalogue.txt` |
| **P11** | Behavioural RTL, cycle equivalence | **0 success mismatches, 0 O mismatches over 564 grids** | `08_recovered_rtl.v`, `09_equivalence.txt` |
| **P12** | Drive the answer in, read `O[7:0]` | **`(* TWO STARS *)`**, `success` on enabled rising edge **122** | |
| **P13** | Render the answer and the waveform | `success` first high at t = 1,255,000 ps, rising edge 126 | `11_`, `12_`, `13_`, `14_success_inputs.vcd` |

### P2, the extraction, in three lines

1. Flatten every conductor polygon to top-level coordinates and union it per
   layer, so each island is one contiguous piece of metal.
2. Every via cut joins the island below it to the island above it.
3. Union-find over both, then look up which island covers each cell pin.

Same-layer overlap means connected. Different layers mean nothing without a cut
between them. That is the whole electrical content of a GDS file.

| conductor | shapes | islands |
|---|---|---|
| li1 | 10,819 | 5,495 |
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

| K | variables | clauses | result |
|---|---|---|---|
| 121 | 129,325 | 387,595 | **UNSAT** |
| 122 | 130,385 | 390,772 | **SAT** in 0.44 s |

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
| **The same-layer gap tolerance** | The extractor joins islands on the same layer that sit within 60 nm of each other without formally overlapping, which happens 23 times on the puzzle. I checked whether the answer depends on that number, and it does not: at 0 nm, 20 nm, 60 nm and 120 nm the recovered net partition is byte-identical on both designs, so it is not a fitting parameter |

## Determinism

Every number on this page is byte-identical run to run. The region letters are
assigned by sorting regions on their lowest cell index rather than on set
iteration order, the counter pairs are sorted on instance index, and nothing in
the pipeline depends on dictionary ordering. The one place a legitimate
difference can appear is W6, where the warm-up has 15 valid answers and the SAT
solver may return any of them.
