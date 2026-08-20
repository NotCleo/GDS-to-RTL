# SKY130 Standard Cell Reference (`sky130_fd_sc_hd`)

- Complete cell list, name-decoding rules, and pin conventions for the SkyWater 130 nm high-density digital library, the one OpenLane / ORFS uses by default, and the one you'll see in almost every open-silicon netlist.

- Everything below is generated from `definition.json` + the functional Verilog in `google/skywater-pdk-libs-sky130_fd_sc_hd`, not from memory.
- **163 cells.**

---

## 1. Anatomy of a cell name

```
sky130_fd_sc_hd__and4b_2
└─┬──┘ └┬┘└┬┘└┬┘  └─┬─┘ └┬┘
  │     │  │  │     │    └── drive strength
  │     │  │  │     └─────── logic function
  │     │  │  └───────────── library variant
  │     │  └──────────────── cell category: standard cell
  │     └─────────────────── source: fd = foundry (SkyWater); ef = efabless; osu = OSU
  └───────────────────────── process / node
```

- The separator between library and cell is a **double** underscore.
- Everything after it is `<function><drive>`; everything inside `<function>` is a compressed grammar, not an arbitrary mnemonic: once you know the grammar you can read a cell you've never seen.

### Library variants (the `hd` field)

| Variant | Name | Row height | Use it for |
|---|---|---|---|
| `hd` | High density | 2.72 µm (9 tracks) | Default digital. What OpenLane/ORFS ships. |
| `hdll` | High density, low leakage | 2.72 µm | Same footprint as `hd`, 5 to 10x lower leakage, slower. Swap in for leakage recovery. |
| `hs` | High speed | 3.33 µm | Timing-critical blocks; bigger, leakier. |
| `ms` | Medium speed | 3.33 µm | Middle ground. |
| `ls` | Low speed | 3.33 µm | Area/power over speed. |
| `lp` | Low power | 3.33 µm | Power-gated designs. |
| `hvl` | High voltage | 5.44 µm | 3.3 V domain, level shifters, I/O interfacing. |

- `hd` and `hdll` are pin-compatible (same grid, same cell names), so a leakage-recovery ECO is a straight name swap.
- The others are **not**, because a different row height means a different floorplan.

---

## 2. Decoding the function field

### 2.1 Simple gates

```
<function><fan-in><b...>
   and       4        b     →  4-input AND, one input inverted
```

- Base function: `inv`, `buf`, `and`, `nand`, `or`, `nor`, `xor`, `xnor`, `mux`, `maj`
- Digit: number of inputs
- Each trailing `b` = one **inverted input** (`b` = "bar").
- `and4bb` = 4-input AND, two inputs inverted.

- **Gotcha, which input is inverted depends on the family:**

| Family | Cell | Pins | Inverted pin position |
|---|---|---|---|
| AND / NAND | `and4bb` | `A_N B_N C D` | **leading** pins |
| OR / NOR | `or4bb` | `A B C_N D_N` | **trailing** pins |

- The SkyWater docs say "first input inverted" for both, and that text is wrong for the OR/NOR family.
- Trust the pin names:
- **any pin ending in `_N` is the inverted one**, always.
- This bites people reverse-engineering netlists, because `nor2b` connects its complemented input to `B_N`, not `A`.

### 2.2 Compound AOI / OAI gates

- This is the grammar that makes `a221oi` readable:

```
a   22 1   o   i
│   │  │   │   └── i present → output is inverted   (Y);  absent → non-inverted (X)
│   │  │   └────── second stage: o = OR, a = AND
│   └──┴────────── fan-in of each first-stage gate, in pin-group order
└───────────────── first stage: a = AND, o = OR
```

- Read it left to right as a sentence:
- **"AND gates of width 2, 2 and 1, feeding an OR, inverted."**

```
a221oi  →  Y = !((A1 & A2) | (B1 & B2) | C1)
a22o    →  X =  ((A1 & A2) | (B1 & B2))
o21ai   →  Y = !((A1 | A2) & B1)
a2111oi →  Y = !((A1 & A2) | B1 | C1 | D1)
a31o    →  X =  ((A1 & A2 & A3) | B1)
```

- A digit of `1` means that first-stage "gate" is just a wire, a single literal straight into the second stage.
- So `a21oi` is a 2-wide AND OR'd with one plain input, then inverted.

- **Pin groups follow the digits.** First digit → `A1, A2, …`; second digit → `B1, B2, …`; then `C…`, `D…`.
- So in `a221oi`, `A1/A2` is the first AND, `B1/B2` the second, `C1` the lone literal.
- This is the single most useful fact when tracing nets by hand: the letter tells you which first-stage gate a wire lands on, and swapping `A2` for `B1` changes the logic.

