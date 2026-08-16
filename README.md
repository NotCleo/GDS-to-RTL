# ASIC Reverse-Engineering Puzzle 2026 

This repo contains my solution at solving [ASIC Reverse-Engineering Puzzle 2026](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/) hosted by Jane Street. 

I decided to call my submission "GDS-to-RTL", contrary to "RTL-to-GDS" :)

The "ASIC Reverse-engineering" involves recovering a circuit from a layout file, working out what the circuit perorms, and then solving it.

Grateful to authors of [ReGDS: A Reverse Engineering Framework from GDSII to Gate-level Netlist](https://ieeexplore.ieee.org/document/9300272/) for being a good starting point in this puzzle. 

----

## Summary of Results

The table below summarises which problems have been successfully solved, the HDL used (Verilog/Hardcaml), and the number of clock cycles used to solve my personal puzzle's input for each day. The 'size' of each puzzle's input has been noted for each day (using my personal puzzle input file). The discussions below often test with various size inputs, not just my personal puzzle inputs. As per [the Advent of Code Rules](https://adventofcode.com/2025/about#faq_copying), sharing of actual inputs is not permitted, so feel free to provide your own input text files (these should be formatted in the exact same format as the Advent of Code site provides). However, in my own investigation and benchmarking of my designs, I wrote my own scripts to generate sample inputs of varying sizes. These functions can be found in [`generate_input.py`](/verilog/scripts/generate_input.py).

| Day               | Solved (Verilog/Hardcaml/Both) | Clock Cycles | Input Size                                           |
| ----------------- | ------------------------------ | ------------ | ---------------------------------------------------- |
| [Day 1](#day-1)   | Both                           | 19,691       | 4780 rotations                                       |
| [Day 2](#day-2)   | Both                           | 1,729        | 38 ranges                                            |
| [Day 3](#day-3)   | Verilog                        | 20,217       | 200 lines (100 chars per line)                       |
| [Day 4](#day-4)   | Verilog                        | 37,108       | 137 x 137 grid                                       |
| [Day 5](#day-5)   | Verilog                        | 66,649       | 177 ranges, 1000 query IDs                           |
| [Day 6](#day-6)   | Verilog                        | 35,139       | 4 numeric rows, 1000 operators, ~3709 chars per line |
| [Day 7](#day-7)   | Verilog                        | 121,496      | 142 x 142 grid                                       |
| [Day 8](#day-8)   | Verilog                        | 1,744,510\*  | 1000 x,y,z coordinates                               |
| [Day 9](#day-9)   | Verilog                        | 1,341,548    | 496 coordinates                                      |
| [Day 10](#day-10) | Verilog                        | 58,319,971\* | 177 machines (up to 13 x 10)                         |
| [Day 11](#day-11) | Verilog                        | 66,542       | 583 device names                                     |
| [Day 12](#day-12) | Hardcaml                       | 25,098       | 6 shapes, 1000 region queries                        |

## Timeline

Below table briefly summarizes the sequence of what I tried : 

| Event | Action |
|---|---|
| Puzzle Announcement (Aug 5) | spent my evening reading the blog and puzzle repository |
| Warmup Task (Aug 6-8) | spent performing the downstream run (RTL-to-GDS) using provided warmup RTL using OpenROAD to understand downstream information gain/loss |
| Warmup Reverse Engineering (Aug 8-9) | Crafted and tested the netlist recovery pipeline using provided warmup GDS layout file |
| Main Puzzle (Aug 9-12) | Recovered the netlist and the circuit, and the correct puzzle solution |
| Submission (Aug 12) | Submitted the solution |

----

## Provided files for the puzzle

The puzzle provided the following files : 

- [A GDS file](https://github.com/janestreet/asic-puzzle-2026/blob/master/puzzle.gds).
  Contains metal, routing, and active transistor layers, along with some sample inputs and outputs.
  Polygons on numbered layers, with the cell names, net names and hierarchy stripped out.
- [An Example Inputs VCD](https://github.com/janestreet/asic-puzzle-2026/blob/master/example_inputs.vcd), driven by incorrect inputs, with a "success" flag that stays low (we need to drive it high, after providing the circuit with correct inputs).

Here's how the waveform (of the provided VCD file) looks like : 

![Surfer showing waveform of example inputs VCD file](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/example_inputs_waveform.png)

- [A Layout image](https://github.com/janestreet/asic-puzzle-2026/blob/master/layout.png), an image of the GDS file with the I/O's labelled for reference

----

## What I did

- Extracted a netlist from the raw geometry present in the puzzle GDS file.
- Proved the extractor pipeline exact against the warm-up's golden files, then validated it against the real chip's recorded outputs. 
- Recovered the register structure, read the design's hidden data out of the silicon by probing it 121 times, solved the resulting puzzle two independent
ways, and proved a behavioural model cycle-equivalent to the gates.

----

## What the puzzle turned out to be

- An "11x11 Star Battle (Two Not Touch) Validator". Two stars per row, per column and per region, no two
touching. Exactly one grid works. Drive in a solved 11x11 Two Not Touch Puzzle grid serially and the chip prints:

```
(* TWO STARS *)
```

### Success Waveform 

![Surfer showing success high and O[7:0] spelling the verdict](Images/success-waveform.png)


##### Note : Star Battle is also referred to as Two Not Touch

- One can read about how the puzzle works [here](https://krazydad.com/twonottouch/intro_tutorial/)

#### Want to try the puzzle?

- Check out this [interactive Two Not Touch Puzzle](https://krazydad.com/play/starbattle/?kind=10x10&volumeNumber=2&bookNumber=1&puzzleNumber=24)

----

## "Hey How did you figure out that you needed to switch to ASCII to see the message?"

Funny story while I was on the blog screen, my eyes fell on : 

<img width="1136" height="655" alt="image" src="https://github.com/user-attachments/assets/1b4f7408-20ad-40e5-9dbc-080f8aad250a" />

----

## Go here to read more

| you want | go here |
|---|---|
| The story of how it was worked out, start to finish | [`WRITEUP.md`](WRITEUP.md) |
| Just the answer | [`solution/`](solution/) |
| To run the whole thing yourself | [`RUN.md`](RUN.md) |
| What each of the 20 scripts does | [`GDS-to-RTL/README.md`](GDS-to-RTL/README.md) |
| The puzzle, the answer and the recovery outputs | [`puzzle-task/README.md`](puzzle-task/README.md) |
| The warm-up, and the full teardown of it | [`warmup-task/README.md`](warmup-task/README.md) |
| All eight easter eggs, and how each turned up | [`Easter-Eggs/README.md`](Easter-Eggs/README.md) |
| To play the puzzle yourself | [`TwoNotTouch-Interactive-Puzzle/README.md`](TwoNotTouch-Interactive-Puzzle/README.md) |
| Viewer setup, tooling notes, dead ends | [`extra-stuff/tips-and-personal-notes.txt`](extra-stuff/tips-and-personal-notes.txt) |
| Jane Street's original brief | [`Challenge-README.md`](Challenge-README.md) |

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash run.sh
```

Needs `yosys`, `iverilog` and `python3-tk` from your package manager. About four
minutes end to end. Full detail, including what each of the fourteen checkpoints
should print, is in [`RUN.md`](RUN.md).

## Layout

| directory | what is in it |
|---|---|
| `solution/` | The seven deliverables. The answer, the grid, how to drive the chip, the recovered RTL. |
| `GDS-to-RTL/` | The 20 pipeline scripts, numbered in run order. |
| `puzzle-task/` | `puzzle.gds` as supplied, plus everything recovered from it. |
| `warmup-task/` | The practice design and its golden files, plus the teardown. |
| `Easter-Eggs/` | The eight things hidden in the chip and the repo. |
| `TwoNotTouch-Interactive-Puzzle/` | A tkinter board so you can play it by hand. |
| `pdk/` | The sky130 Liberty and merged LEF the extractor reads. |
| `Images/` | Screenshots used by the READMEs. |
| `extra-stuff/` | Working notes and a full run log. |

`run.sh` also writes `results/`, which is 7 MB of intermediates and is
gitignored. Every file in it is filed permanently under `puzzle-task/` and
`warmup-task/`, so nothing is lost by not committing it.
