# Personal notes, tooling, and dead ends

Working notes kept while solving this. Not part of the solution. The viewer
setup and the dead ends are recorded because they cost time.

---

## Learning to read a GDS at all

I started from the SkyWater PDK's own cell layouts rather than from the puzzle.
The Liberty file:

```
~/.ciel/ciel/sky130/versions/0fe599b2afb6708d281543108caf8310912f54af/
  sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
```

and the per-cell documentation, for example
[or4b](https://skywater-pdk.readthedocs.io/en/main/contents/libraries/sky130_fd_sc_hd/cells/or4b/README.html).

Working through a half adder by hand, from polygons back to "this is a half
adder", is what made the rest of it make sense. Worth doing before writing any
extractor.

---

## Viewers

| tool | verdict |
|---|---|
| [Tiny Tapeout GDS viewer](https://gds-viewer.tinytapeout.com/) | Zero install, opens in a browser, good for a first look at the whole die. Awkward once you want to magnify one small block. |
| [GDS3D](https://github.com/trilomix/GDS3D) | What I switched to. Renders the layer stack in 3D, so you can separate the power grid from the routing and isolate poly over diffusion to see the transistors. `F1` inside the app lists the inspection keys. |
| KLayout | For spot-checking a single coordinate. |
| Surfer | Waveform viewer. Better than GTKWave here, mostly because switching a bus to ASCII is a right click. |

GDS3D build, on Ubuntu 24.04 LTS:

```bash
git clone https://github.com/trilomix/GDS3D.git
cd GDS3D/linux
chmod +x BuildLinux.sh
./BuildLinux.sh
./GDS3D -p ../techfiles/sky130.txt -i ../../puzzle/puzzle.gds
```

It would have been nice to have qckvu for streaming the GDS files.

---

## Dead end: exiftool

The obvious first move on a set of provided files is to look at their metadata.
I ran exiftool over all three puzzle files. Nothing.

```
$ exiftool layout.png
File Name                       : layout.png
File Size                       : 136 kB
File Type                       : PNG
Image Width                     : 880
Image Height                    : 1000
Bit Depth                       : 8
Color Type                      : RGB with Alpha
Compression                     : Deflate/Inflate
Background Color                : 255 255 255
Pixels Per Unit X               : 96
Pixels Per Unit Y               : 96
Image Size                      : 880x1000
```

No comment chunk, no author, no custom text. A plain PNG.

A negative result worth recording: the metadata that matters in this puzzle is
*inside* the file formats, not attached to them. The VCD header fields
(`$date`, `$version`) and the unknown GDS layer 200/0 are both metadata in that
sense, and neither of them is anything exiftool would ever look at.

---

## File sizes across the forward flow

Running the warm-up files in order, the sizes show what each stage adds:

| file | size | what got added |
|---|---|---|
| `00_source.v` | 1.2 KB | intent |
| `01_netlist.v` | 19 KB | gates |
| `02_netlist_with_power_rails.v` | 30 KB | power connections |
| `03_post_place_and_route.def` | 112 KB | coordinates |
| `04_final.gds` | 306 KB | polygons |

Every step adds detail and removes meaning. `00_source.v` states `A + B == 496`
in one line. `04_final.gds` encodes the same thing in 306 KB of geometry and
states it nowhere. Reversing the flow means recovering the 1.2 KB from the
306 KB.

---

## Reading the ports off the hint image

Before any code, from `puzzle/layout.png`:

| port | direction | what it does |
|---|---|---|
| `clk` | in | clocks every sequential element |
| `rst_n` | in | active low reset |
| `enable` | in | active high enable |
| `I` | in | one serial bit per clock, the payload |
| `O[7:0]` | out | status byte |
| `success` | out | goes high when a valid input sequence has been fed in |

The image also marks one block "output generator, safe to ignore during your
initial reverse-engineering steps". That is true while working out the *rule*,
but that block is where all five of the chip's messages are held.

---

## Things I would tell myself at the start

- Spend the first day on the warm-up, not on the puzzle. It is the only place
  you can check whether your extractor is right.
- Open every provided file in a text editor once, even the binary-looking ones.
- Read the pin geometry from the LEF, never from the GDS text labels.
- When reading the gates gets hard, probe instead. The netlist can be simulated,
  so drive it and observe rather than expanding logic cones.
- When you think you know what the circuit does, generate inputs that satisfy
  your hypothesis and feed them in. If it rejects all of them, the hypothesis is
  wrong.