- **`bb` in the middle** means "this first-stage gate takes inverted inputs":

```
a2bb2o  →  X = ((!A1_N & !A2_N) | (B1 & B2))     i.e. NOR(A1_N,A2_N) OR AND(B1,B2)
o2bb2a  →  X = (!(A1_N & A2_N) & (B1 | B2))      i.e. NAND(A1_N,A2_N) AND OR(B1,B2)
a21bo   →  X = ((A1 & A2) | !B1_N)
```

- **Why these dominate a synthesized netlist:** in CMOS, an AOI/OAI is *one* stage, a single pull-up/pull-down network, so `a22oi_1` is cheaper and faster than a separate AND + NOR.
- ABC's mapper reaches for `*oi`/`*ai` first and only emits the non-inverting `*o`/`*a` versions (which are the same gate plus an output inverter) when polarity can't be pushed elsewhere.
- If a netlist is full of `*oi` and `nand`/`nor` with very few `and`/`or`, that's normal, not a bug.

### 2.3 Output pin: `X` vs `Y`

- **`X` = non-inverting output, `Y` = inverting output.** This is a reliable tell: you can determine a cell's polarity from its pin list alone:

| | Output |
|---|---|
| `buf`, `and2`, `or3`, `a21o`, `mux2`, `xor2` | `X` |
| `inv`, `nand2`, `nor3`, `a21oi`, `mux2i`, `xnor2` | `Y` |

- Two exceptions worth memorizing:
- **`xnor3` and `xor3` both drive `X`** even though `xnor3` is an inverting function.
- Tri-state cells use `Z`.
- Flops use `Q`/`Q_N`.

### 2.4 Drive strength suffix

- `_1` is the baseline; `_2`, `_4`, `_8`, `_16` are progressively stronger output stages driving the same function.
- `_0` exists on a handful of cells (`and2_0`, `a21boi_0`, `o21ai_0`, `einvn_0`, …) and is *weaker* than `_1`, a minimum-area variant for non-critical paths.

- Rules of thumb:

- **Strength numbers are relative within a cell, not across cells.** `nand2_4` and `buf_4` do not have the same output resistance.
- Never reason about drive by comparing suffixes across functions.
- `buf`/`inv` go to `_16`; most logic stops at `_4`.
- If you see a big fan-out cone driven by combinational logic instead of a buffer, that's a real timing problem.
- Delay cells (`dlygate4sd1`, `clkdlybuf4s25`) end in a number that is **not** drive strength, it's the stage/length variant.
- `_1`/`_2` after that is the drive.
- `bufbuf` and `bufinv` only exist at `_8`/`_16`: they're two stacked stages for very high fan-out, used by CTS and fixed-cell buffering rather than by ordinary synthesis.

---

## 3. Decoding sequential cell names

- Flops and latches use a positional grammar, read left to right:

```
[s][e] df|dl  <reset>  <outputs>  <clock>
 │  │   │        │         │         └── p = positive edge / active-high enable
 │  │   │        │         │             n = negative edge / active-low enable
 │  │   │        │         └──────────── t = "true", Q only
 │  │   │        │                       b = "both", Q and Q_N
 │  │   │        └────────────────────── x = none, r = reset, s = set, bb = both
 │  │   └─────────────────────────────── df = D flip-flop, dl = D latch
 │  └─────────────────────────────────── e = enable (loopback data enable)
 └────────────────────────────────────── s = scan (adds SCD/SCE mux)
```

- So the ones from your netlist:

| Name | Decode |
|---|---|
| `dfxtp_2` | D flop, no set/reset, Q only, posedge, drive 2 |
| `dfrtp_2` | D flop, async reset, Q only, posedge |
| `dfstp_2` | D flop, async set, Q only, posedge |
| `dfbbn_1` | D flop, set **and** reset, Q + Q_N, **negedge** |
| `sdfrtp_1` | Scan flop with async reset, Q only, posedge |
| `sedfxbp_1` | Scan + data-enable flop, no set/reset, Q + Q_N, posedge |
| `dlrtn_1` | D latch, reset, Q only, active-**low** enable (`GATE_N`) |

- Three things that are true of every sequential cell in this library:

