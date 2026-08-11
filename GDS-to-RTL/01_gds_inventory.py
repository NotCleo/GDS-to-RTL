#!/usr/bin/env python3
"""
Step 1 of GDS reverse engineering: INVENTORY.

A GDS file is just a bag of "structures" (cells). Each structure contains:
  - polygons/paths on (layer, datatype) pairs  -> the actual mask geometry
  - SREF/AREF records                          -> placements of other structures
  - TEXT records (labels)                      -> the only human-readable names left

The crucial trick: physical-design flows stream each standard cell in as its own
GDS structure, and the *structure names* (sky130_fd_sc_hd__nand2_2, ...) are kept,
because the foundry layout of each cell type is identical everywhere it is used.
So we get the full "placement list" (like a DEF COMPONENTS section) for free:
    for every instance: cell type + (x, y) + orientation.
What the GDS does NOT keep: instance names, net names, module hierarchy.

Usage:  python 01_gds_inventory.py <file.gds> <outdir>
Writes: <outdir>/instances.csv, <outdir>/labels.csv, prints a summary.
"""
import sys, csv, collections, os
import gdstk

PHYS_PREFIXES = ("decap", "fill", "tapvpwrvgnd", "tap_", "diode", "conb")

def is_physical_only(cellname: str) -> bool:
    short = cellname.split("__")[-1]
    return short.startswith(PHYS_PREFIXES)

def orient_name(rotation_deg: int, x_reflection: bool) -> str:
    """Map GDS (rotation, mirror) to DEF orientation letters.
    GDS applies: mirror about X axis first, then rotate CCW, then translate.
    DEF N=R0, S=R180, FN=mirrored-then-R180?  Convention used by streamers:
      N  = rot 0,   no mirror
      S  = rot 180, no mirror
      FN = rot 180, mirror   (flip about Y axis)
      FS = rot 0,   mirror   (flip about X axis)
    Standard-cell rows alternate N / FS so that power rails abut & share.
    """
    r = int(round(rotation_deg)) % 360
    key = (r, bool(x_reflection))
    return {(0, False): "N", (180, False): "S", (180, True): "FN", (0, True): "FS",
            (90, False): "W", (270, False): "E", (90, True): "FW", (270, True): "FE"}.get(key, f"rot{r}{'M' if x_reflection else ''}")

def main(gds_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    lib = gdstk.read_gds(gds_path)
    print(f"== GDS library: '{lib.name}'  unit={lib.unit} m  precision={lib.precision} m")
    print(f"== structures (cells) defined in file: {len(lib.cells)}")

    tops = lib.top_level()
    print(f"== top-level structure(s): {[c.name for c in tops]}")
    top = tops[0]

    bb = top.bounding_box()
    print(f"== top cell '{top.name}' bounding box: {bb[0]} .. {bb[1]}  (micron)")

    counts = collections.Counter()
    rows = []
    for ref in top.references:
        name = ref.cell.name if hasattr(ref.cell, "name") else str(ref.cell)
        n = 1
        if ref.repetition is not None and ref.repetition.size:
            n = ref.repetition.size
        counts[name] += n
        rows.append((name, round(ref.origin[0], 4), round(ref.origin[1], 4),
                     orient_name(round(ref.rotation * 180 / 3.141592653589793), ref.x_reflection)))
    rows.sort(key=lambda r: (r[2], r[1]))

    with open(f"{outdir}/instances.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["cell", "x_um", "y_um", "orient"]); w.writerows(rows)

    logic = {k: v for k, v in counts.items() if not is_physical_only(k)}
    phys  = {k: v for k, v in counts.items() if is_physical_only(k)}
    print(f"\n== instance count: total={sum(counts.values())}  logic={sum(logic.values())}  physical-only={sum(phys.values())}")
    print("\n-- LOGIC cells (these ARE the netlist content):")
    for k, v in sorted(logic.items(), key=lambda kv: -kv[1]):
        print(f"   {v:4d} x {k}")
    print("\n-- PHYSICAL-ONLY cells (ignore for function):")
    for k, v in sorted(phys.items(), key=lambda kv: -kv[1]):
        print(f"   {v:4d} x {k}")

    with open(f"{outdir}/labels.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scope", "text", "layer", "texttype", "x_um", "y_um"])
        print("\n-- TEXT labels in top cell (surviving names = your I/O ports):")
        for lab in top.labels:
            print(f"   '{lab.text}'  layer {lab.layer}/{lab.texttype}  at ({lab.origin[0]:.2f}, {lab.origin[1]:.2f})")
            w.writerow(["TOP", lab.text, lab.layer, lab.texttype, lab.origin[0], lab.origin[1]])
        seen = set()
        example_shown = 0
        for ref in top.references:
            c = ref.cell
            if c.name in seen: continue
            seen.add(c.name)
            for lab in c.labels:
                w.writerow([c.name, lab.text, lab.layer, lab.texttype, lab.origin[0], lab.origin[1]])
                example_shown += 1
        print(f"\n-- labels inside std-cell definitions: {example_shown} rows -> labels.csv")
        if example_shown:
            some = sorted(seen)[:1]
            for cn in some:
                c = next(c for c in lib.cells if c.name == cn)
                print(f"   example, pins of {cn}: {[(l.text, l.layer, l.texttype) for l in c.labels]}")

    lcount = collections.Counter()
    for p in top.polygons: lcount[(p.layer, p.datatype)] += 1
    for p in top.paths:    lcount[(p.layers[0], p.datatypes[0])] += 1
    print("\n-- geometry drawn directly in the top cell (this is inter-cell ROUTING + PDN + pins):")
    for (l, d), v in sorted(lcount.items()):
        print(f"   layer {l:3d}/{d:<3d} : {v:5d} shapes")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out")
