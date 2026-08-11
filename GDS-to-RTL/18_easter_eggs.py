#!/usr/bin/env python3
"""
Sweep puzzle.gds for things that are NOT part of the circuit, and decode them.

Rationale: a GDS contains exactly the layers a foundry needs. Anything on a
layer the PDK does not define, or any structure that is neither a standard cell
nor a via, is there because a human put it there on purpose. That is a very
short list, and it is worth reading.

Three finds, none of which need you to know what you are looking for:

  * layer 200/0, not a sky130 mask layer at all. 36 bars of two widths in a
    strip below the die, gaps in exact 1/3/7 ratios: International Morse. The
    bars are the cells INTERNAL_3 (narrow) and INTERNAL_7 (wide), which is why
    they also show up as the only non-cell, non-via structures in the file.
  * a block of ~1366 sub-micron met2 polygons packed into a 17 um square, which
    is artwork rather than routing. Present in the warm-up too.
  * the layer diff against a design that went through the same flow. Layers
    present in one and not the other are either hand-added or a side effect of
    using a cell the other design does not use, and those are separated here.
    Only 200/0 is genuinely hand-added; 66/15 and 81/23 come from conb_1 and
    diode_2, which the warm-up has no instances of.

Usage: python 18_easter_eggs.py <puzzle.gds> [outdir] [reference.gds]
"""
import sys, os, collections
import gdstk

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
}

KNOWN = {(64, 20), (65, 20), (66, 20), (67, 20), (68, 20), (69, 20), (70, 20),
         (71, 20), (72, 20), (67, 44), (68, 44), (69, 44), (70, 44), (71, 44),
         (67, 5), (68, 5), (69, 5), (70, 5), (71, 5), (72, 5),
         (68, 16), (69, 16), (70, 16), (71, 16), (72, 16),
         (64, 16), (65, 16), (66, 16), (81, 4), (235, 4)}


def decode_morse_row(bars, unit):
    """bars = [(x_left, width)] sorted. Return the decoded text."""
    out, sym = [], ""
    prev_end = None
    for x, w in bars:
        if prev_end is not None:
            gap = round((x - prev_end) / unit)
            if gap >= 7:
                out.append(MORSE.get(sym, "?")); out.append(" "); sym = ""
            elif gap >= 3:
                out.append(MORSE.get(sym, "?")); sym = ""
        sym += "-" if round(w / unit) >= 3 else "."
        prev_end = x + w
    if sym:
        out.append(MORSE.get(sym, "?"))
    return "".join(out)


def layer_hist(path):
    h = collections.Counter()
    for c in gdstk.read_gds(path).cells:
        for p in c.polygons:
            h[(p.layer, p.datatype)] += 1
    return h


def main():
    gds = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else None
    ref = sys.argv[3] if len(sys.argv) > 3 else None
    lib = gdstk.read_gds(gds)
    top = lib.top_level()[0]
    L = [f"EASTER-EGG SWEEP of {gds}", "=" * 60, ""]

    hist = collections.Counter()
    for c in lib.cells:
        for p in c.polygons:
            hist[(p.layer, p.datatype)] += 1
    L.append("layers carrying geometry (whole library, cells included):")
    for k in sorted(hist):
        tag = "" if k in KNOWN else "   <-- NOT A SKY130 MASK LAYER"
        L.append(f"   {k[0]:3d}/{k[1]:<3d}  {hist[k]:6d} polygons{tag}")
    L.append("")

    odd = sorted({r.cell.name for r in top.references
                  if not r.cell.name.startswith(("sky130_fd_sc_hd__", "VIA_"))})
    L.append(f"non-standard-cell, non-via structures: {odd}")
    L.append("")

    if ref:
        rh = layer_hist(ref)
        in_stdcell, elsewhere = set(), set()
        for c in lib.cells:
            bucket = in_stdcell if c.name.startswith("sky130_fd_sc_hd__") else elsewhere
            for p in c.polygons:
                bucket.add((p.layer, p.datatype))
        L.append(f"layers in {gds} but not in {ref}:")
        for k in sorted(set(hist) - set(rh)):
            why = ("hand-added" if k in elsewhere
                   else "only inside standard cells -> cell-library difference")
            L.append(f"   {k[0]:3d}/{k[1]:<3d}  {hist[k]:6d} polygons   {why}")
        L.append(f"layers in {ref} but not in {gds}: "
                 f"{sorted(set(rh) - set(hist)) or 'none'}")
        L.append("")

    for lay in sorted({(p.layer, p.datatype) for p in top.polygons}):
        boxes = [p.bounding_box() for p in top.polygons
                 if (p.layer, p.datatype) == lay]
        tiny = [b for b in boxes
                if b[1][0] - b[0][0] < 1.0 and b[1][1] - b[0][1] < 1.0]
        if len(tiny) < 100:
            continue
        x0 = min(b[0][0] for b in tiny); x1 = max(b[1][0] for b in tiny)
        y0 = min(b[0][1] for b in tiny); y1 = max(b[1][1] for b in tiny)
        L.append(f"drawn artwork on layer {lay[0]}/{lay[1]}: {len(tiny)} polygons "
                 f"packed into {x1-x0:.2f} x {y1-y0:.2f} um "
                 f"at ({x0:.2f}, {y0:.2f}) .. ({x1:.2f}, {y1:.2f})")
        W, H = 64, 32
        grid = [[" "] * W for _ in range(H)]
        for b in tiny:
            for gx in range(int((b[0][0]-x0)/(x1-x0)*(W-1)),
                            int((b[1][0]-x0)/(x1-x0)*(W-1)) + 1):
                for gy in range(int((b[0][1]-y0)/(y1-y0)*(H-1)),
                                int((b[1][1]-y0)/(y1-y0)*(H-1)) + 1):
                    grid[gy][gx] = "#"
        for r in reversed(grid):
            L.append("  " + "".join(r))
        L.append("")

    bars = []
    for r in top.references:
        if not r.cell.name.startswith("INTERNAL_"):
            continue
        p = r.cell.polygons[0]
        bb = p.bounding_box()
        bars.append((round(r.origin[1], 3), round(r.origin[0] + bb[0][0], 3),
                     round(bb[1][0] - bb[0][0], 3)))
    if bars:
        unit = min(w for _, _, w in bars)
        L.append(f"bar strip: {len(bars)} bars, narrow(unit) = {unit} um, "
                 f"wide = {max(w for _,_,w in bars)} um "
                 f"({round(max(w for _,_,w in bars)/unit)} units)")
        for y in sorted({b[0] for b in bars}):
            row = sorted([(x, w) for yy, x, w in bars if yy == y])
            gaps = [round((row[i + 1][0] - (row[i][0] + row[i][1])) / unit)
                    for i in range(len(row) - 1)]
            L.append(f"  y = {y} um  (below the die -> cosmetic, not routed)")
            L.append("  widths  : " + " ".join(
                "-" if round(w / unit) >= 3 else "." for _, w in row))
            L.append("  gaps    : " + " ".join(str(g) for g in gaps) +
                     "   (1 = intra-letter, 3 = letter, 7 = word)")
            msg = decode_morse_row(row, unit)
            L.append(f"  MORSE   : {msg}")
            L.append("")

    txt = "\n".join(L)
    print(txt)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        open(os.path.join(outdir, "easter_eggs.txt"), "w").write(txt + "\n")
        print(f"wrote {outdir}/easter_eggs.txt")


if __name__ == "__main__":
    main()