1. **Set and reset are asynchronous and active-low**, and the pins are `SET_B` / `RESET_B`.
1. There is no synchronous-reset flop in `hd`; a synchronous reset in your RTL becomes `dfxtp` plus combinational logic on `D`.
2. **There is no clock-enable flop other than `edf*`**, and `edfxtp` implements enable by *loopback* (a mux feeding D from Q).
2. Yosys usually builds enables as an explicit `mux2` + `dfxtp` instead, so `edfxtp` is rare in practice.
3. **Scan cells put the scan mux inside the cell**: `SCE=1` selects `SCD`, `SCE=0` selects `D`.
3. A netlist full of `sdfrtp` was built with a scan chain; one full of `dfrtp` was not.

- For clock gating, `dlclkp` is the integrated clock gate:
- `GCLK = CLK & (GATE latched on the low phase)`.
- Seeing `dlclkp` means the flow inserted real clock gating; `sdlclkp` is the test-observable version with a scan enable OR'd in.

---

## 4. The complete cell list

### 4.1 Buffers, inverters and simple gates

| Cell | Pins | Function | Drives |
|---|---|---|---|
| `inv` | A → Y | Y = !A | 1,2,4,6,8,12,16 |
| `buf` | A → X | X = A | 1,2,4,6,8,12,16 |
| `bufbuf` | A → X | X = A | 8,16 |
| `bufinv` | A → Y | Y = !A | 8,16 |
| `and2` | A B → X | X = A & B | 0,1,2,4 |
| `and2b` | A_N B → X | X = !A_N & B | 1,2,4 |
| `and3` | A B C → X | X = A & B & C | 1,2,4 |
| `and3b` | A_N B C → X | X = !A_N & B & C | 1,2,4 |
| `and4` | A B C D → X | X = A & B & C & D | 1,2,4 |
| `and4b` | A_N B C D → X | X = !A_N & B & C & D | 1,2,4 |
| `and4bb` | A_N B_N C D → X | X = !A_N & !B_N & C & D | 1,2,4 |
| `nand2` | A B → Y | Y = !(A & B) | 1,2,4,8 |
| `nand2b` | A_N B → Y | Y = !(!A_N & B) | 1,2,4 |
| `nand3` | A B C → Y | Y = !(A & B & C) | 1,2,4 |
| `nand3b` | A_N B C → Y | Y = !(!A_N & B & C) | 1,2,4 |
| `nand4` | A B C D → Y | Y = !(A & B & C & D) | 1,2,4 |
| `nand4b` | A_N B C D → Y | Y = !(!A_N & B & C & D) | 1,2,4 |
| `nand4bb` | A_N B_N C D → Y | Y = !(!A_N & !B_N & C & D) | 1,2,4 |
| `or2` | A B → X | X = A \| B | 0,1,2,4 |
| `or2b` | A B_N → X | X = A \| !B_N | 1,2,4 |
| `or3` | A B C → X | X = A \| B \| C | 1,2,4 |
| `or3b` | A B C_N → X | X = A \| B \| !C_N | 1,2,4 |
| `or4` | A B C D → X | X = A \| B \| C \| D | 1,2,4 |
| `or4b` | A B C D_N → X | X = A \| B \| C \| !D_N | 1,2,4 |
| `or4bb` | A B C_N D_N → X | X = A \| B \| !C_N \| !D_N | 1,2,4 |
| `nor2` | A B → Y | Y = !(A \| B) | 1,2,4,8 |
| `nor2b` | A B_N → Y | Y = !(A \| !B_N)   [= !A & B_N] | 1,2,4 |
| `nor3` | A B C → Y | Y = !(A \| B \| C) | 1,2,4 |
| `nor3b` | A B C_N → Y | Y = !(A \| B \| !C_N)   [= !(A\|B) & C_N] | 1,2,4 |
| `nor4` | A B C D → Y | Y = !(A \| B \| C \| D) | 1,2,4 |
| `nor4b` | A B C D_N → Y | Y = !(A \| B \| C \| !D_N) | 1,2,4 |
| `nor4bb` | A B C_N D_N → Y | Y = !(A \| B \| !C_N \| !D_N) | 1,2,4 |
| `xor2` | A B → X | X = A ^ B | 1,2,4 |
| `xor3` | A B C → X | X = A ^ B ^ C | 1,2,4 |
| `xnor2` | A B → Y | Y = !(A ^ B) | 1,2,4 |
| `xnor3` | A B C → X | X = !(A ^ B ^ C) | 1,2,4 |
| `maj3` | A B C → X | X = (A&B) \| (B&C) \| (A&C) | 1,2,4 |
| `mux2` | A0 A1 S → X | X = S ? A1 : A0 | 1,2,4,8 |
| `mux2i` | A0 A1 S → Y | Y = !(S ? A1 : A0) | 1,2,4 |
| `mux4` | A0 A1 A2 A3 S0 S1 → X | X = {S1,S0} select of A0..A3 | 1,2,4 |

