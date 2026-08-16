# ASIC Reverse-Engineering Puzzle 2026 

This repo contains my solution at solving [ASIC Reverse-Engineering Puzzle 2026](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/) hosted by Jane Street. 

I decided to call my submission "GDS-to-RTL", contrary to "RTL-to-GDS" :)

The "ASIC Reverse-engineering" involves recovering a circuit from a layout file, working out what the circuit perorms, and then solving it.

Grateful to authors of [ReGDS: A Reverse Engineering Framework from GDSII to Gate-level Netlist](https://ieeexplore.ieee.org/document/9300272/) for being a good starting point in this puzzle. 

----

## Summary of Results

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
- [A Layout image](https://github.com/janestreet/asic-puzzle-2026/blob/master/layout.png), an image of the GDS file with the I/O's labelled for reference
- [An Example Inputs VCD](https://github.com/janestreet/asic-puzzle-2026/blob/master/example_inputs.vcd), driven by incorrect inputs, with a "success" flag that stays low (we need to drive it high, after providing the circuit with correct inputs).

Here's how the waveform (of the provided VCD file) looks like : 

You will notice the "success" flag remains low throughout.

![Surfer showing waveform of example inputs VCD file](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/example_inputs_waveform.png)

----

It was here, when I decided to switch to viewing the VCD file in ASCII at this point, which reveals the following message "TRY AGAIN" (at 1255000 ps marker): 

![Surfer showing waveform displaying "TRY AGAIN"](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/try_again_message.png)


----

Switching to ASCII (and not staying in Decimal/Hexadecimal) was my first breakthrough, I was on the [blog site](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/), and my eyes fell on : 

![Blog Site highlighted](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/switching-to-ascii-moment.png)

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
