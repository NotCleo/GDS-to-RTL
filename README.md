# ASIC Reverse-Engineering Puzzle 2026 

This repository contains my solution at solving [ASIC Reverse-Engineering Puzzle 2026](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/) hosted by Jane Street. 

I decided to call my submission "GDS-to-RTL", contrary to "RTL-to-GDS" :)

The "ASIC Reverse-engineering" involves recovering a circuit from a layout file, working out what the circuit perorms, and then solving it.

Check out [ReGDS: A Reverse Engineering Framework from GDSII to Gate-level Netlist](https://ieeexplore.ieee.org/document/9300272/), was a good starting point to get a glimpse of the netlist recovery procedure.

----

## Summary of Results

Below table lists all final deliverable files / outputs for the Puzzle :  

| Task | Output |
|---|---|
| String value recovered from the chip after driving in a valid input sequence | `(* TWO STARS *)` (see [13_output_string.txt](puzzle-solution/13_output_string.txt)) |
| Valid input sequence | 121 bits, row-major (see [12_input_sequence.txt](puzzle-solution/12_input_sequence.txt)) |
| The puzzle's region map, the unique solution grid | (see [11_solution_grid.txt](puzzle-solution/11_solution_grid.txt)) |
| The recovered behavioural RTL for the whole design | (see [08_recovered_rtl.v](puzzle-solution/08_recovered_rtl.v)) |
| The gate netlist recovered from the layout | 728 cells, 738 nets (see [02_extracted_netlist.v](puzzle-solution/02_extracted_netlist.v)) |
| The waveform with `success` actually high | (see [14_success_inputs.vcd](puzzle-solution/14_success_inputs.vcd)) |

### What the circuit is

The chip is an **11 x 11 Star Battle validator**, the puzzle also known as Two
Not Touch. A 121-bit grid is shifted in serially on `I`, one cell per rising clock
while `enable` is high, row-major. On the following edge it raises `success` if
the grid places exactly two stars in every row, every column and every one of
eleven irregular regions, 22 stars in total, with no two stars adjacent,
diagonals included. It then streams an ASCII verdict out of `O[7:0]`, one
character per clock.

The recovered RTL in
[`08_recovered_rtl.v`](puzzle-solution/08_recovered_rtl.v) is one flat module,
because that is what the netlist is: synthesis flattened the hierarchy and the
layout keeps no record of it. Written as a hierarchy, the same 728 cells are the
blocks below, and each one occupies a contiguous region of the die.

| block | what it would be in RTL | cells | flops |
|---|---|---|---|
| scan position counter | two 4-bit up counters (†), `row` and `col`, plus a `running` flag | 32 | 9 |
| region decoder | combinational lookup, cell index to one of eleven region ids | 147 | 0 |
| column star counters | 11 x 2-bit saturating counter with an equality compare against 2 | 81 | 22 |
| region star counters | 11 x the same counter, selected by the region decoder | 81 | 22 |
| row star counter and no-touch checker | one shared 2-bit counter cleared per row, plus a 12-deep shift register of `I` tapped at 1, 10, 11 and 12, feeding two violation flags | 45 | 16 |
| total star counter | 8-bit accumulator with an equality compare against 22 | 27 | 8 |
| success logic | a 23-input AND tree over every counter and the latch that holds `success` | 53 | 3 |
| output stage | a 4-bit character counter, a verdict lookup table and an 8-bit output register | 225 | 12 |
| clock tree | `clkbuf_4`, `clkbuf_8`, `clkbuf_16` | 33 | 0 |

That is 724 of the 728 cells and all 92 flops. The remaining 4 are buffers that
drive more than one block.

- (†) : 4 bits because each row and each column holds 11 cells.

There is no adder here in the arithmetic sense. Every count is small, so the
design uses 2-bit saturating counters and equality compares rather than an adder
and a magnitude comparator. The warm-up is the design with the adder: two 8-bit
shift registers, an 8-bit adder and a comparator against 496.

Where each block physically sits on the die, with the counts for each drawn box:

![Module map of puzzle.gds](Images/gds-module-map.png)

### The RTL behind each block

The same nine blocks, in the order the table lists them, with the lines of
[`08_recovered_rtl.v`](puzzle-solution/08_recovered_rtl.v) that implement each
one.

#### 1. Scan position counter

```verilog
localparam N = 11;

reg [3:0] col, row;
reg       done, done_d;

wire running   = enable & ~done;
wire last_col  = (col == N-1);
wire last_cell = last_col & (row == N-1);

if (running) begin
  if (last_col) begin
    col <= 0;
    row <= row + 1'b1;
    if (last_cell) done <= 1'b1;
  end else begin
    col <= col + 1'b1;
  end
end
```

This is the only thing that knows where in the frame the chip is. `col` counts
0 to 10 and wraps, `row` advances on each wrap, and `done` latches when cell 120
arrives and stops the scan for good. Four flops for `col`, four for `row`, one
for `done`. Nothing here looks at `I`, so the position and the payload are
independent, which is what lets every other block be written as "on a star, at
this position, do this".

#### 2. Region decoder

```verilog
wire [10:0] cell_no = row * N + col;

always @* begin
  region_id = 4'd0;
  case (cell_no)
    11'd0:   region_id = 4'd0;
    11'd1:   region_id = 4'd0;
    ...
    11'd13:  region_id = 4'd5;
    ...
    11'd120: region_id = 4'd4;
  endcase
end
```

A 121-entry constant lookup, position to region id, with no state at all. It is
the largest purely combinational block in the design, 147 cells and zero flops,
because synthesis flattens the case into AND and OR gates over the eight counter
bits. The table it holds is the region map, and that map is the one piece of the
design that could not be read out of the gates. It came from probing: one star
at one position, 121 times, watching which counter moved.

#### 3. Column star counters

```verilog
reg [1:0] ccnt [0:N-1];

if (star) begin
  if (ccnt[col] != 2'd3) ccnt[col] <= ccnt[col] + 1'b1;
end

if (ccnt[i] != 2'd2) all_ok = 1'b0;
```

Eleven counters of two bits each, 22 flops, one per column, each incremented
when a star lands in its column. They saturate at 3 instead of wrapping, so a
third star sticks at 3 and can never roll back around to a passing 2. Two bits
is enough because the only question ever asked is whether the final value equals
2, and anything above 2 is equally wrong.

#### 4. Region star counters

```verilog
reg [1:0] gcnt [0:N-1];

if (star) begin
  if (gcnt[region_id] != 2'd3) gcnt[region_id] <= gcnt[region_id] + 1'b1;
end

if (gcnt[i] != 2'd2) all_ok = 1'b0;
```

Identical to the column counters, and the same 22 flops, with one difference:
the index is `region_id` from the decoder rather than `col`. That single change
of index is the whole reason the design needs the region decoder, and it is what
turns a two-per-row-and-column puzzle into a Star Battle. It is also why the
first hypothesis failed: 25 grids that were perfect on rows and columns were all
rejected here.

#### 5. Row star counter and no-touch checker

```verilog
reg [1:0]   rowcnt;
reg [N-1:0] prev_row, cur_row;
reg         prev_cell;
reg         adj_err, row_err;

wire above_l = (col > 0)   ? prev_row[col-1] : 1'b0;
wire above_c =               prev_row[col];
wire above_r = (col < N-1) ? prev_row[col+1] : 1'b0;
wire touches = prev_cell | above_l | above_c | above_r;

if (star) begin
  if (rowcnt != 2'd3) rowcnt <= rowcnt + 1'b1;
  cur_row[col] <= 1'b1;
  if (touches) adj_err <= 1'b1;
end
prev_cell <= star;

if (last_col) begin
  if ((rowcnt + (star && rowcnt != 2'd3)) != 2'd2) row_err <= 1'b1;
  rowcnt    <= 0;
  prev_cell <= 0;
  prev_row  <= cur_row | (star << col);
  cur_row   <= 0;
end
```

Two jobs share one block because they share the same memory of the recent past.

There is one row counter rather than eleven. Only one row is ever in flight, so
`rowcnt` is checked against 2 at the last column and cleared in the same cycle,
which is where the 11 + 11 + 1 arrangement on the die comes from. The `(rowcnt +
star)` term in the check exists because the eleventh star of a row arrives on the
same edge the row is being judged.

The no-touch check only ever looks backwards. When a star arrives, the four
neighbours that have already been seen are the cell to the left and the three
above it, so those four are all it needs; the forward neighbours will run the
same test themselves when their turn comes. `prev_cell` holds the left one and
`prev_row` holds the row above. In the gates this is a single 12-deep shift
register of `I` tapped at positions 1, 10, 11 and 12, which is the same object:
11 cells back is directly above, so 10, 11 and 12 back are the three above and 1
back is the left. 16 flops, being 2 for `rowcnt`, 11 for `prev_row`, 1 for
`prev_cell`, and the two error flags, which latch and never clear.

#### 6. Total star counter

```verilog
reg [7:0] total;

if (star) begin
  total <= total + 1'b1;
end

  wire counts_ok = ~row_err & (total == 8'd22) & all_ok;
```

Eight bits, not five, because it has to count all the way to 121 without
wrapping. It is only ever compared for equality, against 22 for the verdict and
against 0 and 121 for the two degenerate messages, so no magnitude comparator is
built. This counter is redundant against the eleven column counters, which
already force 22 stars between them, and the chip carries it anyway because the
output stage needs to tell an empty grid from a full one.

#### 7. Success logic

```verilog
reg succ_q;

always @* begin
  all_ok = 1'b1;
  for (i = 0; i < N; i = i + 1) begin
    if (ccnt[i] != 2'd2) all_ok = 1'b0;
    if (gcnt[i] != 2'd2) all_ok = 1'b0;
  end
end

if (done & ~done_d)
  succ_q <= ~adj_err & ~row_err & (total == 8'd22) & all_ok;

assign success = succ_q;
```

The 23 inputs to the AND tree are 11 column compares, 11 region compares and the
row result, plus the total and the two error flags. `done & ~done_d` is a
one-cycle pulse on the edge after the last cell, so the verdict is computed once,
on edge 122 and not edge 121, and that is exactly why the SAT solver proved 121
edges unsatisfiable and 122 satisfiable. `succ_q` is written nowhere else, so it
holds its value for the rest of time. At gate level that shows up as the
`| (u28.Q & ...)` term feeding the flop back into itself.

#### 8. Output stage

```verilog
wire counts_ok = ~row_err & (total == 8'd22) & all_ok;

always @* begin
  if      (total == 8'd0)             j = 0;
  else if (total == 8'd121)           j = 1;
  else if (counts_ok & ~adj_err)      j = 2;
  else if (counts_ok &  adj_err)      j = 4;
  else                                j = 3;
end

always @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    optr <= 0; emitting <= 0; o_q <= 8'h00;
  end else if (done & ~done_d) begin
    emitting <= 1'b1; optr <= 5'd1; o_q <= rom[0];
  end else if (emitting && optr < mlen) begin
    o_q  <= rom[optr];
    optr <= optr + 1'b1;
  end else begin
    o_q <= 8'h00;
  end
end

assign O = o_q;
```

The largest block on the die at 225 cells, and the one the provided layout image
labels as safe to ignore. It is a five-way selector into a small ASCII ROM,
clocked out one character per cycle starting on the same edge `success` settles.
`j` picks the message: 0 for `EMPTY SKY`, 1 for `BIG BANG`, 2 for
`(* TWO STARS *)`, 3 for `TRY AGAIN` and 4 for `TWO NOT TOUCH`. Index 4 is the
one that took a solver to find, because reaching it means getting every count
right and breaking only the adjacency rule.

The 12 flops are the character pointer and the 8-bit output register. `optr` is
declared five bits here and the gates only build four of them, since the longest
message is 15 characters.

#### 9. Clock tree

```verilog
always @(posedge clk or negedge rst_n) begin
```

There is no RTL for this block. Every sequential element in the design is on that
one line, and the buffer tree is inserted by synthesis to drive 92 clock pins
from a single pad. It appears in the extracted netlist as 32 buffers in three
levels, one `clkbuf_16` at the root and `clkbuf_8` then `clkbuf_4` below it:

```verilog
sky130_fd_sc_hd__clkbuf_16 u201_clkbuf_16 (.A(clk), .X(net_660));
sky130_fd_sc_hd__clkbuf_8 u1_clkbuf_8 (.A(net_660), .X(net_505));
sky130_fd_sc_hd__clkbuf_4 u0_clkbuf_4 (.A(net_505), .X(net_000));
```

Confirming that this is all it is mattered more than it sounds. Every one of the
92 clock pins traces back through these buffers to `clk` with no gating anywhere,
which is what makes it safe to reason about the whole chip one rising edge at a
time.


----

## Summary of all Easter Eggs found

Nine of them, in the order I found them. Each has its own file with what it is,
where it was, how I found it and when.

| # | Easter Egg | Where it was | Write-up |
|---|---|---|---|
| 1 | The **Jane Street logo**, etched in metal 2. 1,366 floating polygons in a 17.1 um square | [puzzle.gds](puzzle/puzzle.gds), and the warm-up GDS too | [01](Easter-Eggs/01_easter_egg.txt) |
| 2 | **"PER ARENAM AD ASTRA"** in Morse code, Latin for "through the sand, to the stars". 36 bars on a layer that is not a sky130 mask layer, below the die | [puzzle.gds](puzzle/puzzle.gds), layer 200/0 at y = -52.72 um | [02](Easter-Eggs/02_easter_egg.txt) |
| 3 | **"Leave no stone unturned!"**, a note left for a human where a simulator would write its own name | [example_inputs.vcd](puzzle/example_inputs.vcd), the `$version` field | [03](Easter-Eggs/03_easter_egg.txt) |
| 4 | **"Sat Dec 31 23:59:60 2016"** (†), a real leap second and the most recent one ever inserted into UTC | [example_inputs.vcd](puzzle/example_inputs.vcd), the `$date` field | [04](Easter-Eggs/04_easter_egg.txt) |
| 5 | **Read the waveform as ASCII.** The instruction that unlocks the whole output side, hidden in plain sight as a passing link | the [puzzle blog post](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/) | [05](Easter-Eggs/05_easter_egg.txt) |
| 6 | **"The night sky awaits"**, in the *inputs*. 11 rows of 7 bits, because standard ASCII needs 7 | [example_inputs.vcd](puzzle/example_inputs.vcd), the `I` input, both frames | [06](Easter-Eggs/06_easter_egg.txt) |
| 7 | **496 is the third perfect number**, `1+2+4+8+16+31+62+124+248`, and `A+B=496` has exactly 15 eight-bit solutions | [warmup/00_source.v](warmup/00_source.v) | [07](Easter-Eggs/07_easter_egg.txt) |
| 8 | **11 + 11 + 1 drawn on the die.** Every counter in one narrow vertical column, in two stacks of eleven plus a loner | [puzzle.gds](puzzle/puzzle.gds), flip-flop placement at x 114.8 to 126.3 | [08](Easter-Eggs/08_easter_egg.txt) |
| 9 | **Five messages, not four.** `EMPTY SKY`, `BIG BANG`, `TRY AGAIN`, **`TWO NOT TOUCH`** and `(* TWO STARS *)`, the last two being the puzzle's own name and its rule in OCaml comment syntax | the output ROM (see [10_message_catalogue.txt](puzzle-solution/10_message_catalogue.txt)) | [09](Easter-Eggs/09_easter_egg.txt) |

`TWO NOT TOUCH` is the least reachable of the five. The chip prints it only for
a grid that gets every count right, two stars in every row, every column and
every region, and then breaks exactly one rule: two stars touch. So it names the
rule that was broken, and that rule is the other name of the puzzle. No random
sweep reaches it. I found it by asking a SAT solver to enumerate every string the
output bus can produce, over the fourteen queries that closed the list.

#### Note : 

In Easter Egg (3), I ran a sample RTL to see how iverilog produces a normal VCD file : 

    iverilog -g2012 -o sim.out counter.v tb_counter.v
    vvp sim.out
    less counter.vcd          # or: cat counter.vcd

To which is comes up as : 

```
$date
	Tue Aug 18 04:49:16 2026
$end
$version
	Icarus Verilog
$end
$timescale
	1ps
$end
```

As you can see it prints the name of the tool and not a human message.


#### (†) : 

I thought Dec 31 2016 must be deliberate, but then came across the [closest blog](https://blog.janestreet.com/a-brief-trip-through-spacetime/) posted (Jan 9 2017) which mentions the word "space", close enough to "stars" (PLEASE TAKE THIS AS JOKE)


#### Note : 

A perfect number is a positive whole number that equals the sum of its positive proper divisors, leaving out the number itself;

    496 (1 + 2 + 4 + 8 + 16 + 31 + 62 + 124 + 248)

#### Note : 

A total of 9 Easter Eggs = number of positive proper divisors of 496 (PLEASE TAKE THIS AS A JOKE)
    
----

## Documentation (50 min read)

I have documented my entire solution's implementation is this single readme file, below table is a glimpse of what follows;

#### Sections (I) through (VII) discuss the core findings (15 min read)

#### Sections (VIII) discusses the complete implementation details (35 min read) 

| Title | What it is about |
|---|---|
| (I) What were the files provided for the puzzle | You can have a look into the puzzle's provided input files |
| (II) The first breakthrough moment  | Discusses my first breakthrough while inspecting the puzzle's waveform file |
| (III) What I did  | A summary of what I did |
| (IV) What the puzzle turned out to be  | A summary of what the solution of this puzzle is |
| (V) Success Waveform  | The puzzle's main solution/deliverable component |
| (VI) How to run | Quick start / Installations |
| (VII) Directory Layout  | Solution's File layout |
| (VIII) Full Picture  | Complete breakdown of the solution |

----

## (I) What were the files provided for the puzzle

The puzzle provided the two sets of files : 

#### Set I (Main Puzzle) 

| File | What it is about | 
|---|---|
| [GDS file](https://github.com/janestreet/asic-puzzle-2026/blob/master/puzzle.gds) (1.4MB) | contains metal, routing, and active transistor layers, with the cell names, net names and hierarchy stripped out |
| [Layout image](https://github.com/janestreet/asic-puzzle-2026/blob/master/layout.png) (136KB)| an image of the GDS file with the I/O's labelled for reference |
| [Example Inputs VCD](https://github.com/janestreet/asic-puzzle-2026/blob/master/example_inputs.vcd) (8.4KB)|  driven by incorrect inputs, with a "success" flag that stays low (we need to drive it high, after providing the circuit with correct inputs). |

#### Set II (Warmup) 

| File | What it is about | 
|---|---|
| [RTL source file](warmup/00_source.v) (1.2KB) | The original Verilog source code of the example design |
| [Netlist file](warmup/01_netlist.v) (19KB)| Synthesized netlist comprising of a list of standard cells and connections |
| [Netlist file (with power rails)](warmup/02_netlist_with_power_rails.v) (30KB)| Netlist with VDD and GND rails added |
| [post_pnr DEF file](warmup/03_post_place_and_route.def) (112KB) | Physical layout of cells and routing connections, corresponding to cell and net names. |
|[GDS file](warmup/04_final.gds) (306KB)| The final manufacturable layout file, with many internal names removed |

The warmup puzzle is a small example design and was run through the same RTL to GDS flow, to obtain the GDS file (similar to main puzzle GDS). The example design consists of two shift registers, an adder, and a comparator, outputting success if A + B == 496.

The whole flow was carried out using SkyWater's 130 nm PDK, see [more](https://skywater-pdk.readthedocs.io/en/main/).

-----

#### Note : The Layout image provided reveals the following I/O,

| I/O | What it is about | 
|---|---|
| clk (input) | drives all sequential elements (d-flop based counters) |
| rst_n (input) | active low resets to all sequential elements |
| enable (input) | active high enable to all sequential elements |
| I (input) | serial 1 bit input wire (we drive the puzzle cells serially through this) |
| O[7:0] (output) | 8 bit output vector displaying status of puzzle's state |
| success (output) | driven high when a valid/solved puzzle was driven in |

----

##### Note : 

I ran the three puzzle files through exiftool for a preliminary check and found nothing interesting.

I ran the warmup files and you will notice the file size going from 

- 1.2 KB (00_source.v) 
- 19 KB (01_netlist.v) 
- 30 KB (02_netlist_with_power_rails.v)
- 112 KB (03_post_place_and_route.def)
- 306KB (04_final.gds). 


-----

Here's how the waveform (of the provided VCD file) looks like : 

You will notice the "success" flag remains low throughout.

![Surfer showing waveform of example inputs VCD file](Images/example_inputs_waveform.png)

----

## (II) My first breakthrough moment 

Switching to ASCII (I rarely use ASCII and prefer staying in Decimal/Hexadecimal/unsigned Integer) was the first breakthrough, I was on the [blog site](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/), and my eyes fell on : 

![Blog Site highlighted](Images/switching-to-ascii-moment.png)

----

It was at this point while viewing the waveform when I decided to switch to viewing the VCD file in ASCII.

Which revealed the following message "TRY AGAIN" (at 1255000 ps marker): 

![Surfer showing waveform displaying "TRY AGAIN"](Images/try_again_message.png)


----

## (III) What I did

- Extracted a netlist from the raw geometry present in the puzzle GDS file.
- Proved the extractor pipeline exact against the warm-up's golden files, then validated it against the real chip's recorded outputs. 
- Recovered the register structure, read the design's hidden data out of the silicon by probing it 121 times, solved the resulting puzzle two independent
ways, and proved a behavioural model cycle-equivalent to the gates.

----

## (IV) What the puzzle turned out to be

- An "11x11 Star Battle (Two Not Touch) Validator". Two stars per row, per column and per region, no two
touching. Exactly one grid works. Drive in a solved 11x11 Two Not Touch Puzzle grid serially and the chip prints:

```
(* TWO STARS *)
```

## (V) Success Waveform 

It was found that to drive "success" flag high, the following input sequence was needed : 

    0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000

![Surfer showing success high and O[7:0] spelling the verdict](Images/success-waveform.png)


##### Note :

Star Battle is also referred to as Two Not Touch

- One can read about how the puzzle works [here](https://krazydad.com/twonottouch/intro_tutorial/)

##### Want to try the puzzle from this challenge? 

- See [here](TwoNotTouch-Interactive-Puzzle/)


##### Want to try the puzzle?

- Check out this sample [interactive Two Not Touch Puzzle](https://krazydad.com/play/starbattle/?kind=10x10&volumeNumber=2&bookNumber=1&puzzleNumber=24)

----

## (VI) How to run 

The whole flow is one Python file. The table below is everything it needs, plus
the tools I used by hand to look at things.

| Name | Type | Why it was used |
|---|---|---|
| **gdstk** | Python package | GDSII parsing and hierarchy flattening: the front end of the extractor |
| **shapely** | Python package | Polygon building, overlap testing and STRtree spatial indexing: the core of net extraction. **Requires 2.0 or newer.** 1.x has no `predicate=` keyword and returns geometries instead of integer indices, which silently builds the wrong netlist |
| **numpy** | Python package | Every coordinate transform in the extractor is one array operation over all polygons at once rather than one call per polygon |
| **python-sat** | Python package | The SAT back end. It bundles several solvers behind one API; the one this pipeline loads was picked by timing them all on this design's own two workloads, and the table is in section (VIII). It solves the unrolled gate netlist: the 121-bit key, the minimum-depth bound, the uniqueness proof, and the enumeration of every string the output ROM holds |
| **z3-solver** | Python package | The independent constraint solve of the recovered puzzle, and generating the grid classes used to falsify hypotheses and to stress the equivalence run |
| **iverilog + vvp** | CLI tool | Used exactly twice, as an independent second opinion: golden versus extracted on the warm-up, and gates versus recovered RTL on the puzzle |
| **KLayout** | GUI tool | Layout viewer, for spot-checking a coordinate |
| **Surfer** | GUI tool | Waveform viewer. Switching a bus to ASCII is a right click, which is what easter egg 5 needs |
| **GDS3D** | GUI tool | 3D rendering of the layer stack, separating power grid from routing and isolating poly over diffusion to see the transistors. Where I found the logo |
| **Tiny Tapeout GDS Viewer** | Web tool | Zero-install browser view of the layout for a first look |
| **sky130_fd_sc_hd Liberty (`.lib`)** | PDK data | Cell pin directions, the boolean `function` of every combinational output, and the `ff` group of every flop. Every truth table in this flow comes from here, none are hand written |
| **sky130_fd_sc_hd merged LEF** | PDK data | The complete pin landing geometry, `PIN / PORT / RECT`. Reading pins from GDS text labels instead loses every pin rectangle the label does not tag |
| **argparse, collections, concurrent.futures, contextlib, json, math, os, re, subprocess, sys** | Stdlib | Argument handling, grouping and counting, running the simulator shards, stage timing, interchange, coordinate arithmetic, Liberty and Verilog parsing, and shelling out to iverilog |

----

### Update: yosys is not used any more, and this is why

The earlier version of this pipeline used **yosys** for every formal question it
asked. It does not any more. Neither tool is better than the other in general,
they answer questions with different cost models, and the questions this puzzle
asks happen to sit badly with one and well with the other.

#### What yosys is

Yosys is an open-source synthesis framework. Its day job is the forward
direction: read Verilog, elaborate it into a netlist of generic gates, optimise
it, and map it onto a real cell library. It also has a formal side, and that is
the part I was using. `sat -seq K` unrolls a design over K clock edges, hands the
result to a SAT solver built into yosys, and answers questions about what the
design can be made to do in K edges.

That is exactly the shape of the question the puzzle asks, so it is where I
started, and I want to be clear that the tool did nothing wrong.

#### What I asked it

Roughly this, once per depth:

```
read_verilog puzzle-solution/03_cell_models.v
read_verilog puzzle-solution/02_extracted_netlist.v
prep -top puzzle_extracted
sat -seq 122 -set-def-inputs -set success 1 -show I
```

Read the cell models, read the 728-cell netlist, elaborate, unroll 122 deep,
constrain `success` to 1, print the input trace.

#### How it went

It worked. It gave the right answer. The problems were all about cost and about
what the interface can express.

| | |
|---|---|
| Time for one depth | about **40 seconds** |
| Of which, actual search | a small fraction. Almost all of it is parsing and elaborating the same 728 cells and 66 cell models again |
| Depths I needed | at least two, 121 and 122, to prove 122 is the minimum |
| Queries the message catalogue needs | **14**, each one a slightly different constraint on the same circuit |
| Uniqueness | not expressible. `sat` hands back one satisfying assignment. There is no interface to say "now give me a different one", so proving the key unique means constructing a new design with the found key blocked and elaborating the whole thing again |
| Total, in practice | several minutes for what is one circuit asked sixteen questions |

The shape of the problem is: **one circuit, many nearly identical questions.**
A command-line tool has to re-read the world for every question, because the
world does not survive between invocations. That is not a flaw in yosys. It is
what a command-line tool is.

| yosys is the right tool when | it is the wrong tool here because |
|---|---|
| you have Verilog and want gates | I already have gates and want an answer |
| you want one formal question answered and do not want to write code | I want sixteen, and the fifteen after the first are cheap only if the first one leaves something behind |
| you want equivalence checking between two RTL descriptions | my equivalence check is gates against RTL, and iverilog does that in one simulation |
| the design is large enough that a hand-written encoder would be slow | 728 cells is small. The encoder is 40 lines |

So I wrote the encoder.

#### What a Tseitin encoder is

A SAT solver eats exactly one thing: a formula in **conjunctive normal form**,
an AND of ORs. My circuit is a nest of gates. Something has to translate.

The obvious translation is substitution. Take the output, replace it by its
gate's expression, replace each of that gate's inputs by its own expression, and
keep going until nothing but input variables is left. This does not work. Every
level of substitution can roughly double the size of the expression, so a
circuit 30 gates deep produces an expression with a billion terms, and this
circuit unrolled over 122 clock edges is far deeper than 30. The formula becomes
too large to write down long before anyone tries to solve it.

**Tseitin's trick is to stop substituting and start naming.**

Give every wire in the circuit its own variable. Then, for each gate, write down
only the local fact that its output variable equals its function of its input
variables. Nothing else. For an AND gate with inputs `a` and `b` and output `w`,
the fact "`w` is `a` AND `b`" is these three clauses:

```
(!a | !b |  w)      if a and b are both 1, then w must be 1
( a      | !w)      if w is 1, then a must be 1
(     b  | !w)      if w is 1, then b must be 1
```

Those three clauses together allow exactly the four rows of the AND truth table
and forbid everything else. The encoder in `GDS-to-RTL/gds_to_rtl.py` writes
three shapes, because after the Liberty functions are parsed everything reduces
to AND, OR and XOR with inversion carried on the literal sign:

| gate | new variable | clauses |
|---|---|---|
| `w = a & b` | one | `(!a \| !b \| w)`, `(a \| !w)`, `(b \| !w)` |
| `w = a \| b` | one | `(a \| b \| !w)`, `(!a \| w)`, `(!b \| w)` |
| `w = a ^ b` | one | `(!a \| !b \| !w)`, `(a \| b \| !w)`, `(a \| !b \| w)`, `(!a \| b \| w)` |

Inversion costs nothing at all: `!x` is just the literal `x` with a minus sign,
so an inverter is not encoded, it is absorbed.

Now the whole circuit is the AND of every gate's little bundle of clauses, plus
one more clause pinning the output you care about to 1. **The size is linear in
the number of gates**: three or four clauses and one variable each, however deep
the circuit is. Substitution was exponential. This is not.

The catch, and the reason it is a trick worth naming, is that the resulting
formula is not *equivalent* to the original. It has variables the original did
not have. What it is instead is **equisatisfiable**: it has a solution exactly
when the original does. And the wire variables are not free to take any value,
because each one is nailed down by its own three clauses to whatever the gate
feeding it produces. So a solution the solver returns is a genuine simulation of
the circuit, and the input bits read off it are genuine inputs.

The last piece is time. A sequential circuit run for K clock edges is a
combinational circuit K copies deep: unroll it, give each copy its own set of
wire variables, and wire copy `t`'s flip-flop outputs into copy `t+1`'s inputs.
"What can this chip be made to do in 122 clock edges" is then one formula.

#### Why that fits this problem

Because the cost moves to the right place.

| | yosys `sat -seq K` | encode once, ask many times |
|---|---|---|
| Cost of the first question | parse, elaborate, unroll, solve | parse once at startup, encode, solve |
| Cost of the second question | all of it again | one more `solve()` call on the solver already holding the formula |
| Asking for a different depth | a separate run | the same formula with the target literal asserted one step earlier |
| Asking "is that the only answer" | not expressible | add a clause forbidding the answer just found, solve again |
| Enumerating everything reachable | not expressible | the same, in a loop, until it returns UNSAT |
| Measured, on this design | about 40 s per depth | **43,111 clauses over 14,498 variables, encoded in 0.09 s, both depths and the uniqueness proof answered in 0.17 s total** |

The uniqueness proof and the five-message catalogue are the two results that do
not exist in the yosys version of this pipeline, and they are not missing
because I did not try. They are missing because "give me another one" is not a
thing a one-shot command can be asked.

#### Is there anything better than Tseitin, and why am I not using it

Yes, for some meanings of better. None of them is better for this.

| alternative | what it buys | why not here |
|---|---|---|
| **Plaisted-Greenbaum encoding** | Writes only one direction of each definition when a gate is used in a single polarity, which cuts the clause count by roughly half | It does not preserve the set of solutions. Both of my interesting results, the uniqueness proof and the message catalogue, work by blocking a solution and re-solving, and that is only sound when the formula's solutions correspond one to one with the circuit's behaviours. Halving the formula and losing the two results it exists to produce is a bad trade |
| **AIG rewriting before encoding**, the ABC approach | Rebuilds the circuit as two-input ANDs and inverters, merges structurally identical nodes, then rewrites small windows into cheaper equivalents before any clause is written | Half of this is adopted and is why the numbers above are what they are: the encoder folds a gate whose inputs are already constant, and shares a gate identical to one already written. That took the puzzle formula from 130,385 variables to **14,498**. The rewriting half needs a full AIG package and, at 728 cells, would cost more to run than it saves |
| **Circuit-SAT solvers that never build CNF** | Search the gate graph directly, and exploit the fact that once an output is settled the rest of its cone does not need justifying | There is no maintained one with a Python interface. Modern CDCL solvers are fast because of watched literals, clause learning and restart policies, all of which a circuit solver has to reimplement to compete |
| **BDDs** | Canonical. Uniqueness and counting come for free instead of costing another query | Size depends brutally on variable order, and a 122-deep unrolling of 92 flops with 121 free inputs is the shape that blows up. This design's counters are adders in disguise, and adders are the textbook BDD explosion |
| **SMT over bit-vectors, which is what z3 is** | Lets a constraint be written in words instead of bits | The netlist is already bits. z3 would bit-blast it straight back down to the same CNF with a translation layer on top. z3 does earn its place in this pipeline, on the other side of it: it is handed the region map and the Star Battle rules, where the problem genuinely is word-level, and it never sees the netlist. That is what makes the two solves independent |
| **Unbounded model checking, IC3/PDR or interpolation** | Proves a property for every depth rather than up to K | It answers a stronger question than I have. The protocol fixes the frame at 121 cells, so the depth is not open. Paying for an unbounded proof to answer a bounded question is the wrong way round |

**OpenROAD is not needed either.** I ran it on the warm-up source early on, to
see how much information the forward flow removes before trying to reverse it.

----

### Complete installation

`RUN.sh` creates `.venv` and installs `requirements.txt` on first run, so on
every platform the install is: get python, get iverilog, run the script. It
takes about **5 seconds** end to end and rebuilds `warmup-solution/` and
`puzzle-solution/` from scratch every time.

#### Ubuntu / Debian
    
    git clone https://github.com/NotCleo/GDS-to-RTL.git
    cd GDS-to-RTL
    sudo apt install iverilog python3-venv python3-tk tree -y
    bash RUN.sh

#### macOS

I do not own a Mac, so this is written from the packages rather than tested. If
something here is wrong, please open an issue.

    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew install python icarus-verilog git tree python-tk
    git clone https://github.com/NotCleo/GDS-to-RTL.git
    cd GDS-to-RTL
    bash RUN.sh

On Apple silicon, `pip` builds `gdstk`, `shapely` and `z3-solver` from arm64
wheels, which exist for all three. `python-tk` is only for the desktop version of
the interactive puzzle; the browser version below needs nothing.

#### Windows

Two routes. I do not run Windows either, so the same caveat applies.

**WSL2, which is the one I would use.** It is the Ubuntu instructions unchanged:

    wsl --install -d Ubuntu

then open the Ubuntu shell and follow the Ubuntu block above.

**Native Windows, without WSL.** Install
[Python 3.10 or newer](https://www.python.org/downloads/windows/) with "Add
python.exe to PATH" ticked, and
[Icarus Verilog for Windows](https://bleyer.org/icarus/), and make sure
`iverilog.exe` is on `PATH`. Then, in PowerShell:

    git clone https://github.com/NotCleo/GDS-to-RTL.git
    cd GDS-to-RTL
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python GDS-to-RTL\gds_to_rtl.py

`RUN.sh` is a bash script, so on native Windows run the Python file directly as
above. Everything in the pipeline is pure Python plus two subprocess calls to
`iverilog` and `vvp`; there is nothing platform-specific in it. If Icarus is not
installed, add `--no-iverilog` and the run skips the two cross-checks and still
produces the answer.

----

### Running it

    bash RUN.sh                   the warm-up, which validates the toolchain, then the puzzle
    bash RUN.sh --only warmup     just the warm-up
    bash RUN.sh --only puzzle     just the puzzle
    bash RUN.sh --no-iverilog     skip the two independent-simulator checks

#### To view the results

    tree puzzle-solution warmup-solution

Every file in those two directories is listed and explained at the end of
section (VIII).

#### Optional, only if you want to look at the waveforms by hand

    mkdir -p ~/surfer_install && cd ~/surfer_install
    wget "https://gitlab.com/api/v4/projects/42073614/jobs/artifacts/main/raw/surfer_linux.zip?job=linux_build" -O surfer_linux.zip
    unzip surfer_linux.zip
    chmod +x surfer
    mkdir -p ~/.local/bin
    mv surfer ~/.local/bin/
    export PATH="$HOME/.local/bin:$PATH"
    surfer puzzle-solution/14_success_inputs.vcd

Open `O[7:0]` and set its format to ASCII. That is easter egg 5: the byte stream
is text.

----

### If you have your own GDS

The extractor is not specific to this puzzle, so it is also packaged on its own,
in [`General-GDS-to-RTL/`](General-GDS-to-RTL/). Point it at any sky130 layout:

    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds

    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds -o out/
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --def mychip.def --golden golden.v
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --lef other.lef --lib other.lib
    python3 General-GDS-to-RTL/gds_to_netlist.py --show-layers

It imports `GDS-to-RTL/gds_to_rtl.py` rather than copying anything out of it, so
the geometry code that runs is the same code proved exact against the warm-up's
golden netlist. The main pipeline is untouched and does not know it exists.

| you get | what is in it |
|---|---|
| `<stem>_01_inventory.txt` | every placement, orientation, label and layer |
| `<stem>_02_netlist.v` | structural Verilog, recovered from polygon overlap alone |
| `<stem>_03_cell_models.v` | simulation models for the cell types used, generated from the Liberty |
| `<stem>_04_structure.txt` | register graph, feedback groups, clock roots, and what each output depends on |
| `<stem>_05_crosscheck.txt` | with `--def` and `--golden`: placement matching and the net-partition comparison |

To be honest about the limit: it recovers a **netlist**, not behavioural RTL.
Synthesis is not reversible. It flattens the hierarchy, deletes every name, and
many different sources compile to the same gates, so nothing gets the `always`
blocks back. The RTL in this repository was written by hand from an
understanding of the gates and then *proved* cycle-equivalent to them. The proof
can be automated. The understanding is the work. What the structure report does
is tell you where to look, and
[`General-GDS-to-RTL/README.md`](General-GDS-to-RTL/README.md) says how to read
it.

For a PDK that is not sky130, `--show-layers` prints the layer table in the
shape that `--layers` accepts, and you pass that PDK's own `--lef` and `--lib`.

----

### Play the puzzle

**In your browser, nothing to install:**
[**notcleo.github.io/GDS-to-RTL/TwoNotTouch-Interactive-Puzzle/**](https://notcleo.github.io/GDS-to-RTL/TwoNotTouch-Interactive-Puzzle/)

One file,
[`TwoNotTouch-Interactive-Puzzle/index.html`](TwoNotTouch-Interactive-Puzzle/index.html),
no scripts loaded from anywhere, works offline if you just open the file.

**One click per cell**, and it steps round: empty, star, dot, empty. Right-click
steps the other way, so a dot is one click too. Nothing waits to see whether a
second click is coming, so the board changes the instant you click it, and the
solution goes in in 22 clicks.

The line under the board is the verdict the **real chip** returns for the grid
you have placed, and it reproduces all five of the messages the output ROM holds,
including `TWO NOT TOUCH`. Solve it and the tab closes itself.

The five verdicts on that page were checked against the five grids the solver
pulled out of the netlist in stage P10, and they agree on all five.

**On the desktop, if you would rather:**
[`TwoNotTouch-Interactive-Puzzle/play.py`](TwoNotTouch-Interactive-Puzzle/play.py),
which needs `python3-tk` and nothing else.

#### Note

The pipeline itself is entirely headless and needs neither of them.

The captured output of a full run is in [`RUN.log`](RUN.log), the pipeline's own
stage-by-stage log is in [`GDS-to-RTL/run.log`](GDS-to-RTL/run.log), and every stage
is described with its numbers in [`GDS-to-RTL/summary.md`](GDS-to-RTL/summary.md).

----

## (VII) Layout

```
├── CHALLENGE.md         # The main challenge 
├── RUN.log              # The complete run log
├── RUN.sh               # Main Orchestrating bash
├── README.md            # This file
├── requirements.txt     # Python dependencies 
├── GDS-to-RTL           # Reverse Recovery scripts
├── General-GDS-to-RTL   # The same extractor, for any sky130 GDS you have
├── puzzle               # Provided Puzzle files
├── warmup               # Provided warmup files
├── puzzle-solution      # Puzzle solution files
├── warmup-solution      # warmup solution files
├── TwoNotTouch-Interactive-Puzzle    # Interactive Two Not Touch Puzzle, browser and desktop (TRY THIS!)
├── Easter-Eggs          # List of easter eggs
├── Images               # Images of waveforms, layouts, schematics
├── pdk                  # SKY130 PDK
└── Personal-Notes       # Ignore this
```

----

## (VIII) Full Picture 

This is the whole thing in the order it happened: the question I had at each
point, what I did about it, and what came back. Every number in it is printed by
`GDS-to-RTL/gds_to_rtl.py` on a fresh run, and the run that produced these
numbers is in [`RUN.log`](RUN.log).

| | |
|---|---|
| The whole flow | one file, [`GDS-to-RTL/gds_to_rtl.py`](GDS-to-RTL/gds_to_rtl.py) |
| Runtime | about 5 seconds |
| Stage by stage | [`GDS-to-RTL/summary.md`](GDS-to-RTL/summary.md) |
| Full terminal log | [`GDS-to-RTL/run.log`](GDS-to-RTL/run.log) |

----

### 1. What is actually inside a GDS file

I started with `puzzle/puzzle.gds`, and the first thing I needed to know was what
kind of file I was holding.

A GDS is a geometry file, and that is all it is. It stores polygons, each tagged
with a layer number and a datatype, plus a hierarchy of cells that can be placed
at a position with a rotation and an optional mirror. There is no concept in the
format of a wire, a gate, a pin, or a connection. Two pieces of metal are
connected if and only if they physically overlap, and the file never says so
anywhere. That has to be worked out from the coordinates.

| what a GDS keeps | what it does not have |
|---|---|
| polygons, with a layer and a datatype | any notion of a net |
| cell definitions, and placements of them | any notion of a pin, beyond a text label someone chose to leave |
| text labels, if the flow did not strip them | signal names, module boundaries, hierarchy above the cell |
| a hierarchy of references, with rotation and mirror | anything at all about intent |

One thing survived that mattered enormously: **the standard cells were still
named.** `sky130_fd_sc_hd__nand3_2` tells me exactly what that cell does, because
the PDK that defines it is public. What the flow stripped is everything above
the cell: which instance is which, what the nets were called, and how the design
was organised.

My first instinct was to open it in a viewer and stare. I tried the Tiny Tapeout
online viewer, then switched to GDS3D because I wanted to magnify specific
regions and the browser viewer fought me. Staring taught me almost nothing about
the circuit. It did turn up one thing, which is section 7 below.

----

### 2. Deciding what to build first, and against what

The challenge asks for a netlist extractor, so at some point I have to write one.
The problem I could see coming is this: suppose I write it, point it at
`puzzle.gds`, and it produces a netlist. **How would I know that netlist is
right?** A netlist can parse cleanly, have every pin connected, have no
duplicate drivers, and still describe a different circuit, because one missed
overlap splits one net into two and nothing anywhere reports an error.

The puzzle ships with a warm-up, and the warm-up ships its answer key:

| `warmup/` contains | which is |
|---|---|
| `00_source.v` | the Verilog someone wrote |
| `01_netlist.v` | the gate netlist synthesis produced from it |
| `03_post_place_and_route.def` | where every one of those gates was placed |
| `04_final.gds` | the geometry, which is the only thing the puzzle gives me for the real chip |

So the order of work chose itself.

| stage | what it buys me |
|---|---|
| Build the extractor against the warm-up | I can compare my output to the golden netlist exactly, net by net, and to the DEF placement by placement |
| Only then point the same code at the puzzle | Any disagreement after that is about the puzzle, not about my tools |

Nothing in the pipeline reads a warm-up answer file when it processes the puzzle.
The warm-up is the test bench for the extractor, and then it is finished with.

----

### 3. Inventory, before any connectivity work

Before trying to work out what is connected to what, I wanted a plain bill of
materials: which cells are placed, where, in what orientation, and every text
label that survived. No interpretation, just counting. This is stage **W1** for
the warm-up and **P1** for the puzzle, and it writes
`01_gds_inventory.txt` in each solution directory.

| | puzzle | warm-up |
|---|---|---|
| structures in the file | 81 | 27 |
| bounding box | (0, -52.72) .. (200, 300) um | (0, 0) .. (100, 100) um |
| total placements | 9,875 | 1,099 |
| logic cells | **728** | **79** |
| distinct logic cell types | 66 | 16 |
| flip-flops | **92** | 16 |
| vias | 8,221 | 869 |
| well taps and decoupling caps | 880 | 151 |
| antenna diodes | 10 | 0 |
| structures that are not standard cells | **36** | 0 |
| pin labels inside cell definitions | 876 | 186 |
| top-level text labels | 17 | 10 |

The warm-up is 79 logic cells: two shift registers, an adder, a comparator and
three clock buffers. Small enough to read by hand, which is the point of it.

The 17 top-level labels on the puzzle are the ports, and they are the last real
names left anywhere in the file:

```
'I'        on layer 70/5 at (  0.30,  79.22)
'clk'      on layer 70/5 at (  0.30, 238.34)
'rst_n'    on layer 70/5 at (  0.30, 185.30)
'enable'   on layer 70/5 at (  0.30, 132.26)
'O[0]'     on layer 70/5 at (199.70, 204.34)   ... through O[7]
'success'  on layer 70/5 at (199.70, 285.94)
```

Inputs down the left edge, outputs down the right, exactly as the hint image in
section (I) draws them. Two rows of that table are odd and both turn out to
matter, which is section 9.

----

### 4. Turning polygons into a netlist

Now the real question: given a pile of polygons, how do I work out what is
connected to what? It sounds close to impossible, and the algorithm turns out to
be four steps.

| step | what happens |
|---|---|
| 1 | For each conducting layer, take every polygon and group the ones that overlap. Each group is one contiguous piece of conductor. |
| 2 | Walk the via layers. A via cut that touches conductor X on the layer below and conductor Y on the layer above means X and Y are the same electrical node. |
| 3 | Union-find over all of those relationships. Every resulting connected component is a net. |
| 4 | For each placed cell, look up where its pins are, find which net covers each pin, and emit Verilog. |

Step 1 is a grouping problem over shapes. Step 2 needs a spatial index or it is
quadratic and unusable, so every lookup goes through an R-tree, which shapely
provides as `STRtree`.

> **Note on shapely.** 2.0 changed `STRtree.query` to take a `predicate`
> argument and to return integer indices rather than geometries. On shapely 1.8
> that call signature does not exist, and the code silently builds a different
> netlist rather than failing. **2.0 is a hard floor**, and `requirements.txt`
> pins it.

This is stage **W2** and **P2**, and it writes `02_extracted_netlist.v`.

----

### 5. Three bugs, each of which produced a clean netlist of the wrong circuit

None of these crashed. All three gave me a netlist that parsed, had no dangling
pins, had exactly one driver per net, and described a circuit that is not the one
on the die. Every one of them was caught by the warm-up comparison and by
nothing else, which is the entire argument for building against the warm-up
first.

| bug | what I did wrong | why it broke silently | the fix |
|---|---|---|---|
| **Pin geometry** | Used the GDS text labels to decide which polygon is which pin | A label tags exactly one polygon. A real pin is often several polygons in different places in the cell, and the router may land on any of them. Pins went missing, and nets that should have been joined stayed separate | Read the pin rectangles out of the PDK's LEF. `PIN ... PORT ... RECT` is the authoritative geometry and lists every rectangle belonging to each pin |
| **Antenna diodes** | Treated `diode_2` as an inert protection device and skipped it | The router uses a diode as a convenient place to jump layers and lands on it twice. Skipping it tears one real net into two halves that never reconnect | Treat it as an electrical bridge: its two connections are the same net |
| **Cell outlines** | Matched my placements to the DEF using each cell's geometric bounding box | The nwell implant overhangs the cell outline, so every box was consistently too big and every lower-left corner was wrong by the same small amount. **0 of 79** placements matched | sky130 draws the real abutment box on its own layer, **81/4**. Reading that instead gave **79 of 79** immediately |

The pin one deserves a number, because it is not a rare edge case. Among the 66
cell types the puzzle uses, 172 of 285 signal pins are a single rectangle, so the
naive approach works most of the time. The ones it does not work for are the ones
that matter: the output pin of `clkbuf_16` is **20 separate rectangles**, and
that cell is the root of the entire clock tree.

| cell | pin | rectangles in LEF |
|---|---|---|
| `clkbuf_16` | `X` | **20** |
| `clkbuf_8` | `X` | 11 |
| `a2111oi_2` | `Y` | 11 |
| `dfrtp_2` | `RESET_B` | 9 |

The diode one is the sort of thing that only surfaces if you have ground truth.
The netlist without diode bridging had the right cell count, no dangling pins,
and no visible defect anywhere. It just described a different circuit.

----

### 6. Proving the extractor exact

With the warm-up I can do better than "it looks fine". This is stage **W3** and
**W5**, and it writes `04_golden_crosscheck.txt` and `05_equivalence.txt`.

| check | what it proves | result |
|---|---|---|
| Every net has exactly one driver | No shorts, no floating outputs, no gate driving into another gate's output | 84 nets, **0 violations** |
| Every GDS placement matches a DEF component | Same cell, same corner, same orientation | **79 of 79** |
| Net partition matches the golden netlist | The two are literally the same circuit | **84 exact matches, 0 mismatches** |
| Simulate both netlists side by side, 3,000 random cycles, then 200 byte pairs | They behave identically, and `S` really is `A+B==496` | **0 mismatches**, 200 of 200 |

The third row is the one that actually settles it, and it is worth saying why it
works. **Two netlists are the same circuit exactly when they cut the same set of
pins into the same groups, with the same ports attached to the same groups.**
That is a statement about set partitions, and names play no part in it. So I can
prove my extraction exact while every instance in it is still called `u17` and
every net `net_412`. The DEF match is not part of the proof; it is only there to
put the names back afterwards.

At this point the extractor is finished and validated, and the warm-up has one
more job to do before I leave it.
----

### 7. What the layout viewer turned up: easter egg 1

Back when I was still turning layers off one at a time in GDS3D, one thing did
come out of it.

On met2 there is a pale ring low on the die that does not look like anything else
in the file. Routing on a metal layer is long power straps and short jogs between
vias, and this was neither: 1,366 sub-micron polygons crammed into a 17.10 x
17.10 um block, sitting over a piece of die with nothing under it, connected to
nothing at all. It is the Jane Street logo, drawn in real mask geometry. It is in
the warm-up GDS too, at a different corner. Details and the rasterised version:
[`Easter-Eggs/01_easter_egg.txt`](Easter-Eggs/01_easter_egg.txt).

That is everything the viewer produced. Everything after this is computed.

----

### 8. Solving the warm-up without reading its answer, and why a SAT solver

The warm-up has one job left. I have proved my netlist is the same circuit as the
golden one, but I have not yet worked out what the circuit **does** from the
gates alone. `warmup/00_source.v` is sitting right there with the answer in it.
The puzzle will not have that file, so this is the one chance I get to try the
technique on a problem whose answer I can check afterwards.

The question I want to ask is: **is there an input sequence that drives `S` high,
and what is the shortest one?**

#### Why a solver, and not something simpler

There are three ways to answer a question of that shape.

| approach | how it works | why it does or does not fit |
|---|---|---|
| **Exhaustive search** | Simulate every input sequence up to length K and look for one that works | Fine for the warm-up: `A` and `B` are eight bits each, so 65,536 pairs. Useless for the puzzle: 121 free bits is 2^121 sequences, which is about 2.7 x 10^36. Even at a billion grids a second that is 10^20 years |
| **Invert it algebraically** | If the state update were linear over GF(2), the circuit is an LFSR or a CRC and Gaussian elimination inverts it in milliseconds | Worth testing, and the pipeline does test it rather than assume. It is not linear, and the test is in section 18 |
| **Ask a solver for a witness** | State the circuit and the goal as constraints and let a search engine that is good at constraints find an assignment, or prove none exists | This is the one that scales, and the "or prove none exists" half is what gives me a minimum depth rather than a guess |

The third one also answers a question the other two cannot: **UNSAT is a proof.**
If the solver says no input of 121 edges works, that is not "I did not find one",
it is "there is not one", and that is what makes the protocol claim in section 18
a fact rather than an observation.

#### What kind of SAT this is

Not plain combinational SAT. The circuit has 16 flip-flops in the warm-up and 92
in the puzzle, so what it does depends on what it has already been shown. The
technique is **bounded model checking**:

| | |
|---|---|
| Take the circuit | a netlist of gates and flops |
| Unroll it over K clock edges | make K copies of the combinational logic, and wire copy `t`'s flop outputs into copy `t+1`'s inputs |
| Encode every gate in every copy | Tseitin, as described in section (VI) |
| Add the goal as one clause | `S = 1` at step K |
| Ask | SAT means a K-edge input sequence exists, and the solver hands it over. UNSAT means one provably does not |
| Then sweep K upward | the smallest K that is SAT is the minimum depth |

Two details make this cheap rather than expensive. The formula for a given K is a
**prefix** of the formula for K+1, so the pipeline encodes once at the largest
depth it will need and asks the shorter questions by asserting the goal literal
one step earlier. And the encoder folds any gate whose inputs are already
constant, which after reset is most of the design for the first several steps.

#### Which solver

`python-sat` bundles several CDCL solvers behind one interface. Rather than pick
one on reputation I timed all of them on this design's own two workloads, the
depth question and the fourteen incremental enumeration queries of section 21,
and took the fastest total. Same formula, same machine, best of three:

| back end | depth question | enumeration | total |
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

The depth question is small enough that every one of them is inside a rounding
error of the others. The enumeration is where they separate, because it is
fourteen incremental queries against a solver that has to keep and reuse what it
learned between them, and that is the part CDCL implementations differ on.
CaDiCaL 3.0 wins, so that is what `SAT_BACKEND` names in the pipeline, and it is
the only line that has to change to swap it.

#### What came back

Unroll the extracted warm-up gates, encode, ask, sweep K.

```
one unrolling to 11 edges: 362 variables, 1012 clauses

K =  6 edges   UNSAT
K =  7 edges   UNSAT
K =  8 edges   SAT
A = 11111000 = 248
B = 11111000 = 248
A + B = 496
```

Eight edges, because the warm-up shifts in eight bits. No gate was traced by
hand, and `00_source.v` was never opened. Output:
[`warmup-solution/06_sat_solve.txt`](warmup-solution/06_sat_solve.txt).

#### Easter egg 7, which is the constant it came back with

The warm-up raises `success` when `A + B == 496`, and 496 is not arbitrary. It is
the **third perfect number**, equal to the sum of its own proper divisors:

```
496 = 1 + 2 + 4 + 8 + 16 + 31 + 62 + 124 + 248
```

It is also `2^4 x (2^5 - 1) = 16 x 31`, which is Euclid's form for a perfect
number, `2^(p-1) x (2^p - 1)` with `p = 5`. And it is a well chosen constant for
an eight-bit adder: `A + B` ranges over 0 to 510, and `A + B = 496` has exactly
**15** solutions, `A` from 241 to 255, out of 65,536 input pairs.

The solver returned `A = B = 248`, which is the largest proper divisor of 496 and
the middle of those 15 solutions. Any of the 15 would have been correct, and an
earlier run of this pipeline returned 242 and 254, so the specific pair is the
solver's choice and not a property of the circuit. That is worth stating plainly
because it is the one number on this page that is allowed to move between runs.

----

### 9. Back to the puzzle: the inventory oddities, and easter egg 2

Same extractor, no changes, pointed at `puzzle.gds`. Three rows of the inventory
table in section 3 do not belong in a normal standard-cell design, and all three
point at the same place.

**The bounding box came back as `(0.00, -52.72) .. (200.00, 300.00)`.** A
negative y. The placement rows of a standard cell design start at y = 0, so
something is drawn 52.72 um below where the chip is.

**The placement histogram has a bucket for anything that is neither a standard
cell nor a via, and on the puzzle it was not empty:**

```
21 x INTERNAL_3
15 x INTERNAL_7
```

36 placements of two structures with no pins, no transistors, and names no PDK
uses.

**The layer histogram, checked against the sky130 layer map, flagged one layer
the map does not know: 200/0**, carrying two polygons, one inside each of those
two structures. Diffing the puzzle's layer set against the warm-up's narrows it
further, since both went through the same flow. Three layers appear in the puzzle
and not the warm-up, and two are boring: 66/15 and 81/23 live only inside
standard cells, so they are present because the puzzle instantiates `conb_1` and
`diode_2` and the warm-up has neither. Only 200/0 is drawn outside every cell, so
only 200/0 was added by hand.

36 bars, two widths, 1.38 um and 4.14 um, exactly 1:3, all at y = -52.72,
spanning x = 1.33 to 198.67. Dividing the gaps by the narrow width, every gap is
1, 3 or 7:

```
widths : . - - . . . - . . - . - . . - . . - - - . - - . . . - . . . - . - . . -
gaps   : 1 1 1 3 3 1 1 7 1 3 1 1 3 3 1 3 1 3 1 7 1 3 1 1 7 1 3 1 1 3 3 1 1 3 1
```

Short mark, long mark at 3, gap 1 inside a letter, 3 between letters, 7 between
words. That is International Morse timing exactly, and it decodes with no
ambiguity to:

```
PER ARENAM AD ASTRA
```

Latin, roughly "through the sand, to the stars", a play on *per aspera ad
astra*. Full decode:
[`Easter-Eggs/02_easter_egg.txt`](Easter-Eggs/02_easter_egg.txt).

----

### 10. The layer map, the via census, and the puzzle netlist

The four-step algorithm in section 4 needs one thing before it can run on the
puzzle: which GDS layers are conductors, which are cuts, and which are neither.
sky130 answers that.

| layer | GDS | what it is | how the extractor uses it |
|---|---|---|---|
| li1 | 67/20 | local interconnect, inside and between cells | conductor |
| met1 | 68/20 | first routing metal | conductor |
| met2 | 69/20 | second routing metal | conductor |
| met3 | 70/20 | third routing metal, also carries the port labels on 70/5 | conductor |
| met4 | 71/20 | fourth routing metal, power straps | conductor |
| met5 | 72/20 | fifth routing metal, power straps | conductor |
| mcon | 67/44 | cut, li1 to met1 | bridge |
| via | 68/44 | cut, met1 to met2 | bridge |
| via2 | 69/44 | cut, met2 to met3 | bridge |
| via3 | 70/44 | cut, met3 to met4 | bridge |
| via4 | 71/44 | cut, met4 to met5 | bridge |
| nwell, diff, poly, licon1, nsdm, psdm, npc, hvtp | 64, 65, 66, 93, 94, 95, 78 | transistors and implants | ignored, they carry no inter-cell signal |
| areaid.standardc | 81/4 | the real cell abutment box | used to match placements to the DEF |

Grouping the overlapping shapes per conductor layer on the puzzle:

| conductor | shapes in | conductors out |
|---|---|---|
| li1 | 10,819 | 5,472 |
| met1 | 12,606 | 3,001 |
| met2 | 8,517 | 2,060 |
| met3 | 2,560 | 811 |
| met4 | 867 | 45 |
| met5 | 162 | 18 |

**Checking the coordinate transforms.** This check needs no golden file, so
unlike section 6 it works on the puzzle too. Every via cut has to land on metal
on **both** sides. If a rotation or a mirror were applied wrongly, vias would sit
with metal on one side only:

```
cut mcon   li1  -> met1 : 17188/17188 bridged
cut via    met1 -> met2 :  3779/3779  bridged
cut via2   met2 -> met3 :   951/951   bridged
cut via3   met3 -> met4 :   687/687   bridged
cut via4   met4 -> met5 :   108/108   bridged
```

**22,713 of 22,713** cuts bridged, none floating. The design that came out:

| | |
|---|---|
| logic cells | 728, in 66 types |
| nets | **738** |
| flip-flops | 92, being 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2` |
| nets with a driver count other than one | **0** |
| nets with no driver at all | **0** |
| combinational loops | **0** |
| clock roots | one, `clk` |

Zero shorts, zero floating outputs and zero undriven nets on both designs. That
last row matters because a single unrecovered connection splits one net into two,
and the circuit becomes a different circuit with no error reported anywhere.

The result is a plain structural Verilog netlist,
[`puzzle-solution/02_extracted_netlist.v`](puzzle-solution/02_extracted_netlist.v):

```verilog
// Recovered from puzzle/puzzle.gds by geometry alone.
// No netlist, DEF or source file was read to produce this.
// 728 logic cells, 738 nets, 0 nets with a driver count other than one.
module puzzle_extracted (I, clk, enable, rst_n, success, O);
  input  I;
  ...
  sky130_fd_sc_hd__xor2_2  u12_xor2_2  (.A(net_268), .B(net_256), .X(net_260));
  sky130_fd_sc_hd__a21oi_2 u13_a21oi_2 (.A1(net_244), .A2(net_245), .B1(net_240), .Y(net_246));
  sky130_fd_sc_hd__nand2_2 u14_nand2_2 (.A(net_200), .B(net_649), .Y(net_255));
  sky130_fd_sc_hd__a22o_2  u15_a22o_2  (.A1(net_051), .A2(net_653), .B1(net_272), .B2(net_296), .X(net_276));
  ...
  sky130_fd_sc_hd__and3_2  u23_and3_2  (.A(net_139), .B(net_140), .C(net_135), .X(O[0]));
endmodule
```

728 instances and 738 nets, with no meaningful names left in it. Which is exactly
as far as geometry can take anyone.

----

### 11. Cell semantics, and what the PDK gets wrong

A netlist of cell names is useless without knowing what the cells do. I take that
from the sky130 Liberty file, which is the same file the synthesiser read when it
built this design in the first place. This is stage **W4** and **P3**, and it
writes `03_cell_models.v`.

For combinational cells, each output pin carries a boolean `function`:

```
cell ("sky130_fd_sc_hd__xor2_2") {
    pin ("X") { direction : "output";  function : "(A&!B) | (!A&B)"; }
}
```

For sequential cells, an `ff` group names the state pair, its clock, its next
state, and its level-sensitive clear or preset:

```
cell ("sky130_fd_sc_hd__dfstp_2") {
    ff ("IQ","IQ_N") { clocked_on : "CLK";  next_state : "D";  preset : "!SET_B"; }
    pin ("Q") { direction : "output";  function : "IQ"; }
}
```

That is enough to derive every cell, so **no truth table is written by hand
anywhere in this repository**, and the same parsed functions are used by the
simulator and by the SAT encoder, which keeps the simulated circuit and the
solved circuit literally the same object.

It also settles the reset polarity, and that one is load-bearing: `dfrtp` has a
`clear` and resets **low**, `dfstp` has a `preset` and resets **high**. This
design has four `dfstp_2`, so any tool option that zeroes every flop at reset
turns it into a circuit with no solution at all.

Four things in the PDK are worth flagging, because each one has a way of being
read that parses cleanly and is wrong.

| what | what it looks like | what goes wrong if you miss it |
|---|---|---|
| **The output pin name depends on inversion** | Among the 66 cell types here, 36 call their output `X`, **26 call it `Y`**, three flops call it `Q`, and `conb_1` calls its two outputs `HI` and `LO` | The rule is that an inverting cell's output is `Y`. A reader that looks for `X` silently drops every NAND, NOR, inverter and AOI in the design, which is 26 of the 66 types here. The pipeline takes the output set from Liberty's `direction : "output"` rather than from a list of names it hoped was complete |
| **One pin, two layers** | `dfrtp_2.RESET_B`, `dfstp_2.SET_B` and `xor2_2.B` each have rectangles on **both li1 and met1** | If you index pin geometry per layer and only look on the layer you expected, the router lands on the other one and the pin binds to nothing. The extractor looks up every rectangle on whatever layer it was declared on |
| **`conb_1` has no inputs at all** | Its entire pin list is two outputs, `HI` with `function : "1"` and `LO` with `function : "0"` | It is how the synthesiser ties a net to a constant. Code that assumes every cell has at least one input, or that every output is a function of inputs, falls over on it. It is also one of the two cells the warm-up does not contain, which is how it turned up in the layer diff in section 9 |
| **The file uses three operator dialects** | `function` is written with `&` and `\|`. `state_function` on the clock-gate cells uses `*` for AND. `power_down_function` uses `+` for OR and refers to the power rails by name | An expression parser that is pointed at every attribute ending in `_function`, which is the obvious thing to write, will read `power_down_function` in the wrong dialect and then treat `VPWR` and `VGND` as ordinary signals. The output of the cell becomes a function of the power rails and the netlist becomes nonsense. The parser here reads `function`, `next_state`, `clear` and `preset`, and nothing else |

A secondary one, less interesting but worth knowing: the human-readable equations
in the comment headers of the PDK's own Verilog models do not always agree with
the cell they sit above. The machine-generated Liberty `function` strings are
consistent, so those are what I parse, and I never read the comments.

Generated models:
[`puzzle-solution/03_cell_models.v`](puzzle-solution/03_cell_models.v).
----

### 12. The sample waveform: easter eggs 3, 4, 5 and 6

I now had a netlist and no description of its behaviour, so I went back to the
one file I had been ignoring: `puzzle/example_inputs.vcd`.

I opened it in a text editor, which I had not done, and the first nine lines
contain two easter eggs.

**Easter egg 3**, the `$version` field:

```
Leave no stone unturned! But for this file, consider looking at it in a
waveform viewer instead.
```

No simulator writes that. iverilog writes "Icarus Verilog", so this line was
added by hand.

**Easter egg 4**, two lines above it, the `$date` field:

```
Sat Dec 31 23:59:60 2016
```

A second numbered 60. Most date parsers reject that, because most date libraries
assume a minute has 60 seconds numbered 0 to 59. It is a leap second, and a real
one: 2016-12-31 23:59:60 UTC is the most recent leap second inserted, so that
minute had 61 seconds. It was a Saturday.

Then I opened the same file in Surfer, and got nothing useful. `success` is low
for the whole trace. `O[7:0]` sits at zero, changes nine times in a burst near
the end, and goes back to zero. As hex that burst is
`54 52 59 20 41 47 41 49 4e`, which says nothing as a number. I read it in
decimal, hex and binary, got nothing, and moved on.

**Easter egg 5** is what fixed that, and it is not in any file. Going back to
re-read the puzzle statement, the blog post links in passing to [another Jane
Street post about using ASCII waveforms to test hardware
designs](https://blog.janestreet.com/using-ascii-waveforms-to-test-hardware-designs/).
Read as a curiosity it is a curiosity. Read as an instruction it is what makes
the output side readable. I do not normally display a bus as ASCII. One right
click later, those same nine bytes read:

```
T R Y   A G A I N
```

So the chip does not return a status code, it returns text. The block the hint
image says to ignore is a ROM of English sentences, and the sample waveform is a
recording of a wrong grid being rejected.

That pointed the same question at the input side, and the input side is **easter
egg 6**. Two counts point at it before any decoding: both frames of the sample
contain exactly **38** ones, identical rather than similar, and in both frames
columns 7 through 10 are empty in **every** row, a perfectly rectangular block of
44 dead cells.

Eleven rows, seven usable columns each. Standard ASCII needs seven bits. So group
the bits in sevens, one row per character, least significant bit first:

```
. . 1 . 1 . 1 . . . .   0010101 ->  84 -> 'T'
. . . 1 . 1 1 . . . .   0001011 -> 104 -> 'h'
1 . 1 . . 1 1 . . . .   1010011 -> 101 -> 'e'
```

Frame 0 gives `The night s`, frame 1 gives `ky awaits  `.

```
The night sky awaits
```

The file I had written off on day one carries the theme in its inputs. Full
decode, all 22 rows:
[`Easter-Eggs/06_easter_egg.txt`](Easter-Eggs/06_easter_egg.txt).

#### The interface, measured rather than assumed

The same file also settles the protocol, which up to here I had been guessing at.
Counting rising edges of `clk` in the recorded trace:

| edges | what happens |
|---|---|
| 1 to 3 | `rst_n` = 0, reset |
| 4 | `rst_n` = 1 |
| 5 to 125 | `enable` = 1, **121 bits shifted in on `I`** |
| 126 | `enable` = 0, and `O` becomes `'T'` on the same edge: the message starts immediately |
| 126 to 134 | `T R Y space A G A I N` |
| 135 | `O` back to 0 |
| 157 to 159 | `rst_n` = 0 again, second frame |
| 161 to 281 | another 121 bits |
| 282 | `'T'` again |

121 = 11 x 11. So it is a fixed 121-cell frame, not a free-running stream, and
the verdict begins on the edge immediately after the frame ends. Both of those
get proved from the gates later, in section 18.

----

### 13. Checking the netlist against the recorded silicon

The sample waveform is a recording of the real chip: known inputs, known outputs.
Which makes it something better than an easter egg hunt. It is a test my
extracted netlist has to pass, and it is a test that could not have been fitted
to, because the trace existed before my extractor did.

Stage **P4** replays the recorded inputs into the extracted netlist and compares
every output at every rising edge:

```
312 rising edges replayed, 624 outputs compared, 0 mismatches
```

A netlist built from polygon coordinates alone reproduces the recorded silicon at
every edge. From here on, wherever the netlist and a hypothesis disagree, the
netlist is taken as correct. If P4 ever reports a mismatch the pipeline stops,
because every later stage would be interpreting a circuit that does not exist.
Output:
[`puzzle-solution/04_vcd_replay.txt`](puzzle-solution/04_vcd_replay.txt).

The same stage also checks the clock tree, which would otherwise be an
assumption. There are 32 clock buffers in three levels, one `clkbuf_16` feeding
16 `clkbuf_8` feeding 15 `clkbuf_4`, and every one of the 92 flip-flop clock pins
traces back through them to the single primary input `clk`. There is no gated
clock anywhere in this design, so the whole thing can be reasoned about one
rising edge at a time, which every later stage relies on.

----

### 14. Register-level structure, and why the flip-flops are the thing to look at

I now had 728 anonymous cells that I knew were correct and did not understand at
all. Reading them gate by gate was not going to work, and I want to be specific
about why rather than just say it is too many.

The problem is that combinational logic does not survive synthesis in any
recognisable form. The optimiser is free to rewrite any acyclic block of gates
into any other block with the same truth table, and it does, so the shape you are
looking at is the shape the optimiser preferred, not the shape anyone wrote.
Net `net_412` corresponds to nothing in anybody's source file.

**Flip-flops are different.** A flop is a physical cell with a name in the
library, it holds a value across a clock edge, and no optimiser can make it not
do that. So the flops are real objects, and the interesting question is not what
each gate does but **which flops feed which**.

#### The graph

Build a directed graph with one node per flip-flop, and an edge from `a` to `b`
when `a`'s output reaches `b`'s data, clear or preset input **through
combinational logic only**, not through some third flop. Constructing it means
walking backwards from each flop's `D` through the gate cone and stopping the
moment you hit a flop output or a primary input.

92 nodes. Cheap to build, and it throws away exactly the part that was not
meaningful.

#### Why cycles are the thing to look for

A cycle in that graph means a flop's next value depends on its own current value.
That is precisely the difference between **state that accumulates** and **state
that merely delays**. A shift register is a chain, so it is a path, and it has no
cycle. A counter has to look at its own value to know what to count to next, so
it has a cycle. Same for accumulators, and same for any state machine whose next
state depends on its current state.

The reason this is worth building a graph for, rather than being an aesthetic
preference, is that **a synthesiser cannot remove a cycle**. It can retime a
loop, re-encode it, or merge flops inside it, but it cannot turn it into a
directed acyclic graph, because a DAG has a bounded memory of the past and a loop
does not. Feedback is a behavioural property, not a syntactic one. So the cycles
in the register graph are the one structural feature of the original design that
is guaranteed to be still there after everything else was optimised away.

#### Why Tarjan

What I want is not "is there a cycle" but "what are the maximal groups of flops
that can all reach each other". That is the definition of a **strongly connected
component**, and Tarjan's algorithm computes all of them in a single depth-first
traversal, in time linear in nodes plus edges.

| alternative | why not |
|---|---|
| Test every pair for mutual reachability | 92 nodes is small enough that this would finish, but it is quadratic in the number of nodes for no benefit |
| Kosaraju's algorithm | Correct and simpler to explain, but it needs two full passes and the reverse graph |
| Just look for self-loops | Finds a flop that feeds itself and nothing else. Misses every counter of two bits or more, which is 26 of the 26 groups here |

Tarjan gives the answer in one pass, and the implementation is 30 lines. This is
stage **P5**, and it writes
[`puzzle-solution/05_register_structure.txt`](puzzle-solution/05_register_structure.txt).

#### What came back

| | |
|---|---|
| flip-flops | 92 |
| feedback groups of size 2 or more | 26 |
| of size 2 | **23** |
| of size 9 | 1, external inputs `enable` and `rst_n` |
| of size 8 | 1, external inputs `I`, `enable` and `rst_n` |
| of size 4 | 1, no external inputs at all |

Reading it one row at a time:

**Twenty-three groups of exactly two flops.** Two bits of state that update
together and look at each other. That is a two-bit counter, twenty-three times
over, and it is very unlikely to be twenty-three of anything else. Simulating
them later confirms it, and confirms something a little unusual: they saturate at
3 rather than wrapping, so each one counts up to two and then records that it
overflowed instead of rolling back to zero. That is a deliberate design choice
and it is why there is no magnitude comparator anywhere on this die. Counting to
exactly two and comparing for equality is cheaper than counting properly and
comparing for greater-than.

**One group of nine, whose external inputs are `enable` and `rst_n` but not `I`.**
Nine bits of feedback state that never look at the data. Something that tracks
where you are in the frame rather than what is in it.

**One group of eight, whose external inputs include `I`.** Eight bits driven by
the data. A byte-wide accumulator of some sort.

**One group of four with no external inputs whatsoever.** Four flops that talk
only to each other and to nothing outside. Something that free-runs once started.
These are also the four `dfxtp_2`, the only flops in the design with no reset at
all, which is why section 22 has to prove their power-up state does not matter.

#### The one thing worth decompiling

`success` is a single flip-flop, `u28_dfrtp_2`, and it does not appear in the
list above because its feedback group has size one: it feeds only itself. Its set
condition is a wide AND tree, and unlike the counters that tree is worth
expanding through the combinational logic and printing, stopping at flop outputs
and ports:

```
D = (((!u390.Q & (!u419.Q & (((u451.Q & u449.Q) & u460.Q) & ((!u459.Q & !u461.Q)
  & !(((u453.Q | u447.Q) | u454.Q)))))) & (((!u26.Q & u350.Q) & ((((((
  !u622.Q & u600.Q) & (u596.Q & !u614.Q)) & (!u232.Q & u601.Q)) & (!u625.Q
  & u597.Q)) & ((((u647.Q & !u651.Q) & (!u661.Q & u595.Q)) & (!u603.Q &
  u634.Q)) & (u635.Q & !u602.Q))) & (((!u215.Q & u197.Q) & (u233.Q &
  !u231.Q)) & (!u226.Q & u198.Q)))) & ((((((!u106.Q & u178.Q) & (u107.Q &
  !u179.Q)) & (!u121.Q & u153.Q)) & (!u108.Q & u180.Q)) & ((((u190.Q &
  !u118.Q) & (!u194.Q & u209.Q)) & (!u126.Q & u188.Q)) & (u117.Q & !u189.Q
  ))) & (((!u122.Q & u141.Q) & (u142.Q & !u124.Q)) & (!u123.Q & u143.Q))))
  ) | (u28.Q & (u26.Q | !u350.Q)))
```

Read for structure rather than detail, there is one group of **eleven**
near-identical two-bit comparisons, `(!u622.Q & u600.Q)`, `(u596.Q & !u614.Q)`
and so on, then a second group of **eleven** more of exactly the same form, then
one separate eight-flop comparison against a fixed pattern,
`u451 & u449 & u460 & !u459 & !u461 & !(u453 | u447 | u454)`. And the whole thing
ORs with `u28.Q`, which is the self-loop: once high, `success` stays high.

Eleven of one thing, eleven of another, one eight-bit thing, everything compared
against two.

The same treatment applied to any of the 23 counter pairs expands into megabytes
of repeated subexpression, because a counter's cone reaches the same nets by many
different paths and a printed tree has no way to share them. So decompiling works
for the control logic and fails completely for the counters, which is why the
counters get probed instead, in section 17.

----

### 15. Where the counters are on the die: easter egg 8

The blog post says the circuit is physically arranged to hint at what it does, so
look closely at the layout. Looking at the layout directly gives nothing: 9,875
placements, none of them labelled. But my extractor numbers instances `uNNN` by
their position in the GDS reference list, so **once the counters were identified
by name, `uNNN` back to (x, y) is a lookup rather than a search.**

That is the trick, and it is why this egg comes now and not in section 7. The
layout does hint at the function, but only to someone who already has the
netlist.

| what | how many | where |
|---|---|---|
| identical 2-bit slices, stacked vertically | 11 | y = 185.0 to 285.6 |
| a conspicuous empty gap | | y = 146.9 to 185.0 |
| more identical slices, same stack | 11 | y = 49.0 to 146.9 |
| one slice alone, off to the side | 1 | x = 80.5, y = 103.4 |

The whole checker is a single vertical column at x = 114.8 to 126.3 um on a die
200 um wide: eleven, a gap, eleven, plus one off to the side. Twenty-three, which
is the number the SCC analysis gave, arranged in a way that says the twenty-three
are not interchangeable.

That arrangement also explains why there are 23 counters and not 33. Eleven rows
plus eleven columns plus eleven of whatever the third family is would be 33. The
missing ten are the rows: the grid streams in one cell per clock, row-major, so
only one row is ever in flight, and a single counter cleared at each row boundary
serves all eleven rows. Columns and the third family are interleaved across the
whole frame, so each one needs its own counter that persists for the entire 121
cycles.

So the floorplan gives me the input format as well as the shape of the rule set,
and it tells me there is a third constraint family that I have not identified.

----

### 16. The first hypothesis, and why it was wrong

At this point the gates have told me the following, without any interpretation
on my part:

| the gates say | |
|---|---|
| the frame is 121 bits, arriving row-major, one per clock | sections 12 and 15 |
| eleven counters watch something that is spread across the whole frame | section 15 |
| eleven more counters watch something else, also spread across the frame | section 15 |
| one shared counter watches something that resets every 11 cells | section 15 |
| `success` requires all 23 to equal exactly **two** | section 14 |
| a separate eight-bit comparison against a fixed pattern must also hold | section 14 |

Two of something per row and two per column, on an 11 x 11 grid of bits, is a
description of a well known family of pencil puzzles: **Star Battle**, also called
**Two Not Touch**. That family adds a rule the counters cannot express, which is
that no two of the marked cells may touch, not even diagonally.

So my working hypothesis was the whole family at once: **two stars per row, two
per column, and no two adjacent including diagonally.**

A note on the word "star", because nothing in the gates says it. The gates say
"exactly two ones per row". The word comes from the two easter eggs I already
had: the input frames of the sample waveform spell `The night sky awaits`, and
the Morse bar code under the die spells `PER ARENAM AD ASTRA`, to the stars. That
is a naming convention and not a constraint, and nothing that follows depends on
it being right.

I tested the hypothesis rather than assuming it. Stage **P6** asks z3 for 25
grids that satisfy it perfectly, and feeds all 25 into the extracted netlist:

```
25 grids satisfying two per row, two per column, no touching
accepted by the netlist: 0
what the chip said instead: {'TRY AGAIN': 25}
```

Twenty-five generated, zero accepted, and the chip answered the same way to all
of them. Two conclusions follow. There is a constraint I have not found, which is
almost certainly the third family of eleven counters. And reading gate cones is
not going to find it, because I already tried that in section 14 and the counter
cones are unreadable.

----

### 17. Probing one grid cell at a time

The eleven unidentified counters each watch some set of grid cells. I could not
read their logic, so I measured them instead, with the simplest possible
experiment:

> For each of the 121 grid positions in turn, run the chip with a one at that
> position and zeros everywhere else, and record which counters increment.

If counter 4 ticks when the only one in the frame is at cell (3, 7), then cell
(3, 7) belongs to whatever counter 4 is watching. That is 121 separate runs of a
121-cycle frame, and it takes 0.04 seconds, because the simulator packs one trial
per bit of a Python integer and runs all 121 in a single pass. This is stage
**P7**.

```
column counters 11   irregular groups 11   shared row counters 1
```

The rows come back as zero, which is what the 23-versus-33 argument in section 15
predicted, and **the way they come back as zero confirms the input format**. The
row counter is cleared at every row boundary, so at the end of the frame it
always reads zero no matter what went in. Sampling it in the cycle each one
arrives instead, it moves in **110** of 121 trials, and the 11 it misses are
exactly cells

```
10  21  32  43  54  65  76  87  98  109  120
```

which is column 10 of every row: the last cell of a row, where the counter is
bumped and cleared on the same edge. 110 = 121 - 11. A single shared row counter
only works if the grid arrives row-major at one cell per clock, so that
measurement is a direct confirmation of the protocol I read off the waveform in
section 12.

And the eleven mystery counters watch eleven irregular contiguous blobs whose
sizes sum to exactly 121. They tile the grid:

```
     0  1  2  3  4  5  6  7  8  9 10
  0  A  A  A  A  A  B  B  C  D  D  E
  1  A  A  F  A  A  B  C  C  D  D  E
  2  A  A  F  B  B  B  B  C  C  D  E
  3  A  A  F  B  G  G  G  E  C  C  E
  4  F  A  F  B  G  E  E  E  E  E  E
  5  F  F  F  B  G  G  G  E  H  H  H
  6  B  B  B  B  B  B  G  E  H  I  I
  7  B  J  J  J  G  G  G  E  H  I  I
  8  B  J  J  K  E  E  E  E  H  I  I
  9  B  B  J  K  K  E  E  E  H  H  H
 10  B  J  J  K  E  E  E  E  E  E  E

region sizes  A=14 B=21 C=7 D=5 E=28 F=8 G=11 H=9 I=6 J=8 K=4   sum = 121
```

Irregular regions that tile the board, two per region, two per row, two per
column, no touching. That is Star Battle exactly, and the missing constraint was
the regions. The 25 grids of section 16 all failed because none of them respected
regions, which I did not know existed. Output:
[`puzzle-solution/06_region_map.txt`](puzzle-solution/06_region_map.txt).
----

### 18. Finding the 121 bits

This is the hard part of the whole exercise, so it gets the most space. I am
going to set it out properly, because "I gave it to a SAT solver" is not an
explanation of anything.

#### 18.1 What is actually being asked

Let the frame be a vector of 121 boolean variables,

```
x = (x_0, x_1, ..., x_120),   x_i in {0, 1}
```

where `x_i` is the bit presented on `I` at the `i+1`-th enabled rising edge.
Row-major, so `x_i` is grid cell (row `i div 11`, column `i mod 11`).

The chip is a deterministic finite state machine. Write `s_t` for the contents of
its 92 flip-flops after `t` clock edges, `s_0` for the state reset leaves behind,
and `d` for the one-edge transition the gates implement:

```
s_(t+1) = d(s_t, x_t)
```

`success` is one bit of `s_t`, so define

```
F(x) = the value of success in s_122
```

which is the composition of `d` with itself 122 times, starting from `s_0`,
driven by the 121 bits of `x` and then by whatever `I` happens to be on the last
edge. Every part of `F` is known exactly: it is 728 gates whose behaviour came
out of the Liberty file and which I have already checked against a recording of
the real chip.

Two questions, then:

```
does there exist x* with F(x*) = 1?           and is x* the only one?
```

Note what is not in that statement. There is no hidden key, no unknown constant,
no parameter I am fitting. The circuit is fully known; what is unknown is which
of its 2^121 possible inputs it accepts.

#### 18.2 The size of the space, and two cheap outs I checked first

```
2^121 = 2,658,455,991,569,831,745,807,614,120,560,689,152
      = 2.658 x 10^36
```

At a billion frames per second, a sweep takes 8.4 x 10^19 years, which is about
six billion times the age of the universe. So a sweep is not a slow option, it is
not an option.

Before reaching for a solver I checked whether the structure lets me cheat.

**Is `F` linear over GF(2)?** If it were, the chip would be an LFSR or a CRC, the
whole 121-bit frame would be a linear map, and Gaussian elimination would invert
it in about 121^3 = 1.8 million operations, which is instant. The definition of
an affine map over GF(2) is

```
F(u xor v) = F(u) xor F(v) xor F(0)
```

so it can be tested directly rather than argued about. The pipeline runs random
frames `u` and `v` through the netlist, and compares the predicted final state
against the measured one across **all 92 flip-flops**, not just `success`:

```
20 of 20 predictions failed
```

The state update is nonlinear. That kills linear algebra, and it kills every
correlation attack that depends on the same property. The counters are the reason:
a saturating counter is not an affine function of its inputs.

So: search, but not a blind one.

#### 18.3 Throwing away what cannot matter, the cone of influence

Not every net in the design can affect `success`. Walk backwards from `success`
through combinational logic and through flip-flops, collecting everything
reachable, and stop when nothing new appears.

```
cone of influence of success: 471 of 738 nets
```

The entire output generator falls outside it, which makes sense: `O[7:0]` depends
on `success` and on the message pointer, and `success` does not depend on `O`.
That drops 267 nets and, once multiplied by 122 time steps, a great deal of
formula. This is sound rather than heuristic: a net outside the cone cannot
change `success` under any assignment, so removing it cannot change whether the
question is satisfiable.

#### 18.4 Making time into space, the unrolling

A SAT solver has no notion of "later". The circuit does, so time has to be turned
into more variables.

For each step `t` from 1 to K+1 and each net `n` in the cone, there is a literal
`L(t, n)`. Three rules define them all:

| | rule |
|---|---|
| **reset** | at `t = 1`, every flop output is its reset value. `dfrtp` has a `clear` and reads 0. `dfstp` has a `preset` and reads 1. `dfxtp` has neither, so its value is left as a free variable |
| **combinational** | inside a step, a gate output is its Liberty function of its inputs *at the same step*: `L(t, n) = f(L(t, a), L(t, b), ...)` |
| **capture** | across a step, a flop takes `L(t+1, q) = (not clr) and (pre or d)`, where `clr`, `pre` and `d` are all evaluated at step `t` |

So step `t` settles the combinational logic from the state step `t-1` left behind
plus the inputs applied on edge `t`, and then the flops capture. `L(t+1, n)` is
what a probe would read after `t` clock edges, which is the convention that makes
the arithmetic in the depth question come out without an off-by-one.

The free variables are one per `(input, step)` for `I`, which is where the 121
bits live. `rst_n`, `enable` and `clk` are pinned to 1 across the whole window,
because the protocol says the frame is shifted in with reset released and enable
high.

The important thing to notice: **the flops disappear.** After unrolling there is
no state and no sequencing left, only a large combinational circuit and a lot of
variables. That is the whole point of bounded model checking.

#### 18.5 Making the circuit into clauses, and why the translation is honest

Section (VI) covers what Tseitin encoding is and why substitution does not work.
Here is the statement of what it buys, because the two results in this section
depend on it being exactly true and not approximately true.

Write `Def(g, t)` for the three or four clauses that define gate `g` at step `t`,
and let

```
PHI_K  =  reset clauses
          AND  Def(g, t)  for every gate g in the cone and every step t <= K+1
          AND  L(K+1, success)
```

**Soundness.** Take any assignment satisfying `PHI_K`. Each wire variable is
pinned by its own clauses to the value its gate produces from its inputs, so
reading the assignment off in step order reproduces a genuine simulation of the
circuit. The last clause forces `success` high at step K+1. Therefore the 121
values assigned to the `I` variables are a real frame that really unlocks the
chip.

**Completeness.** Take any frame that unlocks the chip. Simulate it, and write
every net's value at every step into the corresponding variable. Every `Def(g, t)`
is satisfied because the gate really does compute that, and the goal clause is
satisfied because `success` really is high. So the assignment satisfies `PHI_K`.

The two directions together mean `PHI_K` is satisfiable **exactly when** a
K-edge unlocking frame exists. That is the property that makes UNSAT a proof
rather than a failure, and it is why the encoder folds and shares gates but does
not do anything that would change the set of solutions.

#### 18.6 How big the formula is, and what the encoder does to shrink it

Written out naively, one fresh variable and three or four clauses per gate per
step, the puzzle formula is:

| | naive Tseitin | as the pipeline emits it |
|---|---|---|
| variables | 130,385 | **14,498** |
| clauses | 390,772 | **43,111** |
| time to encode | 0.23 s | **0.09 s** |

The difference is two rules applied while the clauses are being written, both of
which preserve the encoded function exactly:

| rule | what it does | how often it fires here |
|---|---|---|
| **constant folding** | A gate whose inputs are already known constants, or are the same literal, or are exact opposites, is replaced by the literal it equals. No variable is minted and no clause is written | **113,959 times** |
| **structural sharing** | A gate whose operator and input literals have been written before returns the variable that was minted then | **1,928 times** |

Folding fires that often for a specific reason. `rst_n`, `enable` and `clk` are
constants across the whole window, so every gate that depends only on them
collapses. Every flop's capture expression is `(not clr) and (pre or d)`, and for
the 84 `dfrtp_2` the preset is a constant 0 and for the 4 `dfstp_2` the clear is,
so both of those gates fold away at every one of the 122 steps before anything
interesting happens. And immediately after reset most of the design is holding a
known value, so the folding propagates forward through several steps of real
logic before it runs out.

A ninefold smaller formula is not just faster to solve. It is faster to build,
and building it was the larger cost.

#### 18.7 The depth question, and why one encoding answers both halves

I want the smallest K for which `PHI_K` is satisfiable, because that number is
the protocol.

`PHI_K` is a **prefix** of `PHI_(K+1)`: the extra clauses all define fresh
variables belonging to the extra step, and definitional clauses over fresh
variables can always be satisfied whatever the prefix assigns. So asking the
K-edge question inside the larger formula gives the same answer as asking it in
the smaller one. In practice that means the pipeline encodes once at the largest
depth it needs and asks the shorter question by asserting the goal literal one
step earlier, as an assumption rather than as a clause.

```
one unrolling to 122 edges   14498 variables   43111 clauses

K = 121 edges   UNSAT
K = 122 edges   SAT
```

**121 edges is provably impossible.** Not "I could not find one". So 121 cells in
and the verdict on the next edge is exactly the protocol, and it agrees with the
edge count I read off the sample waveform in section 12 without ever having
looked at it.

#### 18.8 Uniqueness

The solver returns one satisfying assignment. That does not by itself say there
is not another.

Take the 121 input literals from the answer, negate each one, and add their
disjunction as a single clause. That clause says "not this exact frame" and says
nothing about anything else, which is why it is built over exactly those 121
literals and not over the auxiliary variables, since two different assignments to
the auxiliaries would be the same frame. Re-solve.

```
blocking that assignment and re-solving: UNSAT  ->  the key is unique
```

There is exactly one 121-bit frame that unlocks this chip, and that is established
at the gate level, without assuming anything about what the puzzle is.

#### 18.9 Why the solver finds it in ten milliseconds and a sweep never would

It is worth being concrete about this, because "SAT solvers are clever" is not an
explanation either.

A CDCL solver never enumerates candidates. It runs a loop of four things:

| step | what happens |
|---|---|
| **unit propagation** | Any clause with all but one literal already false forces the remaining one. Applied until nothing more follows. On a Tseitin encoding this is exactly circuit simulation, and it runs both directions |
| **decision** | When nothing more propagates, pick an unassigned variable and guess a value. The heuristic prefers variables that have recently been involved in conflicts |
| **conflict analysis** | If a clause ends up all false, work out the *reason*: the small subset of decisions actually responsible. Record it as a new clause |
| **backjump** | Undo not one decision but every decision back to the point that reason was created, and carry the learned clause forward permanently |

The learned clause is the part that matters. It does not remove one candidate, it
removes every assignment that shares the responsible pattern, which is typically
an enormous region of the space, and it prevents the solver from ever making that
class of mistake again.

For this particular instance there is a second reason it is easy, and it comes
from the shape of the goal. `success` is an AND of 23 two-bit equality tests plus
one eight-bit comparison. Asserting `success = 1` therefore propagates
**backwards** with no search at all: an AND can only be 1 if every input is 1, so
all 23 counters are pinned to exactly two and the total is pinned to 22 before a
single input bit has been decided. The solver starts from an almost fully
determined final state and works backwards through the counters to the frame,
rather than starting from 121 free bits and working forwards. That is why the two
depth questions and the uniqueness proof together take 0.17 seconds.

Output:
[`puzzle-solution/07_sat_proof.txt`](puzzle-solution/07_sat_proof.txt).

#### 18.10 The answer it returned

121 = 11 x 11, so lay it out as a square:

```
. . . . . . . * . * .
* . . . . * . . . . .
. . . . . . . * . * .
* . * . . . . . . . .
. . . . * . * . . . .
. . * . . . . . * . .
. . . . * . . . . . *
. * . . . . * . . . .
. . . * . . . . . . *
. . . . . * . . * . .
. * . * . . . . . . .
```

Exactly two in every row, exactly two in every column, two in each of the eleven
regions from section 17, and no two touching, not even diagonally.

----

### 19. Solving it a second time, deliberately differently

Two independent confirmations are worth more than one careful one, so stage
**P9** solves the same puzzle again with nothing in common with stage P8.

| | stage P8, bounded model checking | stage P9, constraint solving |
|---|---|---|
| tool | a CDCL SAT solver | z3, an SMT solver |
| what it is given | the extracted gate netlist, unrolled | the region map from section 17, and the Star Battle rules stated explicitly |
| does it know what the puzzle is | **nothing at all** | everything |
| does it ever see the netlist | it sees nothing else | **never** |
| what it returns | one 121-bit frame, proved unique | every grid satisfying the rules |

```
solutions to the probed constraint set: 1 (that is all of them)
matches the SAT key: True
```

Different tool, different encoding, different inputs, same 121 bits. The first
method never learns what the puzzle is; it searches the recovered netlist
directly. The second never learns what the netlist is. They agree.

----

### 20. Writing the RTL, and proving it is the same circuit

Both solves confirm the answer. Neither confirms that I **understand** the
circuit, and that is what the challenge actually asks for. So stage **P11** writes
behavioural RTL for the whole chip from scratch, in terms of rows, columns,
regions and stars, and then proves it equivalent to the gates rather than
asserting it.

Two independent descriptions, two independent simulators, one vector set:

| class | grids |
|---|---|
| the unique solution | 1 |
| degenerate: empty grid, full grid | 2 |
| near misses: the solution with one star moved | 37 |
| random sparse grids, 1 to 30 stars | 200 |
| two stars in every row, columns and regions random | 200 |
| two per row **and** two per column, random permutation pairs | 100 |
| every count correct and two stars touching, built by z3 | 24 |

```
EQUIVALENCE: 0 success mismatches, 0 O mismatches over 564 grids
```

Every cycle of `success` and every cycle of the full output byte, compared, on
both descriptions, driven from the same reset with the same stimulus. The gates
are simulated by iverilog, which has never seen my RTL, and the RTL is simulated
by iverilog, which has never seen the geometry. Output:
[`puzzle-solution/08_recovered_rtl.v`](puzzle-solution/08_recovered_rtl.v) and
[`puzzle-solution/09_equivalence.txt`](puzzle-solution/09_equivalence.txt).

The last row of that table did not exist in my first version of this, and the
next section is where it came from.

----

### 21. The answer, and the fifth message: easter egg 9

Driving the recovered key in and reading `O[7:0]` cycle by cycle:

```
edge 122   0x28  '('    success = 1
edge 123   0x2a  '*'
edge 124   0x20  ' '
edge 125   0x54  'T'
edge 126   0x57  'W'
edge 127   0x4f  'O'
edge 128   0x20  ' '
edge 129   0x53  'S'
edge 130   0x54  'T'
edge 131   0x41  'A'
edge 132   0x52  'R'
edge 133   0x53  'S'
edge 134   0x20  ' '
edge 135   0x2a  '*'
edge 136   0x29  ')'
```

```
(* TWO STARS *)
```

`(* ... *)` is Verilog attribute syntax and also an OCaml comment. Inside it is
the rule the 728 gates spend the whole frame checking.

A waveform with `success` high, which was not provided with the puzzle, is
[`puzzle-solution/14_success_inputs.vcd`](puzzle-solution/14_success_inputs.vcd).
It is shaped deliberately like `example_inputs.vcd`, same six signals, same
timescale, same 10 ns clock, so the two open side by side in Surfer. `success`
first goes high at t = 1,255,000 ps, rising edge 126, which is enabled edge 122.

**Easter egg 9 is the rest of the output generator, where I nearly stopped one
message short.**

My first version of this was guesswork. Once the chip was answering correctly I
got curious about what else it could say, so I drove it with the four cases I
could think of and read `O[7:0]` on each: nothing, everything, something wrong,
and the answer. Four messages. I wrote that up.

Then I noticed that what I had was not a measurement of the ROM. It was a list of
the grids I happened to try, which is a different thing, and there was no reason
to believe the list was complete. So I replaced it with an enumeration.

Unroll the netlist from reset with all 121 input bits free, and ask the solver to
enumerate every value the output bus can take on the first output edge. Four come
back: `(`, `B`, `E`, `T`. Then, for each of those, enumerate every value the bus
can take on the second edge given the first. `T` splits into `R` and `W`; the
others do not split. Two characters separate every message, so when the
enumeration returns UNSAT the catalogue is closed and nothing else is reachable.
Five prefixes, fourteen SAT queries, the last one UNSAT. Each prefix hands back
the grid that produced it, which then gets simulated to read the rest of the
string.

This is the query pattern that yosys could not express, and it is why the encoder
exists.

| message | success | what triggers it |
|---|---|---|
| `EMPTY SKY` | 0 | all 121 bits zero |
| `BIG BANG` | 0 | all 121 bits one |
| `TRY AGAIN` | 0 | any ordinary wrong grid |
| **`TWO NOT TOUCH`** | 0 | every count correct, two stars per row **and** per column **and** per region, 22 stars, and at least one touching pair |
| `(* TWO STARS *)` | 1 | the one grid that satisfies every rule |

The `T` split is where the fifth message came from. One branch is `TRY AGAIN`.
The other returns a grid the gates answer with **`TWO NOT TOUCH`**, the other name
of Star Battle, and the chip prints it only when that exact rule is the one
broken.

To confirm the trigger rather than assume it, I asked z3 for 40 more grids in that
class and drove all 40 through the netlist, plus 20 controls that are two per row
and two per column and no-touch but wrong on regions:

```
40 of 40  counts correct and touching     ->  TWO NOT TOUCH,  success = 0
20 of 20  counts correct except regions   ->  TRY AGAIN,      success = 0
```

Exact condition: every count right, adjacency wrong. It is not reachable by
sweeping. I ran 60 random 22-star grids and 60 grids constructed to have two stars
in every row and every column, and all 120 came back `TRY AGAIN`, because none of
them also got the regions right.

Finding it also meant my recovered RTL was wrong. It had four verdicts, and the
540-grid equivalence run had passed only because none of its grids reached the
fifth case. So the RTL got a fifth verdict, and 24 grids built by z3 to be
counts-right-and-touching joined the vector set, which is where the 564 in
section 20 comes from.

An equivalence run is only as good as its vectors, and these vectors were extended
by a solver result rather than by guesswork. Output:
[`puzzle-solution/10_message_catalogue.txt`](puzzle-solution/10_message_catalogue.txt).
----

### 22. Everything the pipeline checks rather than assumes

Each of these is a thing that could quietly be wrong, so each of them is measured
on every run rather than argued about once.

| | |
|---|---|
| **Nets with no driver** | none. All 738 nets on the puzzle and all 84 on the warm-up have exactly one driver, first try. Nothing is tied off and nothing is guessed |
| **Nets with more than one driver** | none |
| **Combinational loops** | none. The topological sort of the gate graph completes, and the pipeline fails loudly if it ever does not |
| **Every via cut lands on metal on both sides** | 22,713 of 22,713 on the puzzle. This is the check that says the rotations and mirrors were applied correctly, and it needs no answer key, so it works on the puzzle as well as the warm-up |
| **Clock tree** | all 92 flop clock pins trace back through the 32 buffers to the single primary input `clk`. There is no gated clock in this design, which is what lets every later stage reason one rising edge at a time |
| **The four un-reset flops** | `u34` to `u37` are `dfxtp_2` with no reset, so real silicon powers them up randomly and a two-valued simulator has to pick something. The pipeline runs the answer with them initialised low, then again initialised high. `success = 1` and `(* TWO STARS *)` both times, so their power-up state is provably irrelevant to the result |
| **The same-layer gap tolerance** | the extractor treats two shapes on the same layer as one conductor if they come within 60 nm of each other without formally overlapping. I checked whether the result depends on that number and it does not: at 0 nm, 20 nm, 60 nm and 120 nm the recovered net partition is byte-identical on both designs, so it is not a fitting parameter. It matters on 23 li1 groups and on nothing else |
| **Determinism** | every number on this page is byte-identical run to run. Region letters are assigned by sorting on lowest cell index rather than on set iteration order, counter pairs are sorted on instance index, the simulation shards are collected in shard order, and nothing depends on dictionary ordering |

Two places are allowed to move if the SAT back end is swapped, and only two. The
warm-up has 15 valid answers, so the pair it returns is the solver's choice. And
each message in the catalogue is illustrated by *an* example grid that produces
it, and any grid in the class would do. Neither is a result, and neither changes
if the back end does not.

----

### 23. Making it fast, and what actually cost the time

The first working version of this was twenty numbered Python scripts shelling out
to `yosys` and `iverilog` for every question, and it took about **four minutes**.
Almost all of that was process startup and Verilog elaboration, repeated hundreds
of times to ask hundreds of nearly identical questions. Folding it into one file
that keeps its state in memory took it to **17 seconds**.

Then I measured where those 17 seconds were going, which is the only honest way
to start, and it turned out that two thirds of them were in three places nobody
would guess.

| stage | before | after | what changed |
|---|---|---|---|
| W2, extract the warm-up | 0.63 s | **0.17 s** | as P2 |
| P2, extract the puzzle | 4.87 s | **0.90 s** | the polygon union, the coordinate transforms and the union-find, all three below |
| P8, the depth and uniqueness solve | 1.15 s | **0.18 s** | one encoding for both depths, folding and sharing while encoding, one solver instead of three |
| P10, the message enumeration | 1.82 s | **0.41 s** | the same encoder changes, plus the back end chosen by measurement |
| P11, RTL and the 564-grid equivalence | 6.40 s | **2.15 s** | the equivalence simulation sharded across cores |
| the tool version banner | ~0.5 s | **0** | it was a second Python process launched from `RUN.sh` purely to import four packages and print their versions |
| **total, wall clock** | **17.0 s** | **4.9 s** | |

Five changes, in order of how much they bought.

#### Not computing something nothing reads

Three of the 4.87 seconds in P2 were inside one call: `shapely.unary_union`, once
per conductor layer, merging 10,819 li1 polygons into 5,472 islands and so on up
the stack.

What that call computes is the exact merged outline of the union, with the
interior boundaries dissolved. Nothing downstream ever reads an outline. What the
extractor actually needs is the **connected components** of the relation "these
two polygons touch", and it needs to know, for a given point, which component it
landed in.

Those components can be had directly: one `STRtree` per layer, one `dwithin`
query per layer over the raw polygons, and union-find over the pairs that come
back. And it gives the identical partition, for a reason worth writing down:

```
distance(p, A union B)  =  min( distance(p, A), distance(p, B) )
```

so merging shapes first and then asking whether something is within 60 nm can
never give a different answer from asking about the members directly. The
transitive closure is the same set either way. Measured on `puzzle.gds`, the two
approaches agree island for island on all six layers.

```
unary_union then stitch     3.08 s
union-find on raw polygons  0.28 s
```

Eleven times faster, and it deletes code rather than adding any.

#### Doing the arithmetic once for everything, instead of once per shape

Flattening the hierarchy means applying each placement's rotation, mirror and
translation to every polygon in the cell it places. That is 31,844 affine
transforms on the puzzle, and the code did them one shapely call at a time.

shapely 2.0 can hand back the coordinates of a whole array of geometries as one
numpy array, and take them back the same way. So: pull every polygon's
coordinates out in one call, build one array of per-polygon transform
coefficients, apply the whole transform as four multiplies and two adds over the
entire array, and put the coordinates back in one call.

```
one shapely call per polygon   0.54 s
one numpy pass over all of them  0.09 s
```

The same idea applies twice more. Polygons are now built in bulk from
concatenated coordinate arrays rather than one `Polygon(...)` at a time. And the
interior point used to locate a pin or a via is taken **once per cell
definition** and then moved by the same cheap transform, rather than transforming
the polygon at every placement and asking shapely for a fresh interior point each
time. An affine map sends interior points to interior points, so the two are
equivalent, and there are 66 cell definitions and 9,875 placements.

#### Union-find on integers instead of on tuples

The union-find keys were `(layer, index)` tuples in a dictionary. They are now
plain integers into one flat list, with a layer offset added in. Same algorithm,
same path compression, no hashing and no tuple allocation on a loop that runs
120,000 times.

This one has a visible side effect and it is worth being straight about it. Net
names are assigned by sorting on the union-find root, so changing what a root
*is* renumbered the internal nets. The circuit did not change: I compared the two
netlists as partitions of pins into nets, with ports attached, and they are
**identical on both designs**, 738 nets and 84 nets, which is the same test
section 6 uses to prove the extraction correct in the first place. Only the
arbitrary `net_NNN` labels moved.

#### Encoding once and asking many times

Covered in detail in section (VI) and section 18, but the numbers belong here.
The old code built the CNF from scratch for K=121, again for K=122, and a third
time for the uniqueness re-solve, then a fourth for the enumeration. Now the
depth question is one encoding asked twice by assumption plus one blocking
clause, so one solver is built where there were three.

On top of that the encoder folds constants and shares identical gates as it
writes:

| | before | after |
|---|---|---|
| variables | 130,385 | **14,498** |
| clauses | 390,772 | **43,111** |
| solvers built in P8 | 3 | **1** |

Loading a formula into the solver is a per-clause call across the Python boundary,
so a formula nine times smaller loaded a third as often is most of the 1.15 s to
0.18 s.

#### Using the other fifteen cores

The 564-grid equivalence run was a single `vvp` process stepping 564 grids of 140
cycles through 728 gates, and it was the largest single item left at 5.5 seconds.
Compiling with `iverilog` turned out to be 0.05 s of that, so the fix is not about
compilation at all.

The testbench now reads `+shard` and `+shards` and runs only the trials whose
number falls in its shard, while still stepping the same random stream, so the
trial list is **partitioned rather than resampled** and every grid is still
covered exactly once. The pipeline compiles once and launches one `vvp` per core.

Determinism survives, deliberately: the shards are collected in shard order
rather than completion order, and the shard count itself never appears in the
output, so the transcript is identical on a machine with two cores and one with
sixteen.

#### What I did not do, and why

| | |
|---|---|
| Cache the extraction between runs | The whole point is that `puzzle-solution/` is deleted and rebuilt from the shipped files every time. A cache would make the reproduction claim weaker in exchange for seconds |
| Rewrite the hot loops in C or Cython | It would add a build step to a repository whose install is "clone it and run one script". The remaining Python hot loop is the union-find, at about 0.2 s |
| Drop iverilog and use the built-in simulator for the equivalence run | Then the equivalence check would be my simulator against my RTL, both of which I wrote. Its entire value is that it is an independent second opinion, so it stays even though it is now the slowest thing left |
| Parallelise the two extractions | The warm-up has to pass before the puzzle is worth running, and it now takes 0.17 s |

Each of the three main results is still cross-checked by a tool that did not
produce it:

| result | produced by | independently confirmed by |
|---|---|---|
| the extracted netlist | `gdstk` and `shapely` geometry | the shipped DEF and golden netlist, and a recording of the real chip |
| the 121-bit key | a SAT solver on the unrolled gates | z3 on the probed region map, which never sees the netlist |
| the recovered RTL | reading the structure by hand | `iverilog`, 564 grids, against the gates |

----

### 24. Files the run produces

| file | what it is |
|---|---|
| [`puzzle-solution/01_gds_inventory.txt`](puzzle-solution/01_gds_inventory.txt) | Bill of materials for `puzzle.gds`: every placement, every label, every layer |
| [`puzzle-solution/02_extracted_netlist.v`](puzzle-solution/02_extracted_netlist.v) | The gate netlist, recovered from geometry alone |
| [`puzzle-solution/03_cell_models.v`](puzzle-solution/03_cell_models.v) | Simulation models for the 66 cell types, generated from the Liberty |
| [`puzzle-solution/04_vcd_replay.txt`](puzzle-solution/04_vcd_replay.txt) | The extraction checked against the recorded silicon waveform |
| [`puzzle-solution/05_register_structure.txt`](puzzle-solution/05_register_structure.txt) | Register graph, feedback groups, what `success` and `O` depend on |
| [`puzzle-solution/06_region_map.txt`](puzzle-solution/06_region_map.txt) | The constraint map read out of the gates, plus the floorplan |
| [`puzzle-solution/07_sat_proof.txt`](puzzle-solution/07_sat_proof.txt) | Minimum depth, the key, and the uniqueness proof |
| [`puzzle-solution/08_recovered_rtl.v`](puzzle-solution/08_recovered_rtl.v) | Behavioural RTL for the whole chip |
| [`puzzle-solution/09_equivalence.txt`](puzzle-solution/09_equivalence.txt) | Gates against RTL, 564 grids |
| [`puzzle-solution/10_message_catalogue.txt`](puzzle-solution/10_message_catalogue.txt) | Every string the chip can print, and what triggers each |
| [`puzzle-solution/11_solution_grid.txt`](puzzle-solution/11_solution_grid.txt) | Region map, the unique solution, and the checks |
| [`puzzle-solution/12_input_sequence.txt`](puzzle-solution/12_input_sequence.txt) | How to drive the chip, and the 121 bits |
| [`puzzle-solution/13_output_string.txt`](puzzle-solution/13_output_string.txt) | The answer, cycle by cycle |
| [`puzzle-solution/14_success_inputs.vcd`](puzzle-solution/14_success_inputs.vcd) | The waveform with `success` high, shaped like the sample so the two open side by side |
| [`warmup-solution/`](warmup-solution/) | The same, for the warm-up, plus the golden cross-check and the recovered names |
