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
| String value recovered from the chip after driving in a valid input sequence | (* TWO STARS *) (see [answer.txt](https://github.com/NotCleo/GDS-to-RTL/blob/main/solution/answer.txt)) |
| Valid input sequence | (see [input_sequence.txt](https://github.com/NotCleo/GDS-to-RTL/blob/main/solution/input_sequence.txt)) |
| The puzzle's region map, the unique solution grid | (see [solution_grid.txt](https://github.com/NotCleo/GDS-to-RTL/blob/main/solution/solution_grid.txt)) |
| The recovered behavioural RTL for the whole design | (see [puzzle_recovered.v](https://github.com/NotCleo/GDS-to-RTL/blob/main/solution/puzzle_recovered.v) |

----

## Summary of all Easter Eggs found

| Easter Egg | Context |
|---|---|
| (I) "PER ARENAM AD ASTRA" (Latin for "through the sand, to the stars") | Found in [puzzle.gds](https://github.com/NotCleo/GDS-to-RTL/blob/main/puzzle-task/puzzle.gds)|
| (II) "Leave no stone unturned!" (Human inserted entry in the log) | Found in [example_inputs.vcd](https://github.com/NotCleo/GDS-to-RTL/blob/main/puzzle-task/example_inputs.vcd)|
| (III) "Sat Dec 31 23:59:60 2016" (A Leap Second)| Found in [example_inputs.vcd](https://github.com/NotCleo/GDS-to-RTL/blob/main/puzzle-task/example_inputs.vcd)|
| (IV) "EMPTY SKY, BIG BANG, TRY AGAIN" (Error message for driving incorrect input sequences) | Found in [sucesss_inputs.vcd](https://github.com/NotCleo/GDS-to-RTL/blob/main/success_inputs.vcd)|
| (V) "(* TWO STARS *)" (Success message for driving correct input sequence) | Found in [sucesss_inputs.vcd](https://github.com/NotCleo/GDS-to-RTL/blob/main/success_inputs.vcd)|
| (V) "(* *)" (Commenting syntax used by OCaml/HardCaml) | Found in [sucesss_inputs.vcd](https://github.com/NotCleo/GDS-to-RTL/blob/main/success_inputs.vcd)|
| (VI) "Switch to ASCII" (Reading Waveforms in ASCII) | Found in [sucesss_inputs.vcd](https://blog.janestreet.com/using-ascii-waveforms-to-test-hardware-designs/)|
| (VII) "Jane Street logo, etched in metal 2" | Found in [puzzle.gds](https://github.com/NotCleo/GDS-to-RTL/blob/main/puzzle-task/puzzle.gds) |
| (VIII) "The night sky awaits" | Found in [example_inputs.vcd](https://github.com/NotCleo/GDS-to-RTL/blob/main/puzzle-task/example_inputs.vcd) |
| (IX) 496 (3rd Perfect Number in warmup puzzele) | Found in [00_source.v](https://github.com/NotCleo/GDS-to-RTL/blob/main/warmup-task/00_source.v) |


----

## Summary of README

I have documented my entire solution's implementation is this readme file, below table is a glimpse of what follows;

| Title | What it is about |
|---|---|
| (I) What were the files provided for the puzzle | You can have a look into the puzzle's provided input files |
| (II) The first breakthrough moment  | Discusses my first breakthrough while inspecting the puzzle's waveform file |
| (III) What I did  | A summary of what I did |
| (IV) What the puzzle turned out to be  | A summary of what the solution of this puzzle is |
| (V) Success Waveform  | The puzzle's main solution/deliverable component |
| (VI) How to run | Quick start / Installations |
| (VII) Directory Layout  | Solution's File layout |
| (VIII) Read More  | Break out links for further descriptions |

----


## (I) What were the files provided for the puzzle

The puzzle provided the following files : 

| File | What it is about | 
|---|---|
| (I) [A GDS file](https://github.com/janestreet/asic-puzzle-2026/blob/master/puzzle.gds) (1.4MB) | contains metal, routing, and active transistor layers, with the cell names, net names and hierarchy stripped out |
| (II) [A Layout image](https://github.com/janestreet/asic-puzzle-2026/blob/master/layout.png) (136KB)| an image of the GDS file with the I/O's labelled for reference |
| (III)  [An Example Inputs VCD](https://github.com/janestreet/asic-puzzle-2026/blob/master/example_inputs.vcd) (8.4KB)|  driven by incorrect inputs, with a "success" flag that stays low (we need to drive it high, after providing the circuit with correct inputs). |

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

see logs for both tests [here](https://github.com/NotCleo/GDS-to-RTL/blob/main/puzzle-task/exiftool.log).


-----

Here's how the waveform (of the provided VCD file) looks like : 

You will notice the "success" flag remains low throughout.

![Surfer showing waveform of example inputs VCD file](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/example_inputs_waveform.png)

----

## (II) My first breakthrough moment 

Switching to ASCII (I rarely use ASCII and prefer staying in Decimal/Hexadecimal/unsigned Integer) was the first breakthrough, I was on the [blog site](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/), and my eyes fell on : 

![Blog Site highlighted](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/switching-to-ascii-moment.png)

----

It was at this point while viewing the waveform when I decided to switch to viewing the VCD file in ASCII.

Which revealed the following message "TRY AGAIN" (at 1255000 ps marker): 

![Surfer showing waveform displaying "TRY AGAIN"](https://github.com/NotCleo/GDS-to-RTL/blob/main/Images/try_again_message.png)


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


##### Note : Star Battle is also referred to as Two Not Touch

- One can read about how the puzzle works [here](https://krazydad.com/twonottouch/intro_tutorial/)

##### Want to try the puzzle?

- Check out this sample [interactive Two Not Touch Puzzle](https://krazydad.com/play/starbattle/?kind=10x10&volumeNumber=2&bookNumber=1&puzzleNumber=24)

----

## (VI) How to run 

The following table summarizes what was utilized

| Name | Type | Why it was used |
|---|---|---|
| **yosys** | CLI tool | RTL synthesis for the warm-up forward flow (`synth` → `dfflibmap` → `abc`), and the inline `sat` / BMC (which is Bounded Model Checking) invocations to discharge the formal proofs on the extracted gate netlist. |
| **iverilog** | CLI tool | Compiles the generated testbenches against the PDK cell models. Every simulation in the flow shells out to it. |
| **OpenROAD** | CLI tool | Downstream (RTL to GDS) run on the warm-up source, to measure what information the downstream flow destroys before attempting to reverse it. |
| **KLayout** | GUI tool | Layout viewer|
| **Surfer** | GUI tool | Waveform viewer |
| **GDS3D** | GUI tool | Better 3D rendering of the layer stack, separating power grid and routing from the logic, and isolating poly-over-diff to see the transistors. |
| **Tiny Tapeout GDS Viewer** | Web tool | Zero-install browser view of the layout for quick inspection. |
| **Magic** | CLI/GUI tool | sky130 layout and extraction; explored as an extraction route |
| **gdstk** | Python package (pip) | GDSII parsing and hierarchy flattening : the front end of the extractor |
| **shapely** | Python package (pip) | Polygon union and STRtree spatial indexing : the core of net extraction (Requires ≥2.0: 1.x has no `predicate=` keyword and returns geometries instead of integer indices, which silently builds the wrong netlist) |
| **z3-solver** | Python package (pip) | SMT (Satisfiability Modulo Theories) constraint solving |
| **numpy** | Transitive dependency | Pulled in by gdstk and shapely; never imported directly by any script. |
| **collections** | Stdlib module | Grouping and counting during island/net construction and register-graph analysis. |
| **csv** | Stdlib module | Writes `instances.csv` and `labels.csv` — the bill of materials from provided puzzle GDS file |
| **json** | Stdlib module | Interchange between pipeline stages: `extracted.json`, `name_map.json`, `structure.json`, `slots.json`, `regions.json`, `uniqueness.json`. |
| **math** | Stdlib module | Coordinate arithmetic in the extractor : island gap thresholds, geometric distances. |
| **os** | Stdlib module | Path handling and environment overrides (`LEF=`, `GAP=`, `PROBE=`). |
| **re** | Stdlib module | Parsing Liberty `function:` strings into Verilog models, plus Verilog and VCD tokenising. |
| **subprocess** | Stdlib module | Shelling out to `iverilog`/`vvp` for simulation and `yosys` for formal. |
| **sys** | Stdlib module | Argument handling, exit codes, diagnostics. |
| **tempfile** | Stdlib module | Scratch files for the shelled-out simulation and formal runs. |
| **importlib.util** | Stdlib module | Loads a sibling script by file path |
| **tkinter** | Stdlib module | The interactive Two Not Touch board  |
| **python3-tk** | System package (apt) | Debian/Ubuntu ship tkinter separately from the interpreter|
| **sky130_fd_sc_hd Liberty (`.lib`)** | PDK data | Ccontain the standard cell timing, power, and functional data for the SkyWater 130nm High-Density digital library |
| **sky130_fd_sc_hd merged LEF** | PDK data | Cell pin geometry and obstructions that matched against polygons |


### Complete Installation (Ubuntu/Debian)
    
    git clone https://github.com/NotCleo/GDS-to-RTL.git
    cd GDS-to-RTL
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    sudo apt install yosys iverilog python3-tk
    mkdir -p ~/surfer_install && cd ~/surfer_install
    wget "https://gitlab.com/api/v4/projects/42073614/jobs/artifacts/main/raw/surfer_linux.zip?job=linux_build" -O surfer_linux.zip
    unzip surfer_linux.zip
    chmod +x surfer
    mkdir -p ~/.local/bin
    mv surfer ~/.local/bin/
    export PATH="$HOME/.local/bin:$PATH"
    bash run.sh

#### To view the run results (for puzzle): 

    cd results/puzzle
    sudo apt install tree -y
    tree

#### To view the run results (for warmup): 

    cd results/warmup
    sudo apt install tree -y
    tree

In either directories, you will find all deliverable files, but the main list of output files have been listed in a dedicated section below.

#### Note : OpenROAD is not necessary, unless you want to perform any downstream runs yourself.

If you want to attempt complete OpenROAD run, please watch this [short video](https://www.youtube.com/watch?v=QnJzoJjC7RQ)

#### Note : You can see the complete run log [here](https://github.com/NotCleo/GDS-to-RTL/blob/main/run.log) and for more details about the files produced by the pipeline, see [here](https://github.com/NotCleo/GDS-to-RTL/blob/main/RUN.md).

----

## (VII) Layout

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

----

## (VIII) Read more

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
