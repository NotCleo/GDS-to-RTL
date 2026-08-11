#!/usr/bin/env python3
"""
Validate an extracted netlist against recorded silicon behaviour.

example_inputs.vcd records a real run: the input waveform (clk, rst_n, enable, I)
AND the resulting outputs (O[7:0], success). If our GDS-extracted netlist is
correct, driving it with the same inputs must reproduce the same outputs.

This parses the VCD, generates a Verilog testbench that replays the exact input
transitions and checks O/success at every timestamp the VCD recorded them, then
you run iverilog on it. A clean match = extraction validated against ground truth.

Usage: python 06_vcd_replay.py <example_inputs.vcd> <top_module> <out_tb.v>
"""
import sys, re

def parse_vcd(path):
    sym = {}
    width = {}
    with open(path) as f:
        txt = f.read()
    for m in re.finditer(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+([^\s$]+(?:\s*\[\d+:\d+\])?)\s+\$end", txt):
        w, ident, name = m.groups()
        sym[ident] = name.strip().split()[0]
        width[ident] = int(w)
    events = []
    t = 0
    for line in txt.splitlines():
        line = line.strip()
        if not line: continue
        if line[0] == "#":
            t = int(line[1:]); continue
        if line[0] in "01xzXZ" and len(line) >= 2 and line[1] in sym:
            events.append((t, line[1], line[0])); continue
        m = re.match(r"^[bB]([01xzXZ]+)\s+(\S+)$", line)
        if m and m.group(2) in sym:
            events.append((t, m.group(2), m.group(1)))
    return sym, width, events

def main(vcd, top, out):
    sym, width, events = parse_vcd(vcd)
    name2id = {v: k for k, v in sym.items()}
    def find(nm):
        for ident, n in sym.items():
            if n == nm or n.startswith(nm + "[") or n.split("[")[0] == nm:
                return ident
        return None
    ids = {n: find(n) for n in ["clk", "rst_n", "enable", "I", "O", "success"]}
    print("VCD signal map:", {n: (i, sym.get(i)) for n, i in ids.items()})
    IN = ["clk", "rst_n", "enable", "I"]

    from collections import defaultdict, OrderedDict
    byt = OrderedDict()
    for t, ident, val in events:
        byt.setdefault(t, []).append((ident, val))
    times = sorted(byt)

    lines = []
    lines.append("`timescale 1ps/1ps")
    lines.append(f"module tb_replay;")
    lines.append("  reg clk=0, rst_n=0, enable=0, I=0;")
    lines.append("  wire [7:0] O; wire success;")
    lines.append("  integer checks=0, mism=0;")
    lines.append(f"  {top} dut(.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(O), .success(success));")
    lines.append("  initial begin")
    prev = 0
    for t in times:
        dt = t - prev; prev = t
        if dt > 0: lines.append(f"    #{dt};")
        ref = {}
        for ident, val in byt[t]:
            nm = sym[ident]
            base = nm.split("[")[0]
            if base in IN:
                lines.append(f"    {base} = 1'b{val if val in '01' else '0'};")
            elif base == "O":
                ref["O"] = val
            elif base == "success":
                ref["success"] = val
        if ref:
            lines.append("    #1;")
            if "O" in ref and set(ref["O"]) <= set("01"):
                w = len(ref["O"])
                lines.append(f"    checks=checks+1; if (O !== 8'b{ref['O'].zfill(8)}) begin mism=mism+1; "
                             f"$display(\"  t=%0t O mismatch: dut=%b ref={ref['O'].zfill(8)}\", $time, O); end")
            if "success" in ref and ref["success"] in "01":
                lines.append(f"    checks=checks+1; if (success !== 1'b{ref['success']}) begin mism=mism+1; "
                             f"$display(\"  t=%0t success mismatch: dut=%b ref={ref['success']}\", $time, success); end")
            lines.append(f"    #{max(0, 0)};")
            lines.append("    #0;")
            prev = t + 1
    lines.append('    $display("REPLAY: %0d checks, %0d mismatches", checks, mism);')
    lines.append('    if (mism==0) $display("EXTRACTION VALIDATED vs recorded silicon outputs");')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    open(out, "w").write("\n".join(lines) + "\n")
    print(f"wrote {out}: {len(times)} timestamps, checks generated")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
