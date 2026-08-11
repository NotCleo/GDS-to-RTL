#!/usr/bin/env python3
"""
Put the recovered logical blocks back onto the die, and render the floorplan.

The blog says "the circuit is physically arranged to hint at its functionality".
Reading that hint by eye in a GDS viewer is hard: it is 1618 placements and
nothing is labelled. But once the netlist is extracted and the counters are
identified, mapping a cell back to a coordinate is trivial -- the extractor's
instance index `uNNN` is its position in the GDS reference list, so uNNN -> (x,y)
is a lookup.

What comes out is the hint, in full: two stacks of eleven identical 2-bit
counter slices in one narrow vertical column, plus one more counter off to the
side. 11 + 11 + 1 is the architecture (column checks, region checks, and the
single shared row counter) read straight off the floorplan.

Usage: python 19_floorplan.py <puzzle.gds> <regions.json> [outdir]
"""
import sys, os, json, collections
import gdstk

PREFIX = "sky130_fd_sc_hd__"
PHYSICAL = ("decap", "fill", "tapvpwrvgnd")


def index_instances(gds):
    """Reproduce 02_extract_netlist.py's instance numbering: enumerate the top
    cell's references in file order, skipping vias, decoration and fillers."""
    top = gdstk.read_gds(gds).top_level()[0]
    out, i = {}, 0
    for ref in top.references:
        n = ref.cell.name
        if not n.startswith(PREFIX):
            continue
        if n[len(PREFIX):].startswith(PHYSICAL):
            continue
        out[i] = (n[len(PREFIX):], ref.origin[0], ref.origin[1])
        i += 1
    return out


def main():
    gds, regions = sys.argv[1], sys.argv[2]
    outdir = sys.argv[3] if len(sys.argv) > 3 else None
    idx = index_instances(gds)
    reg = json.load(open(regions))
    watches = {int(k): v for k, v in reg["watches"].items()}

    def kind(cells):
        if not cells:
            return "ROW"
        s = sorted(cells)
        return "COL" if len(s) == 11 and all(b - a == 11
                                             for a, b in zip(s, s[1:])) else "REG"

    top0 = gdstk.read_gds(gds).top_level()[0]
    bb0 = top0.bounding_box()
    W_DIE = bb0[1][0] - bb0[0][0]

    pos = lambda nm: idx.get(int(nm.split("_")[0][1:]))
    rows = []
    for slot, (a, b) in enumerate(reg["pairs"]):
        pa, pb = pos(a), pos(b)
        if pa is None or pb is None:
            continue
        cells = watches.get(slot) or []
        rows.append((0, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2, kind(cells),
                     f"{a}+{b}", len(cells)))

    L = ["FLOORPLAN OF THE RECOVERED BLOCKS", "=" * 64, "",
         f"die: {gdstk.read_gds(gds).top_level()[0].bounding_box()}", "",
         "counter pairs, sorted bottom-to-top:",
         f"  {'x (um)':>8} {'y (um)':>8}  kind  cells  instances"]
    for _, x, y, k, nm, n in sorted(rows, key=lambda r: r[2]):
        L.append(f"  {x:8.2f} {y:8.2f}  {k:4s}  {n:5d}  {nm}")

    stack = [r for r in rows if r[3] != "ROW"]
    xs = [r[1] for r in stack]
    cy = [r[2] for r in stack if r[3] == "COL"]
    ry = [r[2] for r in stack if r[3] == "REG"]
    L += ["", f"counter column occupies x = {min(xs):.1f} .. {max(xs):.1f} um "
              f"of a {W_DIE:.0f} um wide die",
          f"  {len(cy):2d} COL slices at y = {min(cy):.1f} .. {max(cy):.1f}",
          f"  {len(ry):2d} REG slices at y = {min(ry):.1f} .. {max(ry):.1f}",
          f"   1 ROW slice  off to the side at x = "
          f"{[r[1] for r in rows if r[3]=='ROW'][0]:.1f}",
          "",
          "The checker is one vertical stack of identical 2-bit slices, split into",
          "a column-checking half and a region-checking half with a visible gap",
          f"between them (y {max(ry):.0f} -> {min(cy):.0f}). Counting slices gives",
          "11 + 11 + 1 -- the whole architecture, before a single gate is read.",
          "",
          "region-counter watch-set sizes (bottom to top) = the region sizes:",
          "  " + " ".join(str(r[5]) for r in sorted(
              [x for x in rows if x[3] == "REG"], key=lambda r: r[2])) +
          f"   sum = {sum(r[5] for r in rows if r[3] == 'REG')}", ""]

    top = gdstk.read_gds(gds).top_level()[0]
    bb = top.bounding_box()
    W, H = bb[1][0] - bb[0][0], bb[1][1] - bb[0][1]
    NX, NY = 50, 40
    g = collections.Counter()
    for _, x, y in idx.values():
        g[(min(int((x - bb[0][0]) / W * NX), NX - 1),
           min(int((y - bb[0][1]) / H * NY), NY - 1))] += 1
    mark = {(min(int((r[1] - bb[0][0]) / W * NX), NX - 1),
             min(int((r[2] - bb[0][1]) / H * NY), NY - 1)) for r in rows}
    L += ["logic-cell density (C = a recovered counter slice sits here):"]
    ramp = " .:-=+*#%@"
    for j in range(NY - 1, -1, -1):
        L.append("  " + "".join("C" if (i, j) in mark else ramp[min(g[(i, j)], 9)]
                                for i in range(NX)))

    txt = "\n".join(L)
    print(txt)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        open(os.path.join(outdir, "floorplan.txt"), "w").write(txt + "\n")
        print(f"\nwrote {outdir}/floorplan.txt")


if __name__ == "__main__":
    main()