### 4.2 AND-OR / AND-OR-Invert (`a…`)

| Cell | Pins | Function | Drives |
|---|---|---|---|
| `a21o` | A1 A2 B1 → X | X = ((A1 & A2) \| B1) | 1,2,4 |
| `a21oi` | A1 A2 B1 → Y | Y = !((A1 & A2) \| B1) | 1,2,4 |
| `a21bo` | A1 A2 B1_N → X | X = ((A1 & A2) \| (!B1_N)) | 1,2,4 |
| `a21boi` | A1 A2 B1_N → Y | Y = !((A1 & A2) \| (!B1_N)) | 0,1,2,4 |
| `a22o` | A1 A2 B1 B2 → X | X = ((A1 & A2) \| (B1 & B2)) | 1,2,4 |
| `a22oi` | A1 A2 B1 B2 → Y | Y = !((A1 & A2) \| (B1 & B2)) | 1,2,4 |
| `a2bb2o` | A1_N A2_N B1 B2 → X | X = ((!A1_N & !A2_N) \| (B1 & B2)) | 1,2,4 |
| `a2bb2oi` | A1_N A2_N B1 B2 → Y | Y = !((!A1_N & !A2_N) \| (B1 & B2)) | 1,2,4 |
| `a31o` | A1 A2 A3 B1 → X | X = ((A1 & A2 & A3) \| B1) | 1,2,4 |
| `a31oi` | A1 A2 A3 B1 → Y | Y = !((A1 & A2 & A3) \| B1) | 1,2,4 |
| `a32o` | A1 A2 A3 B1 B2 → X | X = ((A1 & A2 & A3) \| (B1 & B2)) | 1,2,4 |
| `a32oi` | A1 A2 A3 B1 B2 → Y | Y = !((A1 & A2 & A3) \| (B1 & B2)) | 1,2,4 |
| `a41o` | A1 A2 A3 A4 B1 → X | X = ((A1 & A2 & A3 & A4) \| B1) | 1,2,4 |
| `a41oi` | A1 A2 A3 A4 B1 → Y | Y = !((A1 & A2 & A3 & A4) \| B1) | 1,2,4 |
| `a211o` | A1 A2 B1 C1 → X | X = ((A1 & A2) \| B1 \| C1) | 1,2,4 |
| `a211oi` | A1 A2 B1 C1 → Y | Y = !((A1 & A2) \| B1 \| C1) | 1,2,4 |
| `a221o` | A1 A2 B1 B2 C1 → X | X = ((A1 & A2) \| (B1 & B2) \| C1) | 1,2,4 |
| `a221oi` | A1 A2 B1 B2 C1 → Y | Y = !((A1 & A2) \| (B1 & B2) \| C1) | 1,2,4 |
| `a222oi` | A1 A2 B1 B2 C1 C2 → Y | Y = !((A1 & A2) \| (B1 & B2) \| (C1 & C2)) | 1 |
| `a311o` | A1 A2 A3 B1 C1 → X | X = ((A1 & A2 & A3) \| B1 \| C1) | 1,2,4 |
| `a311oi` | A1 A2 A3 B1 C1 → Y | Y = !((A1 & A2 & A3) \| B1 \| C1) | 1,2,4 |
| `a2111o` | A1 A2 B1 C1 D1 → X | X = ((A1 & A2) \| B1 \| C1 \| D1) | 1,2,4 |
| `a2111oi` | A1 A2 B1 C1 D1 → Y | Y = !((A1 & A2) \| B1 \| C1 \| D1) | 0,1,2,4 |

### 4.3 OR-AND / OR-AND-Invert (`o…`)

