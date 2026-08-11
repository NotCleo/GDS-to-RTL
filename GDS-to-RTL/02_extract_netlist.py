#!/usr/bin/env python3
"""
Step 2 of GDS reverse engineering: NETLIST EXTRACTION (the core step).

Idea: a "net" (wire in the netlist) is nothing more than a set of metal shapes
that physically touch, across layers, through vias. So:

  1. For every standard-cell TYPE, find its pin shapes:
     the PDK cell layouts carry text labels (e.g. 'A', 'X', 'CLK') on the
     li1-label layer 67/5; the li1 drawing polygon (67/20) under the label
     is the pin's landing shape.
  2. For every INSTANCE, geometrically transform those pin shapes to die
     coordinates (translate + rotate + mirror, from the GDS reference).
  3. Throw every conductor shape into per-layer "soups":
       li1(67) - met1(68) - met2(69) - met3(70) - met4(71) - met5(72)
     Soup contents: top-level routing wires, via-cell landing pads, std-cell
     internal li1/met1 islands (incl. the pin shapes).
  4. unary_union each layer's soup -> merged islands. Two shapes touching on
     the same layer = same electrical node.
  5. Every via instance connects one island on its lower layer to one island
     on its upper layer -> union-find across layers.
  6. Each resulting connected component = one net. Attach:
       - (instance, pin_name) for every pin shape inside it
       - a port name if a top-level label (A/B/S/clk/en/rst_n...) sits on it
  7. Sanity-check (every pin netted, exactly one driver per net), then write
     a structural Verilog netlist.

Usage: python 02_extract_netlist.py <file.gds> <outdir>
"""
import sys, os, json, math, collections, re
import gdstk
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely import affinity

ROUTE_LAYERS = [67, 68, 69, 70, 71, 72]
LNAME = {67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4", 72: "met5"}
OUTPUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO"}
POWER_PINS = {"VPWR", "VGND", "VPB", "VNB"}
LEF_LAYERS = {"li1": 67, "met1": 68, "met2": 69, "met3": 70, "met4": 71, "met5": 72}
LEF_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "pdk", "sky130_fd_sc_hd_merged.lef")

def lef_pin_rects(path):
    """Complete pin landing geometry from the LEF: {macro: {pin: [(layer, Polygon)]}}.

    The GDS label-point method tags only the ONE polygon sitting under the
    label. But a pin is often several shapes: extra li1 polygons connected
    through poly/diff inside the cell, or a met1 strap (e.g. dfrtp_2 RESET_B).
    The router may land on any of them -- LEF PORT rects are the authoritative
    list of what is landable, so tag them all."""
    macros = {}
    m = p = lay = None
    for line in open(path):
        w = line.split()
        if not w: continue
        k = w[0]
        if k == "MACRO":
            m, p = w[1], None; macros[m] = {}
        elif m is None:
            continue
        elif k == "PIN":
            p = w[1]; macros[m].setdefault(p, [])
        elif k == "OBS":
            p = None
        elif k == "END" and len(w) > 1:
            if w[1] == p: p = None
            elif w[1] == m: m = None
        elif k == "LAYER" and p is not None:
            lay = LEF_LAYERS.get(w[1])
        elif k == "RECT" and p is not None and lay is not None:
            x1, y1, x2, y2 = map(float, w[1:5])
            macros[m][p].append((lay, Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])))
    return macros

def ref_affine(ref):
    """shapely affine coefficients for a gdstk reference (GDS: mirror-X first, then rotate, then move)."""
    th = ref.rotation
    s = -1.0 if ref.x_reflection else 1.0
    c, si = math.cos(th), math.sin(th)
    return [c, -s * si, si, s * c, ref.origin[0], ref.origin[1]]

def poly2shape(p):
    return Polygon([(x, y) for x, y in p.points])

def cell_polys(cell, layer, datatype):
    out = [poly2shape(p) for p in cell.polygons if p.layer == layer and p.datatype == datatype]
    for path in cell.paths:
        if path.layers[0] == layer and path.datatypes[0] == datatype:
            out += [poly2shape(pp) for pp in path.to_polygons()]
    return out

