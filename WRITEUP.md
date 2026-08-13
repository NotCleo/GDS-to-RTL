# How I solved it

A chip with no names on it, and what I did about it, in the order I did it.

---

## What I was handed

| file | what it actually is |
|---|---|
| `puzzle.gds` | 1.4 MB of polygons on numbered layers. No cell names, no net names, no hierarchy, no comments. |
| `example_inputs.vcd` | A recorded run of the real chip. `success` never goes high. |
| `layout.png` | A hint image, with one region marked "output generator" and a note saying I could ignore it at first. |
| a warm-up design | A small circuit shipped with its Verilog source, its gate netlist, its placed-and-routed DEF, and its GDS. |

The task, in three parts: recover a netlist from the layout, work out what the
circuit is for, then use that understanding to find the input that makes it say
yes and read out the string it prints.

### What a GDS actually contains

Worth being precise about this, because it shapes everything that follows.

A GDS is a geometry file. It stores polygons, each tagged with a layer number
and a datatype, plus a hierarchy of cells that can be instantiated at a position
with a rotation and an optional mirror. That is genuinely all. There is no
concept of a wire, a gate, a pin, or a connection. Two pieces of metal are
connected if and only if they physically overlap, and the file does not say so
anywhere. You have to work it out from the coordinates.

The standard cells were still named, which is the one significant break I got.
`sky130_fd_sc_hd__nand3_2` tells me what a cell does. What was stripped is
everything above that: which instance is which, what the nets are called, and
how the design was organised.

My first instinct was to open it in a viewer and stare. I tried the TinyTapeout
online viewer, then switched to GDS3D because I wanted to magnify specific
sections and the browser viewer fought me. Staring taught me almost nothing. A
layout at that zoom is texture. Two things did register and both mattered later:
a tall narrow column of something very repetitive on the right-hand side, and a
pale ring low on the die that I assumed was a via array I did not understand
yet.

---

## Day 1: I spent 80% of my time on the warmup

It is the only place in the whole puzzle where you can check your own work.

Suppose I write an extractor,
point it at `puzzle.gds`, and it produces a netlist. How do I know that netlist
is right? There is no answer key. A subtly wrong extraction does not crash. It
produces a circuit that is plausible, simulates cleanly, and means something
completely different from the real one. I would then spend three days carefully
reverse-engineering a circuit that does not exist.

The warm-up ships the truth. So the plan became:

| stage | what it buys me |
|---|---|
| Build the extractor against the warm-up | I can compare to the golden netlist exactly, net by net |
| Only then point it at the puzzle | Any disagreement later is about the puzzle, not about my tools |

That ordering saved me twice.

### Counting things before connecting them

Before any connectivity work, I just took inventory: what cells are placed,
where, in what orientation, and every text label that survived.

The warm-up came out at 230 standard cell instances, of which 79 are logic and
the rest are well taps and decoupling capacitors. Two shift registers, an adder,
a comparator, three clock buffers. The design computes `A + B == 496`.

Cheap step, and it frames everything. It also gave me the port names, because
top-level pin labels survive the flow even when internal names do not.

### Turning polygons into a circuit

The algorithm is simpler than I expected going in:

| step | what happens |
|---|---|
| 1 | For each conducting layer, take every polygon and merge overlapping ones into islands. Each island is one contiguous piece of conductor. |
| 2 | Walk the via layers. A via cut that touches island X on the layer below and island Y on the layer above means X and Y are the same electrical node. |
| 3 | Union-find over all of those relationships. Every resulting connected component is a net. |
| 4 | For each placed cell, look up where its pins are, find which net covers each pin, and emit Verilog. |

Step 1 is a union of overlapping polygons per layer. Step 2 needs a spatial
index or it is quadratic and unusable, so it goes through an R-tree. That detail
turned into the single hardest version requirement in the project: Shapely 2.0
changed `STRtree.query` to take a `predicate` argument and return integer
indices rather than geometries. On Shapely 1.8 the call signature does not
exist. There is no graceful fallback, so 2.0 is a hard floor.

Step 4 is where I made my first real mistake.

---

## The two bugs that produced a confident wrong answer

Neither of these crashed. Both produced a netlist that looked entirely fine.

| bug | what I did wrong | why it silently broke things | the fix |
|---|---|---|---|
| Pin geometry | Used the GDS text labels to decide which polygon is which pin | A label tags exactly one polygon. A real pin is often several polygons at different places in the cell. Pins went missing, and nets that should have been joined stayed separate | Read the pin rectangles out of the PDK's LEF. `PIN ... PORT ... RECT` is the authoritative geometry and lists every rectangle belonging to each pin |
| Antenna diodes | Treated `diode_2` as an inert protection device and skipped it | The router uses a diode as a convenient place to jump layers and lands on it twice. Skipping it tears one real net into two halves that never reconnect | Treat it as an electrical bridge: its two connections are the same net |

