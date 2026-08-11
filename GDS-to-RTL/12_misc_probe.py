#!/usr/bin/env python3
"""
Two loose ends, both answered by poking the netlist rather than reading it:

  1. What does the chip say when you get it WRONG? (drive a bad grid, read O)
  2. What is the 8-flop register u447/u449/u451/u453/u454/u459/u460/u461 that
     `success` compares against a fixed pattern? Hypothesis: total star count.
     Test: drive k stars for k = 0..24 and read the register back.

Usage: python 12_misc_probe.py <netlist.v> <models.v> <top> <outdir>
"""
import os, sys, subprocess, re

CNT = ["u447_dfrtp_2", "u449_dfrtp_2", "u451_dfrtp_2", "u453_dfrtp_2",
       "u454_dfrtp_2", "u459_dfrtp_2", "u460_dfrtp_2", "u461_dfrtp_2"]
FRAME = 121


def build(netlist, models, top, outdir, sol):
    probes = ", ".join(f"dut.{f}.Q" for f in CNT)
    tb = f"""`timescale 1ns/1ps
module tb_misc;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer k, i, ns, m;
  reg [{FRAME}-1:0] sol = {FRAME}'b{sol};
  {top} dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    // ---- part 1: star-count sweep. k stars dropped on cells 0,4,8,... ----
    for (k=0; k<=24; k=k+1) begin
      rst_n=0; enable=0; I=0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n=1; enable=1;
      for (i=0; i<{FRAME}; i=i+1) begin
        I = (i % 4 == 0) && ((i/4) < k);
        @(posedge clk); @(negedge clk);
      end
      I=0;
      $display("NSTARS %0d REG {"%b" * len(CNT)}", k, {probes});
    end
    // ---- part 2: the message catalogue. Drive four classes of grid and read
    // O[7:0] back. The wrong ones are dead code no correct solve ever reaches,
    // so the only way to see them is to deliberately fail. ----
    for (m=0; m<4; m=m+1) begin
      rst_n=0; enable=0; I=0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n=1; enable=1;
      for (i=0; i<{FRAME}; i=i+1) begin
        case (m)
          0: I = 1'b0;                  // no stars at all
          1: I = 1'b1;                  // every cell a star
          2: I = (i % 4 == 0);          // 31 stars, structurally wrong
          3: I = sol[{FRAME}-1-i];      // the real answer
        endcase
        @(posedge clk); @(negedge clk);
      end
      I=0;
      for (i=0; i<40; i=i+1) begin
        $display("MSGOUT %0d %0d %0h success=%b", m, i, O, success);
        @(posedge clk); @(negedge clk);
      end
    end
    $finish;
  end
endmodule
"""
    tbp = os.path.join(outdir, "tb_misc.v")
    open(tbp, "w").write(tb)
    vvp = os.path.join(outdir, "misc.vvp")
    r = subprocess.run(f"iverilog -g2012 -o {vvp} {models} {netlist} {tbp}",
                       shell=True, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout + r.stderr); sys.exit(1)
    return subprocess.run(f"vvp {vvp}", shell=True,
                          capture_output=True, text=True).stdout


def main():
    netlist, models, top, outdir = sys.argv[1:5]
    sol = (sys.argv[5] if len(sys.argv) > 5 else "0" * FRAME)[:FRAME]
    log = build(netlist, models, top, outdir, sol)
    open(os.path.join(outdir, "misc_probe.log"), "w").write(log)

    print("star-count sweep: does the 8-flop register count stars?")
    print(f"   bit order {CNT}")
    prev = None
    for m in re.finditer(r"NSTARS (\d+) REG ([01]+)", log):
        k, bits = int(m.group(1)), m.group(2)
        val_msb = int(bits, 2)
        val_lsb = int(bits[::-1], 2)
        print(f"   {k:3d} stars -> {bits}   as-is={val_msb:3d}  reversed={val_lsb:3d}")
        prev = bits

    LABEL = {0: "0 stars (empty grid)", 1: "121 stars (every cell)",
             2: "31 stars, structurally wrong", 3: "the recovered solution"}
    msgs, succ = {}, {}
    for mm in re.finditer(r"MSGOUT (\d+) (\d+) ([0-9a-fx]+) success=(\w)", log):
        mode, v, s = int(mm.group(1)), mm.group(3), mm.group(4)
        if v.isalnum() and not v.startswith("x"):
            b = int(v, 16)
            if 32 <= b < 127:
                msgs.setdefault(mode, []).append(chr(b))
        succ[mode] = succ.get(mode, "0") if s != "1" else "1"
    print("\nMESSAGE CATALOGUE (drive a grid, read the ASCII on O[7:0]):")
    for mode in sorted(LABEL):
        print(f"   {LABEL[mode]:32s} success={succ.get(mode,'?')}  "
              f"-> {''.join(msgs.get(mode, []))!r}")


if __name__ == "__main__":
    main()