| Cell | Pins | Function | Drives |
|---|---|---|---|
| `o21a` | A1 A2 B1 → X | X = ((A1 \| A2) & B1) | 1,2,4 |
| `o21ai` | A1 A2 B1 → Y | Y = !((A1 \| A2) & B1) | 0,1,2,4 |
| `o21ba` | A1 A2 B1_N → X | X = ((A1 \| A2) & !B1_N) | 1,2,4 |
| `o21bai` | A1 A2 B1_N → Y | Y = !((A1 \| A2) & !B1_N) | 1,2,4 |
| `o22a` | A1 A2 B1 B2 → X | X = ((A1 \| A2) & (B1 \| B2)) | 1,2,4 |
| `o22ai` | A1 A2 B1 B2 → Y | Y = !((A1 \| A2) & (B1 \| B2)) | 1,2,4 |
| `o2bb2a` | A1_N A2_N B1 B2 → X | X = (!(A1_N & A2_N) & (B1 \| B2)) | 1,2,4 |
| `o2bb2ai` | A1_N A2_N B1 B2 → Y | Y = !(!(A1_N & A2_N) & (B1 \| B2)) | 1,2,4 |
| `o31a` | A1 A2 A3 B1 → X | X = ((A1 \| A2 \| A3) & B1) | 1,2,4 |
| `o31ai` | A1 A2 A3 B1 → Y | Y = !((A1 \| A2 \| A3) & B1) | 1,2,4 |
| `o32a` | A1 A2 A3 B1 B2 → X | X = ((A1 \| A2 \| A3) & (B1 \| B2)) | 1,2,4 |
| `o32ai` | A1 A2 A3 B1 B2 → Y | Y = !((A1 \| A2 \| A3) & (B1 \| B2)) | 1,2,4 |
| `o41a` | A1 A2 A3 A4 B1 → X | X = ((A1 \| A2 \| A3 \| A4) & B1) | 1,2,4 |
| `o41ai` | A1 A2 A3 A4 B1 → Y | Y = !((A1 \| A2 \| A3 \| A4) & B1) | 1,2,4 |
| `o211a` | A1 A2 B1 C1 → X | X = ((A1 \| A2) & B1 & C1) | 1,2,4 |
| `o211ai` | A1 A2 B1 C1 → Y | Y = !((A1 \| A2) & B1 & C1) | 1,2,4 |
| `o221a` | A1 A2 B1 B2 C1 → X | X = ((A1 \| A2) & (B1 \| B2) & C1) | 1,2,4 |
| `o221ai` | A1 A2 B1 B2 C1 → Y | Y = !((A1 \| A2) & (B1 \| B2) & C1) | 1,2,4 |
| `o311a` | A1 A2 A3 B1 C1 → X | X = ((A1 \| A2 \| A3) & B1 & C1) | 1,2,4 |
| `o311ai` | A1 A2 A3 B1 C1 → Y | Y = !((A1 \| A2 \| A3) & B1 & C1) | 0,1,2,4 |
| `o2111a` | A1 A2 B1 C1 D1 → X | X = ((A1 \| A2) & B1 & C1 & D1) | 1,2,4 |
| `o2111ai` | A1 A2 B1 C1 D1 → Y | Y = !((A1 \| A2) & B1 & C1 & D1) | 1,2,4 |

### 4.4 Arithmetic

| Cell | Pins | Function | Drives |
|---|---|---|---|
| `ha` | A B → COUT SUM | {COUT,SUM} = A + B | 1,2,4 |
| `fa` | A B CIN → COUT SUM | {COUT,SUM} = A + B + CIN | 1,2,4 |
| `fah` | A B CI → COUT SUM | {COUT,SUM} = A + B + CI | 1 |
| `fahcin` | A B CIN → COUT SUM | {COUT,SUM} = A + B + !CIN | 1 |
| `fahcon` | A B CI → COUT_N SUM | COUT_N = !carry, SUM = A^B^CI | 1 |

- `fah` is the "high-speed" full adder (a plain XOR3 + majority tree) versus `fa`'s factored implementation; `fahcin`/`fahcon` invert the carry in / carry out so a ripple chain can alternate polarity and skip the inverter between stages.
- Classic carry-chain trick, if you see alternating `fahcin`/`fahcon`, that's a hand-built or datapath-compiled adder, not something Yosys produced.

### 4.5 Flip-flops

| Cell | Pins | Meaning | Drives |
|---|---|---|---|
| `dfxtp` | CLK D → Q | Delay flop, single output | 1,2,4 |
| `dfxbp` | CLK D → Q Q_N | Delay flop, complementary outputs | 1,2 |
| `dfrtp` | CLK D RESET_B → Q | Delay flop, inverted reset, single output | 1,2,4 |
| `dfrtn` | CLK_N D RESET_B → Q | Delay flop, inverted reset, inverted clock, complementary outputs | 1 |
| `dfrbp` | CLK D RESET_B → Q Q_N | Delay flop, inverted reset, complementary outputs | 1,2 |
| `dfstp` | CLK D SET_B → Q | Delay flop, inverted set, single output | 1,2,4 |
| `dfsbp` | CLK D SET_B → Q Q_N | Delay flop, inverted set, complementary outputs | 1,2 |
| `dfbbp` | D CLK SET_B RESET_B → Q Q_N | Delay flop, inverted set, inverted reset, complementary outputs | 1 |
| `dfbbn` | D CLK_N SET_B RESET_B → Q Q_N | Delay flop, inverted set, inverted reset, inverted clock, complementary outputs | 1,2 |
| `edfxtp` | CLK D DE → Q | Delay flop with loopback enable, non-inverted clock, single output | 1 |
| `edfxbp` | CLK D DE → Q Q_N | Delay flop with loopback enable, non-inverted clock, complementary outputs | 1 |