The diode one is the sort of thing that only surfaces if you have ground truth.
The netlist without diodes had the right cell count, no dangling pins and no
obvious defect. It just described a different circuit.

There was a third bug, less interesting but more infuriating. To recover
instance names I matched my extracted placements against the DEF, comparing cell
type and lower-left corner. I got 0 matches out of 79. Not a few, all of them.

The cause: I was using the geometric bounding box of each cell, and the nwell
implant overhangs the cell outline. So my box was consistently bigger than the
real one, and every corner was wrong by the same small amount. What the DEF
records is the abutment box, which sky130 stores as its own layer, 81/4. Reading
that instead gave 79 out of 79 immediately.

---

## Proving the extractor is exact

Four checks, increasing in strength:

| check | what it proves | result |
|---|---|---|
| Every net has exactly one driver | No shorts, no floating outputs, no gate driving into another gate's output | 84 nets, 0 violations |
| Every GDS placement matches a DEF component | Same cell, same corner, same orientation | 79 of 79 |
| Net partition matches the golden netlist | The two circuits are literally the same circuit | 84 exact matches, 0 mismatches |
| Simulate both netlists side by side for 3000 random cycles | They behave identically | All checks passed |

The third is the real proof, and it is worth explaining why it works without
names. Two netlists are identical if and only if they split the same set of pins
into the same groups, with the same ports attached to the same groups. That is a
statement about set partitions. Instance and net names are irrelevant to it. So
I could prove exactness while my extracted netlist still called everything `u17`
and `net_412`.

### Rehearsing the technique that would actually solve the puzzle

Then I did something that felt like showing off and turned out to be the most
useful hour of the week. I solved the warm-up from my extracted netlist alone,
using bounded model checking rather than by reading it.

I generated simulatable Verilog models for every cell by parsing the `function:`
strings out of the Liberty file, so the truth tables come from the PDK and
cannot be got wrong by hand. Then I handed the whole thing to a SAT solver and
asked one question: find inputs such that `S` is high at cycle 9.

It came back with A = 11110101 and B = 11111011. That is 245 and 251, which sum
to 496.

I never traced a gate. I asked the circuit a question and it answered. That is
the technique the entire puzzle turned on.

For completeness I also ran the flow forwards, synthesising the original Verilog
back down to gates with the same library. Same shape of cell mix out. It made
concrete what the reverse direction was undoing, including where the sixteen
recirculation multiplexers come from: the library has no enable flip-flop, so an
enable becomes a mux feeding a plain flop.

---

## Day 2: pointing it at the real thing

Same extractor, no changes.

| | warm-up | puzzle |
|---|---|---|
| placements | 230 | 9,875 |
| logic cells | 79 | 728 |
| nets | 84 | 738 |
| flip-flops | 16 | 92 |
| distinct cell types | 16 | 67 |

The 9,875 placements break down as 728 logic cells, 8,221 vias, 676 well taps,
204 decoupling capacitors, 10 antenna diodes, and 36 things that are not
standard cells at all. I noted those 36 and came back to them on the last day.

Nets came out at 738 with zero driver-count violations on the first try, which
was the moment I started believing the warm-up work had been worth it.

### Validating with no answer key

This is the step I would tell anyone not to skip.

The sample waveform is a recording of the real chip: known inputs, known
outputs, `success` low throughout. I turned it into a self-checking testbench by
replaying the recorded inputs into my extracted netlist and comparing every
output at every sampled edge against what the real chip did.

22 checks, 0 mismatches.

That is not a proof of correctness, but it is a very strong signal. My netlist,
built out of nothing but polygon coordinates, reproduces real silicon on a trace
I did not generate and could not have tuned against. From that point on, when
the netlist disagreed with me, I believed the netlist.

---

## What the gates mean

728 cells is far too many to read. So I stopped trying to read and started
looking at shape.

I built a graph over the flip-flops only, with an edge from A to B when A's
output reaches B's input through some amount of combinational logic, and ran
strongly-connected-component analysis on it. The reasoning: feedback loops are
where state machines and counters live, and a cycle in the register graph
survives synthesis because you cannot optimise away a loop.

That produced 26 feedback groups. Most were pairs of flops in a tight loop,
dozens of them, all the same shape.

Two-bit counters.

