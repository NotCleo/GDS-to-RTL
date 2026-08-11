#!/usr/bin/env python3
"""
Step 3: prove the extraction is EXACT, using the warm-up's golden files.

  a) DEF cross-check : every GDS instance placement must equal a DEF COMPONENT
     (same cell, same lower-left corner, same orientation). This also hands us
     the instance NAMES (sr_a/_16_, add0/_35_, ...) that the GDS deleted.
  b) Golden netlist  : with names recovered, compare connectivity pin-by-pin
     against warmup-task/01_netlist.v. Two netlists are identical iff they induce
     the same partition of pins into nets, with the same port attachments.

(For the real puzzle there is no DEF/netlist -- this validation exists to let
 you trust the extractor before pointing it at puzzle.gds.)

Usage: python 03_def_crosscheck.py <final.gds> <pnr.def> <golden_netlist.v> <outdir>
"""
import sys, re, json, math, collections
import gdstk

def parse_def_components(path):
    txt = open(path).read()
    m = re.search(r"^COMPONENTS \d+ ;\n(.*?)^END COMPONENTS", txt, re.S | re.M)
    comps = {}
    for stmt in m.group(1).split(";"):
        mm = re.search(r"-\s+(\S+)\s+(\S+)\s+.*?(?:PLACED|FIXED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)", stmt, re.S)
        if mm:
            name, cell, x, y, o = mm.groups()
            comps[name] = (cell, int(x) / 1000.0, int(y) / 1000.0, o)
    return comps

def parse_golden_netlist(path):
    txt = open(path).read()
    insts = {}
    for stmt in txt.split(";"):
        mm = re.search(r"(sky130_fd_sc_hd__\w+)\s+(\\?\S+)\s*\((.*)\)\s*$", stmt, re.S)
        if not mm: continue
        cell, iname, body = mm.groups()
        iname = iname.lstrip("\\")
        pins = {p: n.strip().lstrip("\\").rstrip() for p, n in re.findall(r"\.(\w+)\(\s*([^)]*?)\s*\)", body)}
        insts[iname] = (cell, pins)
    return insts

def main(gds_path, def_path, golden_path, outdir):
    ext = json.load(open(f"{outdir}/extracted.json"))
    lib = gdstk.read_gds(gds_path)
    cellbb = {}
    for c in lib.cells:
        boxes = [p for p in c.polygons if (p.layer, p.datatype) == (81, 4)]
        if boxes:
            xs = [pt[0] for pt in boxes[0].points]; ys = [pt[1] for pt in boxes[0].points]
            cellbb[c.name] = ((min(xs), min(ys)), (max(xs), max(ys)))
        else:
            cellbb[c.name] = c.bounding_box()

    defcomps = parse_def_components(def_path)
    print(f"DEF components: {len(defcomps)}  (incl. decap/tap)   GDS logic instances: {len(ext['instances'])}")
    by_key = {}
    for name, (cell, x, y, o) in defcomps.items():
        by_key[(cell, round(x, 3), round(y, 3))] = name

    idx2name = {}
    for inst in ext["instances"]:
        (x0, y0), (x1, y1) = cellbb[inst["cell"]]
        w, h = x1 - x0, y1 - y0
        ox, oy, rot, mir = inst["x"], inst["y"], inst["rot"], inst["mirror"]
        pts = []
        for px, py in [(x0, y0), (x1, y1)]:
            sx, sy = px, -py if mir else py
            c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            pts.append((ox + c * sx - s * sy, oy + s * sx + c * sy))
        llx, lly = min(p[0] for p in pts), min(p[1] for p in pts)
        name = by_key.get((inst["cell"], round(llx, 3), round(lly, 3)))
        if name is None:
            print(f"  NO DEF MATCH for instance {inst}"); continue
        idx2name[inst["idx"]] = name
    print(f"matched {len(idx2name)}/{len(ext['instances'])} GDS instances to DEF components (names recovered!)")

    golden = parse_golden_netlist(golden_path)
    gold_partition = collections.defaultdict(set)
    for iname, (cell, pins) in golden.items():
        for p, n in pins.items():
            if p in ("VPWR", "VGND", "VPB", "VNB"): continue
            gold_partition[n].add((iname, p))

    ext_partition = {}
    for net in ext["nets"]:
        pins = {(idx2name[i], p) for i, p in net["pins"]}
        if pins: ext_partition[net["name"]] = (pins, set(net["ports"]))

    ok, bad = 0, 0
    mapping = {}
    for ename, (pins, ports) in ext_partition.items():
        gnets = {g for g, gpins in gold_partition.items() if pins & gpins}
        exact = [g for g in gnets if gold_partition[g] == pins]
        if len(gnets) == 1 and exact:
            g = exact[0]
            port_in_golden = g if g in ("A", "B", "S", "clk", "en", "rst_n") else None
            if (port_in_golden is None) == (len(ports) == 0) and (not ports or ports == {port_in_golden}):
                mapping[ename] = g; ok += 1; continue
        bad += 1
        print(f"  MISMATCH {ename}: pins={sorted(pins)} vs golden candidates={gnets}")
    print(f"net-by-net comparison: {ok} exact matches, {bad} mismatches, golden has {len(gold_partition)} nets")
    if bad == 0 and ok == len(gold_partition):
        print("VERDICT: extracted netlist is EXACTLY the golden netlist (connectivity-identical).")

    with open(f"{outdir}/name_map.json", "w") as f:
        json.dump({"instances": {str(k): v for k, v in idx2name.items()},
                   "nets": mapping}, f, indent=1)
    for i in sorted(idx2name)[:8]:
        print(f"   example: extracted u{i} = {defcomps[idx2name[i]][0].split('__')[-1]:10s} -> DEF/netlist name '{idx2name[i]}'")

if __name__ == "__main__":
    main(*sys.argv[1:5])