### 4.6 Scan flip-flops

| Cell | Pins | Meaning | Drives |
|---|---|---|---|
| `sdfxtp` | CLK D SCD SCE → Q | Scan delay flop, non-inverted clock, single output | 1,2,4 |
| `sdfxbp` | CLK D SCD SCE → Q Q_N | Scan delay flop, non-inverted clock, complementary outputs | 1,2 |
| `sdfrtp` | CLK D SCD SCE RESET_B → Q | Scan delay flop, inverted reset, non-inverted clock, single output | 1,2,4 |
| `sdfrtn` | CLK_N D SCD SCE RESET_B → Q | Scan delay flop, inverted reset, inverted clock, single output | 1 |
| `sdfrbp` | CLK D SCD SCE RESET_B → Q Q_N | Scan delay flop, inverted reset, non-inverted clock, complementary outputs | 1,2 |
| `sdfstp` | CLK D SCD SCE SET_B → Q | Scan delay flop, inverted set, non-inverted clock, single output | 1,2,4 |
| `sdfsbp` | CLK D SCD SCE SET_B → Q Q_N | Scan delay flop, inverted set, non-inverted clock, complementary outputs | 1,2 |
| `sdfbbp` | D SCD SCE CLK SET_B RESET_B → Q Q_N | Scan delay flop, inverted set, inverted reset, non-inverted clock, complementary outputs | 1 |
| `sdfbbn` | D SCD SCE CLK_N SET_B RESET_B → Q Q_N | Scan delay flop, inverted set, inverted reset, inverted clock, complementary outputs | 1,2 |
| `sedfxtp` | CLK D DE SCD SCE → Q | Scan delay flop, data enable, non-inverted clock, single output | 1,2,4 |
| `sedfxbp` | CLK D DE SCD SCE → Q Q_N | Scan delay flop, data enable, non-inverted clock, complementary outputs | 1,2 |

### 4.7 Latches

| Cell | Pins | Meaning | Drives |
|---|---|---|---|
| `dlxtp` | D GATE → Q | Delay latch, non-inverted enable, single output | 1 |
| `dlxtn` | D GATE_N → Q | Delay latch, inverted enable, single output | 1,2,4 |
| `dlxbp` | D GATE → Q Q_N | Delay latch, non-inverted enable, complementary outputs | 1 |
| `dlxbn` | D GATE_N → Q Q_N | Delay latch, inverted enable, complementary outputs | 1,2 |
| `dlrtp` | RESET_B D GATE → Q | Delay latch, inverted reset, non-inverted enable, single output | 1,2,4 |
| `dlrtn` | RESET_B D GATE_N → Q | Delay latch, inverted reset, inverted enable, single output | 1,2,4 |
| `dlrbp` | RESET_B D GATE → Q Q_N | Delay latch, inverted reset, non-inverted enable, complementary outputs | 1,2 |
| `dlrbn` | RESET_B D GATE_N → Q Q_N | Delay latch, inverted reset, inverted enable, complementary outputs | 1,2 |

### 4.8 Clock, delay and clock-gating cells

| Cell | Pins | Meaning | Drives |
|---|---|---|---|
| `clkbuf` | A → X | Clock tree buffer | 1,2,4,8,16 |
| `clkinv` | A → Y | Clock tree inverter | 1,2,4,8,16 |
| `clkinvlp` | A → Y | Lower power Clock tree inverter | 2,4 |
| `dlclkp` | GATE CLK → GCLK | Clock gate | 1,2,4 |
| `sdlclkp` | SCE GATE CLK → GCLK | Scan gated clock | 1,2,4 |
| `clkdlybuf4s15` | A → X | Clock Delay Buffer 4-stage 0.15um length inner stage gates | 1,2 |
| `clkdlybuf4s18` | A → X | Clock Delay Buffer 4-stage 0.18um length inner stage gates | 1,2 |
| `clkdlybuf4s25` | A → X | Clock Delay Buffer 4-stage 0.25um length inner stage gates | 1,2 |
| `clkdlybuf4s50` | A → X | Clock Delay Buffer 4-stage 0.59um length inner stage gates | 1,2 |
| `dlygate4sd1` | A → X | Delay Buffer 4-stage 0.15um length inner stage gates | 1 |
| `dlygate4sd2` | A → X | Delay Buffer 4-stage 0.18um length inner stage gates | 1 |
| `dlygate4sd3` | A → X | Delay Buffer 4-stage 0.50um length inner stage gates | 1 |
| `dlymetal6s2s` | A → X | 6-inverter delay with output from 2nd stage on horizontal route | 1 |
| `dlymetal6s4s` | A → X | 6-inverter delay with output from 4th inverter on horizontal route | 1 |
| `dlymetal6s6s` | A → X | 6-inverter delay with output from 6th inverter on horizontal route | 1 |