Next question: what gates each pair? If a pair only counts when some other
signal is active, the gating condition tells me what the pair is counting.

| what I found | how many |
|---|---|
| pairs gated on a column index | 11 |
| pairs gated on something not a column, not a row, and matching no pattern I could name | 11 |
| pairs not gated at all | 1 |

I also tried decompiling the logic cones into boolean expressions, which worked
fine for the small control flops and was useless for the counters. The 22
counter cones expand into megabytes of repeated subexpression. I could read
every line of it and understand nothing. That was the first hint that reading
was the wrong tool.

### The floorplan told me more than the logic did

At this point I did something I should have done on day one. I took the counter
flops I had identified and looked up their physical coordinates.

| what | how many | where |
|---|---|---|
| identical two-bit slices, stacked vertically | 11 | y = 185 to 286 |
| a conspicuous empty gap | | y = 147 to 185 |
| more identical slices, same stack | 11 | y = 49 to 147 |
| one slice on its own, off to the side | 1 | x = 80.5 |

The whole checker is a single vertical column occupying x = 114.8 to 126.3 of a
200 um wide die, split visibly into two halves. That narrow repetitive column I
had noticed on day one was the entire architecture, and it had been legible from
the first five minutes if I had known what I was looking at.

Eleven of one thing. Eleven of another. One of a third. And the counters
saturate at 3 rather than wrapping, so what they actually implement is "count up
to two, and notice if you ever exceed it".

Two per row. Two per column. Two per something.

### Why 23 counters and not 33

If you need two stars in each of 11 rows, 11 columns and 11 regions, you might
expect 33 counters. There are 23, and the missing ten are the rows.

The reason is the input protocol. The grid streams in row-major, one cell per
clock, so only one row is ever in flight at a time. A single counter serves all
eleven rows if you reset it at each row boundary. Columns and regions are
interleaved across the entire stream, so each one needs its own counter that
persists to the end.

That single asymmetry told me the input format before I had confirmed it any
other way.

---

## Day 3: I was confidently wrong

My hypothesis by now: two stars per row, two per column, and no two stars
adjacent including diagonally. A classic no-touch constraint. The eleven mystery
counters were, I assumed, part of the adjacency machinery somehow.

So I tested it, which is the only part of this day I am pleased with. I
generated 25 different grids that satisfied rows, columns and no-touch
perfectly, and fed each one to the netlist to see which it accepted.

| grids satisfying my hypothesis | grids the netlist accepted |
|---|---|
| 25 | 0 |

Zero. Not one of them.

That result was worth more than anything I had derived by reading. It told me
two things at once: there is a constraint I have not found, and my method for
finding constraints is not working.

The lesson I actually took, and applied for the rest of the week: the netlist is
the oracle, my reading of the netlist is only a hypothesis, and when they
disagree I am the one who is wrong. Stop theorising, start measuring.

---

## The probe, which is the part I am actually pleased with

The eleven mystery counters each watch some set of grid cells. I did not know
which cells. Reading the logic cone for even one of them produced pages of
boolean algebra I could not hold in my head, and I had already established that
approach did not work.

So I stopped reading and started poking.

For each of the 121 grid positions, I ran the chip with a star at that position
and nowhere else, and recorded which counters incremented.

That is it. That is the whole idea. One star at (3, 7), watch counter 4 tick,
therefore cell (3, 7) belongs to region 4. No inference, no theory, no algebra.
121 simulations, about thirty seconds of wall time.

| trials | rows found | columns found | irregular groups found |
|---|---|---|---|
| 121 | 0 | 11 | 11 |

Rows came back as zero because of the single shared row counter, exactly as the
23-versus-33 argument predicted. And the eleven mystery counters turned out to
watch eleven irregular contiguous blobs, of sizes:

```
8  11  4  9  5  7  14  8  21  28  6      sum = 121
```

They tile the grid exactly. Irregular regions, two stars each, on top of two per
row, two per column, and no two touching.

That is Star Battle. Two Not Touch.

The reason my 25 grids all failed is now obvious. Every one of them satisfied
rows, columns and adjacency, and not one of them respected the regions, because
I did not know regions existed.

---

## Day 4: solving it twice

I had a puzzle. I did not want to trust a single answer from a single tool, so I
solved it two independent ways and checked they agreed.

| method | what it operates on | what it knows about Star Battle |
|---|---|---|
| Bounded model checking | The extracted gate netlist itself | Nothing at all. It searches for any input making `success` go high |
| Constraint solving with z3 | The region map recovered by probing | Everything. It is handed the rules explicitly |

The first is the honest one. It never learns what the puzzle is. It searches the
actual recovered silicon.

