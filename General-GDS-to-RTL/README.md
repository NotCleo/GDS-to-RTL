# General-GDS-to-RTL

- The puzzle pipeline with the puzzle taken out of it.
- Point it at any sky130 GDSII layout and it gives you back a gate netlist, cell models, behavioural RTL, and a report on the register structure.
- The RTL is not a guess: it is checked against the gates it came from before the run finishes.

    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds

- It imports [`GDS-to-RTL/gds_to_rtl.py`](../GDS-to-RTL/gds_to_rtl.py) rather than copying anything out of it, so the geometry code that runs here is the same code that was proved exact against the warm-up's golden netlist, net for net.
- The main pipeline is not modified and does not know this exists.

----

## What you get

| output | what is in it |
|---|---|
| `<stem>_01_inventory.txt` | every placement, orientation, label and layer in the file |
| `<stem>_02_netlist.v` | structural Verilog, recovered from polygon overlap alone |
| `<stem>_03_cell_models.v` | simulation models for the cell types the design uses, generated from the Liberty `function` and `ff` entries, no hand-written truth tables |
| `<stem>_04_structure.txt` | register graph, feedback groups, clock roots, and what each output depends on |
| `<stem>_05_recovered_rtl.v` | behavioural RTL: boolean equations for the logic, clocked blocks for the registers |
| `<stem>_06_function.txt` | what the circuit computes, as equations, and for a combinational design the exact function of every output plus its full truth table |
| `<stem>_07_equivalence.txt` | the recovered RTL run against the recovered gates in iverilog, and the mismatch count |
| `<stem>_08_crosscheck.txt` | only with `--def` and `--golden`: placement matching and the net-partition comparison |

- Every run also checks, and says so in the log: that each net has exactly one driver, that no net is undriven, that the gate graph has no combinational loop, and that every via cut landed on metal on both sides.
- A via with metal on one side only is what a wrong rotation or a wrong mirror looks like.

----

## Options

    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds -o out/
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --def mychip.def --golden golden.v
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --lef other.lef --lib other.lib
    python3 General-GDS-to-RTL/gds_to_netlist.py --show-layers

| flag | what it does |
|---|---|
| `-o DIR` | where to write, default `recovered/` |
| `--lef FILE` | merged LEF for the pin geometry, default the sky130 one in `pdk/` |
| `--lib FILE` | Liberty for the cell semantics, default the sky130 one in `pdk/` |
| `--def FILE` | a DEF to match placements against, which is also how instance names come back |
| `--golden FILE` | a gate netlist to compare the recovered net partition with |
| `--layers FILE` | a JSON layer table, for a PDK that is not sky130 |
| `--show-layers` | print the layer table this build uses, in the shape `--layers` wants |

- The cross-check needs both `--def` and `--golden`.
- It reports how many placements matched components, and how many nets partition their pins identically.
- That comparison is what makes the answer trustworthy, and it is worth doing on any design where you have the answer key, before you point the tool at one where you do not.

----

## Another PDK

- The layer numbers are sky130's.
- `--show-layers` prints them:

    {
      "conductor": [67, 68, 69, 70, 71, 72],
      "names":     {"67": "li1", "68": "met1", ...},
      "cuts":      {"67": "mcon", "68": "via", ...},
      "gap_um":    0.06
    }

- `conductor` lists the routing layers in stack order, bottom first.
- `cuts` maps a conductor layer to the name of the cut that connects it to the layer above.
- `gap_um` is how close two shapes on the same layer have to be before they count as one conductor.
- Edit those, pass the file with `--layers`, and pass that PDK's `--lef` and `--lib`.
- Nothing else in the extractor is sky130-specific: it reads pin rectangles out of LEF and cell behaviour out of Liberty.
- Cell names still have to be the PDK's.
- A layout whose cell definitions have been renamed to `CELL_1`, `CELL_2` and so on carries no way to know what any of them does, and no tool recovers that.

----

## Behaviour, and what this still cannot do

- Behaviour and intent are different things, and only one of them survives synthesis.
- The behaviour is fully recoverable, and the tool recovers it.
- Every cell's function comes out of the Liberty file, so a netlist of known functions is already a system of boolean equations, one per net.
- Writing that system down naively does not work, because substituting every equation into its consumer expands a cone into an expression exponential in its depth, which is why fully expanding a counter produces megabytes.
- The rule used instead is that a net keeps its own line when more than one thing reads it, when it is a port, when it holds state, or when folding it in would make the expression longer than sixteen terms, and is folded into its consumer otherwise.
- Every shared term is then written once, the output stays linear in the gate count, and the long thin buffer chains a synthesiser leaves behind collapse into the expression that uses them.
- The result is run against the gates before the run ends: exhaustively for a combinational design small enough to enumerate, and over two thousand clocked cycles otherwise.
- On the half-adder in `warmup/` that recovers `carry = a & b` and `sum = a & ~b | ~a & b` from the polygons alone, with all four input vectors checked.
- What it cannot do is tell you what the circuit is for.
- Synthesis is not a reversible transform.
- It flattens the module hierarchy, drops every signal name that the layout did not keep as a label, and leaves a flat sea of gates.
- The original `always` blocks cannot be reconstructed, because many different sources compile to the same gates, and the recovered RTL is only one of them.
- That is the difference between the machine-generated RTL here and [`puzzle-solution/08_recovered_rtl.v`](../puzzle-solution/08_recovered_rtl.v), which was written by hand from an understanding of what the gates were doing, and then proved cycle-equivalent over 564 input grids.
- Both are equivalent to the gates.
- Only the hand-written one says the circuit is an 11x11 Star Battle validator.
- The proof can be automated.
- The understanding is the work.
- What the structure report does is tell you where to look:

| what the report says | what it usually means |
|---|---|
| a feedback group of size 2 | a two-bit counter |
| a feedback group of size 8 or 9 | a wider counter, an accumulator or a state machine |
| a flop in no feedback group | a pipeline stage or a latched flag |
| an output that depends on few flops | a status bit worth decompiling by hand |
| an output that depends on most of them | leave it alone and probe it instead |

- A cycle in the register graph is the one structural feature that survives synthesis intact, because no optimiser can remove a loop.
- That is why the report leads with it.
- In this repository, the line `of size 2: 23` is what turned 728 anonymous cells into twenty-three counters and started the whole solve.