### 4.9 Tri-state

| Cell | Pins | Function | Drives |
|---|---|---|---|
| `einvn` | A TE_B → Z | Z = TE_B ? 1'bz : !A | 0,1,2,4,8 |
| `einvp` | A TE → Z | Z = TE ? !A : 1'bz | 1,2,4,8 |
| `ebufn` | A TE_B → Z | Z = TE_B ? 1'bz : A | 1,2,4,8 |

### 4.10 Physical-only cells (no logic function)

| Cell | Pins | Meaning | Drives |
|---|---|---|---|
| `fill` |  →  | Fill cell | 1,2,4,8 |
| `decap` |  →  | Decoupling capacitance filler | 3,4,6,8,12 |
| `tap` |  →  | Tap cell with no tap connections (no contacts on metal1) | 1,2 |
| `tapvgnd` |  →  | Tap cell with tap to ground, isolated power connection 1 row down | 1 |
| `tapvgnd2` |  →  | Tap cell with tap to ground, isolated power connection 2 rows down | 1 |
| `tapvpwrvgnd` |  →  | Substrate and well tap cell | 1 |
| `diode` | DIODE →  | Antenna tie-down diode | 2 |
| `conb` |  → HI LO | Constant value, low, high outputs | 1 |
| `macro_sparecell` |  → LO | Macro cell for metal-mask-only revisioning, containing inverter, 2-input NOR, 2-input NAND, and constant cell | none |
| `probe_p` | A → X | Virtual voltage probe point | 8 |
| `probec_p` | A → X | Virtual current probe point | 8 |

- These carry no function and should be **stripped before any logical analysis**, because they exist for DRC, density, latch-up and antenna reasons only:

- `fill`, `decap` : fill the row, add on-die decoupling capacitance
- `tap`, `tapvgnd`, `tapvpwrvgnd` : substrate/well ties, placed on a fixed pitch to prevent latch-up
- `diode` : antenna diode, tied to a net to bleed charge during plasma etch
- `conb` : the **tie cell**: `HI` = logic 1, `LO` = logic 0.
- Every constant in your netlist comes from here, not from a direct connection to `VPWR`/`VGND`
- `macro_sparecell` : spare gates for metal-only ECO
- `probe_p`, `probec_p` : virtual probe points, no physical devices

### 4.11 Low-power flow cells (`lpflow_*`)

| Cell | Pins | Meaning | Drives |
|---|---|---|---|
| `lpflow_bleeder` | SHORT →  | Current bleeder (weak pulldown to ground) | 1 |
| `lpflow_clkbufkapwr` | A → X | Clock tree buffer on keep-alive power rail | 1,2,4,8,16 |
| `lpflow_clkinvkapwr` | A → Y | Clock tree inverter on keep-alive rail | 1,2,4,8,16 |
| `lpflow_decapkapwr` |  →  | Decoupling capacitance filler on keep-alive rail | 3,4,6,8,12 |
| `lpflow_inputiso0n` | A SLEEP_B → X | Input isolator with inverted enable | 1 |
| `lpflow_inputiso0p` | A SLEEP → X | Input isolator with non-inverted enable | 1 |
| `lpflow_inputiso1n` | A SLEEP_B → X | Input isolation, inverted sleep | 1 |
| `lpflow_inputiso1p` | A SLEEP → X | Input isolation, noninverted sleep | 1 |
| `lpflow_inputisolatch` | D SLEEP_B → Q | Latching input isolator with inverted enable | 1 |
| `lpflow_isobufsrc` | SLEEP A → X | Input isolation, noninverted sleep | 1,2,4,8,16 |
| `lpflow_isobufsrckapwr` | SLEEP A → X | Input isolation, noninverted sleep on keep-alive power rail | 16 |
| `lpflow_lsbuf_lh_isowell` | A → X | Level-shift buffer, low-to-high, isolated well on input buffer, no taps, double-row-height cell | 4 |
| `lpflow_lsbuf_lh_isowell_tap` | A → X | Level-shift buffer, low-to-high, isolated well on input buffer, vpb/vnb taps, double-row-height cell | 1,2,4 |
| `lpflow_lsbuf_lh_hl_isowell_tap` | A → X | Level-shift buffer, low-to-high, isolated well on input buffer, vpb/vnb taps, double-row-height cell | 1,2,4 |