Getting it to run correctly took some care with the pass ordering. The netlist
has to be flattened, then asynchronous resets converted to synchronous, and only
then can the flops be unmapped into something the solver handles. One thing I
had to be careful not to do was force all flops to start at zero. The puzzle
contains four `dfstp` flops, which reset high, and zeroing them silently changes
the circuit into one with no solution. The warm-up does want that flag, which is
exactly the sort of difference that makes copying your own earlier command line
dangerous.

Run at increasing depths, it gave a clean boundary:

| clock edges | result |
|---|---|
| 121 | no solution exists |
| 122 | solution found |

Which pins the protocol precisely: 121 cells go in one per clock, and `success`
rises on the very next edge.

The second approach enumerated all solutions rather than stopping at the first.

| solutions found | agrees with the model checker |
|---|---|
| 1 | yes |

Exactly one. The puzzle is well posed, and two entirely different tools given
two entirely different encodings landed on the same 121 bits.

### The check I actually trust

Both of those confirm the answer. Neither confirms that I understood the design.
It is perfectly possible to have the right answer and the wrong mental model.

So I wrote behavioural RTL for the whole chip from scratch, in terms of rows and
columns and regions and stars, as I now believed it worked. Then I simulated my
model and the extracted gates side by side against 540 different grids,
comparing both `success` and the full output byte at every cycle.

| grids | success mismatches | output byte mismatches |
|---|---|---|
| 540 | 0 | 0 |

Not just the right answer, but a model that behaves identically to the silicon
on hundreds of inputs I never tuned it against.

---

## The string

The last piece was the block the hint image said to ignore. Drive the correct
grid in, keep clocking past the point where `success` rises, and read the output
byte one character per cycle:

```
(* TWO STARS *)
```

`(* ... *)` is Verilog attribute syntax, wrapped around the rule of the puzzle.
I laughed.

Then I got curious about what else it could say and started feeding it wrong
answers on purpose:

| what I fed it | what it printed |
|---|---|
| no stars at all | `EMPTY SKY` |
| far too many stars | `BIG BANG` |
| a wrong but plausible grid | `TRY AGAIN` |
| the answer | `(* TWO STARS *)` |

Four messages in the output ROM, three of which exist purely to be funny at
someone who got it wrong.

---

## Going back for the rest

With the puzzle solved I went back for the 36 non-standard-cell structures from
day two, and for that pale ring I had dismissed on day one.

The 36 turned out to be Morse code, on a layer that is not a sky130 mask layer,
in a strip positioned below the die where nothing is ever fabricated. Two bar
widths in a 1:3 ratio, three gap sizes in 1:3:7. It reads `PER ARENAM AD ASTRA`,
which is Latin for roughly "through the sand to the stars". Sand is silicon and
the puzzle is about stars, so it lands twice.

The pale ring was the Jane Street logo, drawn out of 1,366 sub-micron metal-2
polygons in a 17 um square, connected to nothing. It is in the warm-up file too,
which means it was sitting in front of me on day one.

And then the one that stung. The sample waveform, the one described as inputs
that do not make `success` go high, is not a failed solve attempt. Its header
literally says "Leave no stone unturned". Each of its two frames uses only the
first seven columns of the grid, and each of the eleven rows is a seven-bit
ASCII character. Decoded, it reads:

```
The night sky awaits
```

The puzzle told me what it was about on the first day, in the one file I had
written off as a dead end.

---

## Where it ended up

| | |
|---|---|
| what the chip is | an 11x11 Star Battle validator, 728 gates, 92 flip-flops |
| how it is checked | 11 column counters, 11 region counters, 1 shared row counter, all 2-bit saturating |
| the answer | `(* TWO STARS *)` |
| how it is entered | 121 bits row-major, one per clock, `success` on edge 122 |
| independent confirmations | golden netlist match, recorded-silicon replay, model checking, constraint solving, 540-grid equivalence |
| time | four days |

---

## Timeline

| when | what |
|---|---|
| Day 1 | Warm-up end to end. Extractor written, three bugs found and fixed, exactness proved against the golden files, warm-up solved by model checking rather than by reading. |
| Day 2 | Puzzle extracted, 738 nets clean on the first attempt, validated against the recorded silicon trace. Register graph and counter structure recovered. |
| Day 3 | Wrong hypothesis, falsified 25 times out of 25 by the netlist itself. Floorplan read. The 121-trial probe, and the region map. |
| Day 4 | Solved twice independently, uniqueness proved, behavioural model proved equivalent over 540 grids, string read out, easter eggs swept. |
