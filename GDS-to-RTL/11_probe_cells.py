#!/usr/bin/env python3
"""
Recover the meaning of every 2-bit counter by SINGLE-CELL STIMULUS.

The decompiler tells you a counter is gated by "counter == 0101", but not what
that slot means physically. So stop reading and start poking: for each of the
121 grid positions in turn, reset the chip, drive I=1 at exactly that position
(and 0 everywhere else), clock through the whole frame, and record which of the
23 counters incremented.

A counter that increments for cell (r,c) is *watching* that cell. Collect the
set of cells each counter watches and you have read the constraint map straight
out of the silicon -- rows, columns, and (if present) irregular regions.

One iverilog build; the trial loop lives inside the testbench, so this costs
seconds rather than 121 separate compiles.

Usage: python 11_probe_cells.py <netlist.v> <models.v> <top> <structure.json> <outdir>
"""
import os, sys, subprocess, re, json, collections

N = 11
FRAME = 121


def main():
    netlist, models, top, structjson, outdir = sys.argv[1:6]
    st = json.load(open(structjson))
    pairs = [tuple(c) for c in st["sccs"] if len(c) == 2]
    flops = [f for p in pairs for f in p]

    probes = ", ".join(f'dut.{f}.Q' for f in flops)
    fmt = "%b" * len(flops)
    tb = f"""`timescale 1ns/1ps
module tb_probe;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer k, i;
  {top} dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    for (k=0; k<{FRAME}; k=k+1) begin
      rst_n=0; enable=0; I=0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n=1; enable=1;
      for (i=0; i<{FRAME}; i=i+1) begin
        I = (i==k);
        @(posedge clk); @(negedge clk);
      end
      I=0;
      $display("CELL %0d {fmt}", k, {probes});
    end
    $finish;
  end
endmodule
"""
    tbp = os.path.join(outdir, "tb_probe.v")
    open(tbp, "w").write(tb)
    vvp = os.path.join(outdir, "probe.vvp")
    r = subprocess.run(f"iverilog -g2012 -o {vvp} {models} {netlist} {tbp}",
                       shell=True, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout + r.stderr); sys.exit(1)
    r = subprocess.run(f"vvp {vvp}", shell=True, capture_output=True, text=True)
    log = r.stdout
    open(os.path.join(outdir, "probe.log"), "w").write(log)

    watches = collections.defaultdict(set)
    for m in re.finditer(r"CELL (\d+) ([01]+)", log):
        k, bits = int(m.group(1)), m.group(2)
        state = dict(zip(flops, bits))
        for pi, (a, b) in enumerate(pairs):
            if state[a] == "1" or state[b] == "1":
                watches[pi].add(k)

    R = []
    def p(*a):
        s = " ".join(str(x) for x in a); print(s); R.append(s)

    p("=" * 70)
    p("WHAT EACH 2-BIT COUNTER WATCHES  (single-cell stimulus, from silicon)")
    p("=" * 70)

    rowsets, colsets, other = [], [], []
    for pi, cells in sorted(watches.items(), key=lambda kv: sorted(kv[1])):
        rs = {c // N for c in cells}
        cs = {c % N for c in cells}
        kind = "REGION"
        if len(rs) == 1 and len(cells) == N:
            kind = f"ROW {rs.pop()}"; rowsets.append(pi)
        elif len(cs) == 1 and len(cells) == N:
            kind = f"COL {cs.pop()}"; colsets.append(pi)
        else:
            other.append(pi)
        p(f"  pair {pairs[pi][0]:16s}/{pairs[pi][1]:16s} "
          f"watches {len(cells):3d} cells -> {kind}")

    p("")
    p(f"rows found: {len(rowsets)}   cols found: {len(colsets)}   "
      f"irregular groups: {len(other)}")

    label = {}
    for idx, pi in enumerate(other):
        for c in watches[pi]:
            label[c] = "ABCDEFGHIJKLMNOP"[idx]
    if other:
        p("")
        p("REGION MAP (each letter = one group of cells sharing a counter):")
        for r in range(N):
            p("   " + " ".join(label.get(r * N + c, "?") for c in range(N)))
        sizes = collections.Counter(label.values())
        p(f"   region sizes: {dict(sorted(sizes.items()))}")
        unassigned = [c for c in range(N * N) if c not in label]
        if unassigned:
            p(f"   !! {len(unassigned)} cells belong to no group: {unassigned}")

    json.dump({"pairs": pairs,
               "watches": {str(k): sorted(v) for k, v in watches.items()},
               "region_of_cell": label},
              open(f"{outdir}/regions.json", "w"), indent=1)
    open(f"{outdir}/regions.txt", "w").write("\n".join(R) + "\n")
    p("")
    p(f"wrote {outdir}/regions.json, {outdir}/regions.txt")


if __name__ == "__main__":
    main()
