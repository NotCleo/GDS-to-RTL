# The puzzle

The real thing. 728 logic cells, 738 nets, 92 flip-flops, no names, no answer key.

## What is in here

| path | what it is |
|---|---|
| `puzzle.gds` | As supplied. Polygons only. |
| `example_inputs.vcd` | As supplied. A recorded run of the real chip, with `success` staying low. |
| `layout.png` | As supplied. The hint image from the blog post. |
| `puzzle-recovery-files/` | Everything the pipeline produced on the way, kept as a record. Same tree `run.sh` writes to `results/puzzle/`. |
| the deliverables | Live one level up in [`../solution/`](../solution/), so there is only one copy of them. |

## What it turned out to be

An 11x11 Star Battle, also known as Two Not Touch. Place two stars in every row,
every column and every lettered region, and no two stars may touch, not even
at a corner. Feed the grid in one cell per clock, row-major, and the chip checks
all three constraint families in parallel with 23 two-bit saturating counters.

There is exactly one valid grid. Drive it in and the chip says so:

![Surfer showing success rising and O[7:0] spelling out the verdict](../Images/success-waveform.png)

`success` goes high on the 122nd enabled rising edge, one clock after the last
grid cell, and latches. From that same edge `O[7:0]` streams the verdict one
character per clock:

```
(* TWO STARS *)
```

Which is both the answer and a joke about the rules.

## The answer

The 121-bit row-major input sequence, and the grid it draws:

```
0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
```

```
     0 1 2 3 4 5 6 7 8 9 10
   0  . . . . . . . * . * .
   1  * . . . . * . . . . .
   2  . . . . . . . * . * .
   3  * . * . . . . . . . .
   4  . . . . * . * . . . .
   5  . . * . . . . . * . .
   6  . . . . * . . . . . *
   7  . * . . . . * . . . .
   8  . . . * . . . . . . *
   9  . . . . . * . . * . .
  10  . * . * . . . . . . .
```

Full region map, per-row bits and the clocking protocol are in
[`../solution/solution_grid.txt`](../solution/solution_grid.txt) and
[`../solution/input_sequence.txt`](../solution/input_sequence.txt).

## The deliverables

All seven live at the repo root in [`../solution/`](../solution/).

| file | what it is |
|---|---|
| `../solution/answer.txt` | The recovered string. |
| `../solution/solution_grid.txt` | Region map, the unique solution, and the rules in plain text. |
| `../solution/input_sequence.txt` | The 121 bits and how to clock them in. |
| `../solution/puzzle_recovered.v` | Behavioural RTL for the whole design, proved cycle-equivalent to the extracted gates over 540 grids. |
| `../solution/easter_eggs.txt` | Layer-set diff against the warm-up, the rasterised logo, and the decoded Morse. |
| `../solution/floorplan.txt` | Recovered blocks mapped back to die coordinates. |
| `../solution/vcd_message.txt` | The two VCD header fields, and the hidden ASCII decoded out of the supplied inputs. |

To reproduce all of it from `puzzle.gds`, see [`../RUN.md`](../RUN.md).
To read how it was worked out, see [`../WRITEUP.md`](../WRITEUP.md).