def main(gds_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    lib = gdstk.read_gds(gds_path)
    top = lib.top_level()[0]
    print(f"top cell: {top.name}")

    lef_path = os.environ.get("LEF", LEF_DEFAULT)
    lefpins = lef_pin_rects(lef_path) if os.path.exists(lef_path) else {}
    print(f"LEF pin geometry: {len(lefpins)} macros" if lefpins
          else "WARNING: no LEF found -- pin tagging falls back to GDS labels only")

    celltypes = {}
    viatypes = {}
    for c in {r.cell.name: r.cell for r in top.references}.values():
        if c.name.startswith("VIA_"):
            pads = {l: cell_polys(c, l, 20) for l in ROUTE_LAYERS}
            viatypes[c.name] = {l: ps for l, ps in pads.items() if ps}
            continue
        if not c.name.startswith("sky130"):
            cond = {l: cell_polys(c, l, 20) for l in ROUTE_LAYERS}
            cond = {l: ps for l, ps in cond.items() if ps}
            if cond:
                desc = " ".join(f"{LNAME[l]}x{len(ps)}" for l, ps in sorted(cond.items()))
                if os.environ.get("INCLUDE_NONSKY"):
                    print(f"NOTE: non-std cell {c.name} carries conductors [{desc}] -- INCLUDED in soup")
                    celltypes[c.name] = {"pins": {}, "cond": cond, "mcon": cell_polys(c, 67, 44)}
                    continue
                print(f"WARNING: non-std cell {c.name} carries conductors [{desc}] -- IGNORED "
                      f"(rerun with INCLUDE_NONSKY=1 if nets dead-end at its instances)")
            celltypes[c.name] = None
            continue
        short = c.name.split("__")[-1]
        if short.startswith(("decap", "fill", "tapvpwrvgnd")):
            celltypes[c.name] = None
            continue
        bridge = short.startswith("diode")
        cond = {l: cell_polys(c, l, 20) for l in ROUTE_LAYERS}
        cond = {l: ps for l, ps in cond.items() if ps}
        pins = collections.defaultdict(list)
        for lab in c.labels:
            if (lab.layer, lab.texttype) == (67, 5) and lab.text not in POWER_PINS:
                pt = Point(lab.origin)
                pins[lab.text] += [(67, p) for p in cond.get(67, []) if p.buffer(0.005).intersects(pt)]
        for pname, rects in lefpins.get(c.name, {}).items():
            if pname not in POWER_PINS:
                pins[pname] += rects
        mcon = cell_polys(c, 67, 44)
        celltypes[c.name] = {"pins": dict(pins), "cond": cond, "mcon": mcon, "bridge": bridge}

    soup = {l: [] for l in ROUTE_LAYERS}
    pin_marks = []
    via_marks = []
    instances = []

    for ref in top.references:
        cname = ref.cell.name
        A = ref_affine(ref)
        tf = lambda g: affinity.affine_transform(g, A)
        if cname in viatypes:
            layers = sorted(viatypes[cname].keys())
            pads = {l: [tf(p) for p in viatypes[cname][l]] for l in layers}
            for l in layers:
                soup[l] += pads[l]
            via_marks.append([(l, pads[l][0].representative_point()) for l in layers])
            continue
        info = celltypes.get(cname)
        if info is None:
            continue
        if not info["pins"]:
            for l, ps in info["cond"].items():
                soup[l] += [tf(p) for p in ps]
            for p in info["mcon"]:
                pt = tf(p).representative_point()
                via_marks.append([(67, pt), (68, pt)])
            continue
        idx = len(instances)
        instances.append({"idx": idx, "cell": cname, "bridge": info.get("bridge", False),
                          "x": round(ref.origin[0], 4), "y": round(ref.origin[1], 4),
                          "rot": round(math.degrees(ref.rotation)) % 360, "mirror": bool(ref.x_reflection)})
        for l, ps in info["cond"].items():
            soup[l] += [tf(p) for p in ps]
        for p in info["mcon"]:
            pt = tf(p).representative_point()
            via_marks.append([(67, pt), (68, pt)])
        for pname, ppolys in info["pins"].items():
            for lay, pp in ppolys:
                pin_marks.append((lay, tf(pp).representative_point(), idx, pname))

    for dt in (20, 16):
        for l in ROUTE_LAYERS:
            soup[l] += cell_polys(top, l, dt)

    comps, trees = {}, {}
    for l in ROUTE_LAYERS:
        u = unary_union(soup[l]) if soup[l] else None
        geoms = [] if u is None else (list(u.geoms) if u.geom_type != "Polygon" else [u])
        comps[l] = geoms
        trees[l] = STRtree(geoms) if geoms else None
        print(f"layer {LNAME[l]:5s}: {len(soup[l]):5d} shapes -> {len(geoms):4d} islands")

    def find_comp(layer, point):
        if trees[layer] is None: return None
        for i in trees[layer].query(point, predicate="intersects"):
            return (layer, int(i))
        for i in trees[layer].query(point.buffer(0.01), predicate="intersects"):
            return (layer, int(i))
        return None

    parent = {}
    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def union(a, b):
        parent[find(a)] = find(b)

    GAP = float(os.environ.get("GAP", "0.06"))
    stitched = 0
    for l in ROUTE_LAYERS:
        if trees[l] is None: continue
        for i, g in enumerate(comps[l]):
            for j in trees[l].query(g.buffer(GAP), predicate="intersects"):
                j = int(j)
                if j != i and find((l, i)) != find((l, j)) and g.distance(comps[l][j]) <= GAP:
                    union((l, i), (l, j)); stitched += 1
    if stitched: print(f"stitched {stitched} same-layer island pairs (gap<= {GAP*1000:.0f}nm)")

    missed_vias = 0
    for group in via_marks:
        found = [c for c in (find_comp(l, pt) for l, pt in group) if c]
        if len(found) >= 2:
            for c in found[1:]: union(found[0], c)
        else:
            missed_vias += 1
    if missed_vias: print(f"WARNING: {missed_vias} vias failed to bind")

    unbound = 0
    by_pin = collections.defaultdict(list)
    for layer, pt, idx, pname in pin_marks:
        c = find_comp(layer, pt)
        if c is None: unbound += 1; continue
        by_pin[(idx, pname)].append(c)
    if unbound: print(f"WARNING: {unbound} cell pins not touching any conductor")
    net_pins = collections.defaultdict(list)
    for (idx, pname), clist in by_pin.items():
        for c in clist[1:]: union(clist[0], c)
    for (idx, pname), clist in by_pin.items():
        net_pins[find(clist[0])].append((idx, pname))

    LABEL2METAL = {70: 70, 71: 71, 72: 72}
    net_ports = collections.defaultdict(set)
    for lab in top.labels:
        if lab.texttype == 5 and lab.layer in LABEL2METAL:
            c = find_comp(LABEL2METAL[lab.layer], Point(lab.origin))
            if c: net_ports[find(c)].add(lab.text)

    nets = collections.defaultdict(lambda: {"pins": [], "ports": set()})
    for r, pl in net_pins.items(): nets[find(r)]["pins"] += pl
    for r, po in net_ports.items(): nets[find(r)]["ports"] |= po

    for k in ("VPWR", "VGND"):
        pass
    bridge_idx = {i["idx"] for i in instances if i.get("bridge")}
    netlist = []
    for i, (root, d) in enumerate(sorted(nets.items(), key=lambda kv: str(kv[0]))):
        ports = d["ports"] - {"VPWR", "VGND"}
        pins = sorted({(ix, p) for ix, p in set(d["pins"]) if ix not in bridge_idx})
        if not pins and not ports: continue
        name = sorted(ports)[0] if ports else f"net_{i:03d}"
        drivers = [(idx, p) for idx, p in pins if p in OUTPUT_PINS]
        netlist.append({"name": name, "ports": sorted(ports), "pins": pins, "drivers": drivers})

    ndrv_bad = [n for n in netlist if len(n["drivers"]) + (1 if n["ports"] and not n["drivers"] else 0) != 1]
    print(f"nets: {len(netlist)}   nets with driver-count != 1: {len(ndrv_bad)}")
    for n in ndrv_bad: print("   check:", n["name"], n)

    probe = os.environ.get("PROBE")
    if probe is not None:
        root_of_name = {}
        for n in netlist:
            r = find(by_pin[tuple(n["pins"][0])][0]) if n["pins"] else None
            if r is None:
                for lab in top.labels:
                    if lab.texttype == 5 and lab.layer in LABEL2METAL and lab.text in n["ports"]:
                        c = find_comp(LABEL2METAL[lab.layer], Point(lab.origin))
                        if c: r = find(c); break
            if r is not None: root_of_name[n["name"]] = r
        name_of_root = {r: nm for nm, r in root_of_name.items()}
        want = [w for w in probe.split(",") if w] or \
               [n["name"] for n in ndrv_bad] + \
               [n["name"] for n in netlist if n["ports"] and not n["pins"]]
        RADIUS = float(os.environ.get("PROBE_RADIUS", "2.0"))
        print(f"\n== PROBE (nearest foreign island within {RADIUS*1000:.0f}nm) ==")
        for nm in want:
            r = root_of_name.get(nm)
            if r is None:
                print(f"  {nm}: no geometry located"); continue
            mine = collections.defaultdict(list)
            for l in ROUTE_LAYERS:
                for i, g in enumerate(comps[l]):
                    if find((l, i)) == r: mine[l].append(g)
            desc = " ".join(f"{LNAME[l]}x{len(gs)}" for l, gs in sorted(mine.items()))
            print(f"  {nm}  [{desc}]")
            best = []
            for l, gs in mine.items():
                for g in gs:
                    for k in trees[l].query(g.buffer(RADIUS), predicate="intersects"):
                        k = int(k)
                        if find((l, k)) == r: continue
                        best.append((g.distance(comps[l][k]), l, g, comps[l][k], find((l, k))))
            for d, l, g, o, orr in sorted(best, key=lambda t: t[0])[:4]:
                a, b = g.bounds, o.bounds
                print(f"     {d*1000:7.1f}nm on {LNAME[l]:4s} -> net {name_of_root.get(orr,'(unnamed)'):10s}"
                      f"  mine({a[0]:.2f},{a[1]:.2f})-({a[2]:.2f},{a[3]:.2f})"
                      f"  theirs({b[0]:.2f},{b[1]:.2f})-({b[2]:.2f},{b[3]:.2f})")

    if os.environ.get("DIAG"):
        island_root = {}
        for l in ROUTE_LAYERS:
            for i, g in enumerate(comps[l]):
                island_root.setdefault(find((l, i)), []).append(g)
        out_marks = [(pt, idx, pn) for (layer, pt, idx, pn) in pin_marks if pn in OUTPUT_PINS]
        root_layer_geoms = collections.defaultdict(lambda: collections.defaultdict(list))
        for l in ROUTE_LAYERS:
            for i, g in enumerate(comps[l]):
                root_layer_geoms[find((l, i))][l].append(g)
        print("\n== DIAG: undriven nets ==")
        for n in ndrv_bad:
            if n["drivers"]: continue
            idx0, p0 = n["pins"][0]
            root = find(by_pin[(idx0, p0)][0])
            per = root_layer_geoms.get(root, {})
            layerdesc = " ".join(f"{LNAME[l]}x{len(gs)}" for l, gs in sorted(per.items()))
            geoms = island_root.get(root, [])
            best = min(((g.distance(pt), idx, pn) for pt, idx, pn in out_marks
                        for g in geoms), key=lambda t: t[0])
            d, didx, dpn = best
            drv_cell = next((it["cell"].split("__")[-1] for it in instances if it["idx"] == didx), "?")
            owner = next((m["name"] for m in netlist if (didx, dpn) in [tuple(x) for x in m["pins"]]), "?")
            near = None
            for l in ROUTE_LAYERS:
                if trees[l] is None: continue
                for g in per.get(l, []):
                    for k in trees[l].query(g.buffer(0.35), predicate="intersects"):
                        k = int(k)
                        if find((l, k)) == root: continue
                        dd = g.distance(comps[l][k])
                        if near is None or dd < near[0]:
                            near = (dd, LNAME[l], find((l, k)))
            neartxt = f"{near[0]*1000:.0f}nm on {near[1]}" if near else "none<350nm"
            print(f"  {n['name']:9s} sinks={len(n['pins']):2d}  layers[{layerdesc}]  "
                  f"nearest-other-net {neartxt}")
            for l, gs in sorted(per.items()):
                for g in gs:
                    b = g.bounds
                    print(f"       {LNAME[l]:4s} ({b[0]:.2f},{b[1]:.2f})-({b[2]:.2f},{b[3]:.2f})")

    pin2net = {}
    for n in netlist:
        for idx, p in n["pins"]:
            pin2net[(idx, p)] = n["name"]
    inputs  = sorted({n["name"] for n in netlist if n["ports"] and not n["drivers"]})
    outputs = sorted({n["name"] for n in netlist if n["ports"] and n["drivers"]})
    internal = sorted({n["name"] for n in netlist if not n["ports"]})

    def decls(names, kw):
        """Emit Verilog port declarations, grouping bus bits O[0..7] -> [7:0] O.
        Returns (header_names, declaration_lines). Bit-select names like 'O[3]'
        stay valid in instance bodies once the vector is declared."""
        buses = collections.defaultdict(list); scalars = []
        for n in names:
            m = re.match(r"^(\w+)\[(\d+)\]$", n)
            (buses[m.group(1)].append(int(m.group(2))) if m else scalars.append(n))
        heads, lines = [], []
        for s in sorted(scalars):
            heads.append(s); lines.append(f"  {kw} {s};")
        for b in sorted(buses):
            hi, lo = max(buses[b]), min(buses[b])
            heads.append(b); lines.append(f"  {kw} [{hi}:{lo}] {b};")
        return heads, lines

    in_h,  in_d  = decls(inputs,  "input ")
    out_h, out_d = decls(outputs, "output")
    wire_h, wire_d = decls(internal, "wire")

    vpath = os.path.join(outdir, "extracted_netlist.v")
    with open(vpath, "w") as f:
        f.write(f"// Extracted from {os.path.basename(gds_path)} by geometry alone -- no netlist was harmed\n")
        f.write(f"module {top.name}_extracted (" + ", ".join(in_h + out_h) + ");\n")
        for line in in_d + out_d + wire_d: f.write(line + "\n")
        undriven = [n["name"] for n in netlist
                    if not n["drivers"] and not (n["ports"] and not n["drivers"])
                    and not n["ports"]]
        if undriven:
            f.write(f"  // {len(undriven)} undriven signal nets tied to 0 (revisit): {undriven}\n")
            for w in undriven: f.write(f"  assign {w} = 1'b0;\n")
        for inst in instances:
            if inst.get("bridge"): continue
            conns = [(p, pin2net.get((inst['idx'], p))) for p in sorted(celltypes[inst["cell"]]["pins"])]
            conn_s = ", ".join(f".{p}({n})" for p, n in conns if n)
            f.write(f"  {inst['cell']} u{inst['idx']}_{inst['cell'].split('__')[-1]} ({conn_s});\n")
        f.write("endmodule\n")
        with open(os.path.join(outdir, "undriven_nets.txt"), "w") as g:
            g.write("\n".join(undriven) + ("\n" if undriven else ""))
    nlogic = len(instances) - len(bridge_idx)
    print(f"wrote {vpath}  ({nlogic} logic instances"
          + (f" + {len(bridge_idx)} bridge/diode omitted" if bridge_idx else "")
          + f", {len(inputs)} inputs, {len(outputs)} outputs)")

    with open(os.path.join(outdir, "extracted.json"), "w") as f:
        json.dump({"instances": instances,
                   "nets": [{k: (sorted(v) if isinstance(v, set) else v) for k, v in n.items()} for n in netlist]},
                  f, indent=1, default=str)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out")