- Only relevant if the design uses power gating: isolation cells clamp a signal crossing from a gated domain, `kapwr` cells sit on the always-on keep-alive rail, and `lsbuf` are level shifters (double-row-height, so they break normal row placement).

---

## 5. Every cell has the same power pins

```verilog
sky130_fd_sc_hd__and2_2 u1 (.A(a), .B(b), .X(y),
                            .VPWR(VPWR), .VGND(VGND),  // supply
                            .VPB(VPWR),  .VNB(VGND));  // p-well / n-well body ties
```

- `VPB`/`VNB` are the body/well connections.
- Netlists come in two flavours: the plain `.v` blackbox (no power pins) and the `.pp.v` "power-pins" version.
- LVS needs the `.pp` form; gate-level simulation usually uses the plain one.
- If a netlist you extracted from GDS has `VPB`/`VNB` dangling, that's expected: they are tied through the well, not through routing.

---

## 6. Reading a netlist: practical rules of thumb

- **Get a histogram first.** Cell mix tells you what the design is before you read a single net:

```bash
grep -oP 'sky130_fd_sc_hd__\K[a-z0-9_]+(?=_\d+\s)' netlist.v \
  | sed 's/_[0-9]*$//' | sort | uniq -c | sort -rn
```

- Interpreting it:

| Signal | What it means |
|---|---|
| Many `dfrtp`, few `dfxtp` | Most registers have async reset, so a reset-dominant control design |
| `dfxtp` only | Datapath / pipeline, reset handled in logic or not at all |
| Lots of `sdf*` | Scan-inserted; the `SCD` pins form the chain, so follow them to recover the flop order |
| Heavy `mux2` + `dfxtp` pairs | Clock-enable flops built by Yosys, not `edfxtp` |
| Long `clkbuf_8`/`clkbuf_16` chains | CTS output; these are the clock tree, skip them when tracing datapath |
| `conb_1` | Tie cells, the source of every constant. Resolve them first |
| Lots of `a*oi`/`o*ai`, few `and`/`or` | Normal ABC mapping; don't read polarity into it |

- **Then normalize polarity.** Before trying to understand a cone, push all the inversion into a canonical form: read the netlist into Yosys, `techmap` away the library cells, then `aigmap` or `abc -g AND`.
- The `*oi`/`*ai` cells hide the structure; an AIG makes repeated subcircuits (adders, comparators, shift registers) visible.

- **Watch the `_N` pins.** A wire landing on `A_N`, `B1_N`, `RESET_B` or `SET_B` is used complemented.
- Half of all "my recovered logic is inverted" bugs come from treating `nor2b`'s `B_N` like an ordinary input.

- **Flop count is your best structural hint.** 92 flops in a design with an 8-bit output almost certainly means a shift register or a state machine with a wide datapath, not 92 independent registers: cluster the flops by which nets feed their `D` pins, and serial chains fall out immediately.

- **Ignore the fillers.** `fill`, `decap`, `tap*`, `diode` and `probe*` should be deleted from any extracted netlist before analysis.
- They inflate instance counts and connect to nothing logical.

---

## 7. Regenerating this yourself

- The library is self-documenting: every cell ships a `definition.json` with its description, equation and port list:

```bash
git clone --depth 1 --filter=blob:none --no-checkout \
  https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd.git
cd skywater-pdk-libs-sky130_fd_sc_hd
git sparse-checkout set --no-cone '/cells/*/definition.json'
git checkout
jq -r '[.name, .description, .equation] | @tsv' cells/*/definition.json
```

- Two caveats: a handful of `equation` fields upstream are wrong (`nor2b`, `nor3`, `nor3b`, `lpflow_isobufsrc` among them, where the equations do not match the pin lists).
- The `*.functional.v` file in each cell directory is the authoritative source; the tables above were corrected against it.

- For timing/area rather than function, read the `.lib` (Liberty) files from `open_pdks` / `volare`.
- `sky130_fd_sc_hd__tt_025C_1v80.lib` is the typical corner.
