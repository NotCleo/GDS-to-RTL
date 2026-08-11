#!/usr/bin/env python3
"""
Is the recovered grid the *unique* input the hardware accepts?

Hypothesis from the decompiled logic: the chip checks an 11x11 Star Battle --
exactly 2 stars per row, 2 per column, no two stars touching (8-neighbourhood).
If that were the whole story there would be a huge number of accepted grids,
which would make the puzzle ill-posed. So either the hypothesis is incomplete
(there are region constraints too), or the chip really does accept many grids.

Method: enumerate grids satisfying the hypothesis with z3, then feed each one to
the *actual extracted netlist* in simulation and see whether `success` fires.
The netlist is the oracle -- never trust the hypothesis over the silicon.

Usage: python 10_uniqueness.py <netlist.v> <models.v> <top> <n_candidates> <outdir>
"""
import os, sys, subprocess, re, json
from z3 import Bool, Solver, Sum, If, Not, Or, And, sat

N = 11
STARS = 2

TB = """`timescale 1ns/1ps
module tb_u;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer i; reg [122:0] seq = 123'b{BITS};
  reg [8*32:1] msg; integer mi;
  {TOP} dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    rst_n=0; enable=0; I=0; mi=0;
    @(posedge clk); @(posedge clk); rst_n=1; @(negedge clk);
    enable=1;
    for (i=0;i<123;i=i+1) begin I = seq[122-i]; @(posedge clk); @(negedge clk); end
    I=0;
    $write("SUCCESS=%b MSG=", success);
    for (i=0;i<40;i=i+1) begin
      if (O !== 8'h00) $write("%c", O);
      @(posedge clk); @(negedge clk);
    end
    $write("\\n"); $finish;
  end
endmodule
"""


def enumerate_grids(limit):
    """All 11x11 grids with 2 stars/row, 2/col, no two stars 8-adjacent."""
    g = [[Bool(f"g{r}_{c}") for c in range(N)] for r in range(N)]
    s = Solver()
    for r in range(N):
        s.add(Sum([If(g[r][c], 1, 0) for c in range(N)]) == STARS)
    for c in range(N):
        s.add(Sum([If(g[r][c], 1, 0) for r in range(N)]) == STARS)
    for r in range(N):
        for c in range(N):
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < N and 0 <= cc < N:
                    s.add(Not(And(g[r][c], g[rr][cc])))
    out = []
    while len(out) < limit and s.check() == sat:
        m = s.model()
        grid = [[bool(m.evaluate(g[r][c])) for c in range(N)] for r in range(N)]
        out.append(grid)
        s.add(Or([g[r][c] != grid[r][c] for r in range(N) for c in range(N)]))
    return out, (s.check() == sat)


def sim(netlist, models, top, bits, outdir, tag):
    tb = os.path.join(outdir, f"tb_u_{tag}.v")
    open(tb, "w").write(TB.format(BITS=bits, TOP=top))
    vvp = os.path.join(outdir, f"u_{tag}.vvp")
    r = subprocess.run(f"iverilog -g2012 -o {vvp} {models} {netlist} {tb}",
                       shell=True, capture_output=True, text=True)
    if r.returncode:
        return None, r.stdout + r.stderr
    r = subprocess.run(f"vvp {vvp}", shell=True, capture_output=True, text=True)
    os.remove(tb); os.remove(vvp)
    m = re.search(r"SUCCESS=(\w) MSG=(.*)", r.stdout)
    return (m.group(1), m.group(2).strip()) if m else (None, r.stdout)


def main():
    netlist, models, top, nc, outdir = sys.argv[1:6]
    nc = int(nc)
    print(f"enumerating up to {nc} grids with 2/row, 2/col, no-touch ...")
    grids, more = enumerate_grids(nc)
    print(f"  found {len(grids)}" + (" (and more exist)" if more else " (that is ALL of them)"))
    results = []
    for i, g in enumerate(grids):
        bits = "".join("1" if g[r][c] else "0" for r in range(N) for c in range(N)) + "00"
        succ, msg = sim(netlist, models, top, bits, outdir, str(i))
        results.append({"grid": [["*" if x else "." for x in row] for row in g],
                        "bits": bits, "success": succ, "msg": msg})
        print(f"  candidate {i:3d}: success={succ}  msg={msg!r}")
    acc = [r for r in results if r["success"] == "1"]
    print(f"\n{len(acc)} of {len(results)} row/col/no-touch grids are ACCEPTED by the netlist")
    if acc and len(acc) < len(results):
        print("=> the chip enforces MORE than row/col/no-touch (regions!). "
              "Accepted example:")
        for row in acc[0]["grid"]:
            print("   " + " ".join(row))
    json.dump(results, open(f"{outdir}/uniqueness.json", "w"), indent=1)
    print(f"wrote {outdir}/uniqueness.json")


if __name__ == "__main__":
    main()
