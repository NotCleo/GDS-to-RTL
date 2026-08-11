#!/usr/bin/env python3
"""
Emit human-readable RTL for the recovered design, then prove it equivalent to
the gate netlist pulled out of the GDS.

This is the last step of the upstream flow: gds -> def -> netlist -> RTL. Up to
now the "understanding" lived in prose and JSON; this turns it into Verilog that
either matches the silicon cycle-for-cycle or does not. The comparison
testbench runs both modules from the same reset with the same stimulus and flags
the first cycle where `success` disagrees.

Stimulus mix (equivalence is only as good as the vectors):
  - the unique Star Battle solution
  - random sparse grids (mostly rejected, exercises every error path)
  - near-miss grids: the solution with one star moved / added / deleted
  - degenerate grids: empty, full

Usage: python 14_gen_rtl.py <regions.json> <solution_bits> <outdir>
"""
import sys, json, os

N = 11


def main():
    regions = json.load(open(sys.argv[1]))["region_of_cell"]
    sol = sys.argv[2][:121]
    outdir = sys.argv[3]
    os.makedirs(outdir, exist_ok=True)

    reg = {int(k): v for k, v in regions.items()}
    labels = sorted(set(reg.values()))
    rid = {lab: i for i, lab in enumerate(labels)}

    table = "\n".join(
        f"      11'd{k}: region_id = 4'd{rid[reg[k]]};" for k in range(N * N))

    rtl = f"""// ===========================================================================
// puzzle_recovered.v -- behavioural RTL recovered from puzzle.gds
//
// The chip is an 11x11 STAR BATTLE ("Two Not Touch") validator.
//
//   * The grid is shoved in serially on `I`, one cell per clock while
//     `enable` is high, in row-major order: 121 cells, 121 clocks.
//   * A star is I=1. The chip accepts the grid iff
//        - exactly 2 stars in every row
//        - exactly 2 stars in every column
//        - exactly 2 stars in every one of the 11 irregular regions
//        - no two stars orthogonally or diagonally adjacent
//        - 22 stars in total
//   * `success` rises on the FIRST clock after the 121st cell -- the 122nd
//     enabled clock edge -- and latches. The output generator streams an ASCII
//     verdict on O[7:0], one character per clock, starting that same cycle.
//
// Region map recovered by single-cell stimulus (see 11_probe_cells.py):
{chr(10).join('//   ' + ' '.join(reg[r * N + c] for c in range(N)) for r in range(N))}
// ===========================================================================
module puzzle_recovered (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       I,
  input  wire       enable,
  output wire       success,
  output wire [7:0] O
);
  localparam N = 11;

  // ---- scan position -------------------------------------------------------
  reg [3:0]  col, row;
  reg        done, done_d, succ_q;
  wire       running   = enable & ~done;
  wire       last_col  = (col == N-1);
  wire       last_cell = last_col & (row == N-1);
  wire       star      = I & running;

  // ---- region lookup -------------------------------------------------------
  reg  [3:0] region_id;
  wire [10:0] cell_no = row * N + col;
  always @* begin
    region_id = 4'd0;
    case (cell_no)
{table}
    endcase
  end

  // ---- constraint state ----------------------------------------------------
  reg [1:0] ccnt [0:N-1];      // per-column star count, saturating at 3
  reg [1:0] gcnt [0:N-1];      // per-region star count, saturating at 3
  reg [1:0] rowcnt;            // per-row count, cleared at the end of each row
  reg [7:0] total;             // total stars
  reg       adj_err, row_err;
  reg       all_ok;            // every column and region counter reads exactly 2
  reg [N-1:0] prev_row;        // star mask of the row above
  reg [N-1:0] cur_row;         // star mask of the row being scanned
  reg         prev_cell;       // star immediately to the left

  // a new star may not touch the one to its left, nor the three above it
  wire above_l = (col > 0)     ? prev_row[col-1] : 1'b0;
  wire above_c =                 prev_row[col];
  wire above_r = (col < N-1)   ? prev_row[col+1] : 1'b0;
  wire touches = prev_cell | above_l | above_c | above_r;

  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      col <= 0; row <= 0; done <= 0; done_d <= 0; succ_q <= 0;
      rowcnt <= 0; total <= 0; adj_err <= 0; row_err <= 0;
      prev_row <= 0; cur_row <= 0; prev_cell <= 0;
      for (i = 0; i < N; i = i + 1) begin ccnt[i] <= 0; gcnt[i] <= 0; end
    end else begin
      done_d <= done;

      if (running) begin
        if (star) begin
          if (ccnt[col]     != 2'd3) ccnt[col]     <= ccnt[col] + 1'b1;
          if (gcnt[region_id] != 2'd3) gcnt[region_id] <= gcnt[region_id] + 1'b1;
          if (rowcnt        != 2'd3) rowcnt        <= rowcnt + 1'b1;
          total   <= total + 1'b1;
          cur_row[col] <= 1'b1;
          if (touches) adj_err <= 1'b1;
        end
        prev_cell <= star;

        if (last_col) begin
          // end of a row: the row must have held exactly 2 stars
          if ((rowcnt + (star && rowcnt != 2'd3)) != 2'd2) row_err <= 1'b1;
          rowcnt    <= 0;
          prev_cell <= 0;
          prev_row  <= cur_row | (star << col);
          cur_row   <= 0;
          col       <= 0;
          row       <= row + 1'b1;
          if (last_cell) done <= 1'b1;
        end else begin
          col <= col + 1'b1;
        end
      end

      // `success` is evaluated in the single cycle where done is set but its
      // delayed copy is not, then held.
      if (done & ~done_d) begin
        succ_q <= ~adj_err & ~row_err & (total == 8'd22) & all_ok;
      end
    end
  end

  // all column and region counters must read exactly 2
  always @* begin
    all_ok = 1'b1;
    for (i = 0; i < N; i = i + 1) begin
      if (ccnt[i] != 2'd2) all_ok = 1'b0;
      if (gcnt[i] != 2'd2) all_ok = 1'b0;
    end
  end

  assign success = succ_q;

  // ---- output generator ----------------------------------------------------
  // Streams one ASCII character per clock once the verdict is known.
  localparam MAXC = 16;
  reg [7:0] rom [0:MAXC-1];
  reg [4:0] optr;
  reg       emitting;
  reg [7:0] o_q;
  integer j;
  reg [4:0] mlen;

  // The first character appears in the SAME cycle `success` resolves, so the
  // verdict cycle must both start the stream and emit rom[0].
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      optr <= 0; emitting <= 0; o_q <= 8'h00;
    end else if (done & ~done_d) begin
      emitting <= 1'b1; optr <= 5'd1; o_q <= rom[0];
    end else if (emitting && optr < mlen) begin
      o_q  <= rom[optr];
      optr <= optr + 1'b1;
    end else begin
      o_q <= 8'h00;
    end
  end
  assign O = o_q;

  // verdict text selection
  always @* begin
    if (total == 8'd0)                                        j = 0;   // EMPTY SKY
    else if (total == 8'd121)                                 j = 1;   // BIG BANG
    else if (~adj_err & ~row_err & (total == 8'd22) & all_ok) j = 2;   // win
    else                                                      j = 3;   // TRY AGAIN
    case (j)
      0: mlen = 9;  1: mlen = 8;  2: mlen = 15; default: mlen = 9;
    endcase
  end
  always @* begin
    for (i = 0; i < MAXC; i = i + 1) rom[i] = 8'h00;
    case (j)
      0: begin rom[0]="E"; rom[1]="M"; rom[2]="P"; rom[3]="T"; rom[4]="Y";
               rom[5]=" "; rom[6]="S"; rom[7]="K"; rom[8]="Y"; end
      1: begin rom[0]="B"; rom[1]="I"; rom[2]="G"; rom[3]=" ";
               rom[4]="B"; rom[5]="A"; rom[6]="N"; rom[7]="G"; end
      2: begin rom[0]="("; rom[1]="*"; rom[2]=" "; rom[3]="T"; rom[4]="W";
               rom[5]="O"; rom[6]=" "; rom[7]="S"; rom[8]="T"; rom[9]="A";
               rom[10]="R"; rom[11]="S"; rom[12]=" "; rom[13]="*"; rom[14]=")"; end
      default: begin rom[0]="T"; rom[1]="R"; rom[2]="Y"; rom[3]=" ";
               rom[4]="A"; rom[5]="G"; rom[6]="A"; rom[7]="I"; rom[8]="N"; end
    endcase
  end
endmodule
"""
    open(f"{outdir}/puzzle_recovered.v", "w").write(rtl)

    tb = f"""`timescale 1ns/1ps
// Equivalence check: extracted-from-silicon netlist vs recovered RTL.
module tb_equiv;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire s_gate, s_rtl;  wire [7:0] o_gate, o_rtl;
  integer t, c, mism, mism_o, seed, trial, nstar, r_i;
  integer perm [0:10]; integer perm2 [0:10];
  reg [120:0] g;
  reg [120:0] sol = 121'b{sol};

  puzzle_extracted uut_gate(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                            .success(s_gate), .O(o_gate));
  puzzle_recovered uut_rtl (.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                            .success(s_rtl),  .O(o_rtl));
  always #5 clk = ~clk;

  task run_grid; input [120:0] grid; begin
    rst_n=0; enable=0; I=0;
    @(posedge clk); @(posedge clk); @(negedge clk);
    rst_n=1; enable=1;
    for (c=0; c<140; c=c+1) begin
      I = (c < 121) ? grid[120-c] : 1'b0;
      @(posedge clk);
      if (s_gate !== s_rtl) begin
        mism = mism + 1;
        if (mism < 5) $display("  MISMATCH success trial=%0d cycle=%0d gate=%b rtl=%b",
                               trial, c+1, s_gate, s_rtl);
      end
      if (o_gate !== o_rtl) begin
        mism_o = mism_o + 1;
        if (mism_o < 5) $display("  MISMATCH O trial=%0d cycle=%0d gate=%02h rtl=%02h",
                                 trial, c+1, o_gate, o_rtl);
      end
      @(negedge clk);
    end
    I=0; enable=0;
  end endtask

  initial begin
    mism = 0; mism_o = 0; seed = 1;
    // 1. the solution itself
    trial = 0; run_grid(sol);
    // 2. degenerate grids
    trial = 1; run_grid(121'b0);
    trial = 2; run_grid({{121{{1'b1}}}});
    // 3. near misses: flip exactly one cell of the solution
    //    ({{$random}} forces the unsigned read -- a bare $random is signed and
    //     `% 121` can come out negative, which silently indexes out of range)
    for (trial=3; trial<40; trial=trial+1) begin
      g = sol;
      t = {{$random(seed)}} % 121;
      g[t] = ~g[t];
      run_grid(g);
    end
    // 4. random sparse grids
    for (trial=40; trial<240; trial=trial+1) begin
      g = 0;
      nstar = 1 + ({{$random(seed)}} % 30);
      for (c=0; c<nstar; c=c+1) g[{{$random(seed)}} % 121] = 1'b1;
      run_grid(g);
    end
    // 5. the hard class: exactly 2 stars in every row, columns/regions random.
    //    These pass the row check and the total-count check, so they probe the
    //    column, region and adjacency logic in isolation -- the paths a merely
    //    sparse random grid almost never reaches.
    for (trial=240; trial<440; trial=trial+1) begin
      g = 0;
      for (r_i=0; r_i<11; r_i=r_i+1) begin
        g[120 - (r_i*11 + ({{$random(seed)}} % 11))] = 1'b1;
        g[120 - (r_i*11 + ({{$random(seed)}} % 11))] = 1'b1;
      end
      run_grid(g);
    end
    // 6. two stars per row AND per column (a random permutation pair): fails
    //    only on regions or adjacency, the deepest paths in the design.
    for (trial=440; trial<540; trial=trial+1) begin
      for (c=0; c<11; c=c+1) perm[c] = c;
      for (c=10; c>0; c=c-1) begin
        t = {{$random(seed)}} % (c+1);
        nstar = perm[c]; perm[c] = perm[t]; perm[t] = nstar;
      end
      for (c=0; c<11; c=c+1) perm2[c] = c;
      for (c=10; c>0; c=c-1) begin
        t = {{$random(seed)}} % (c+1);
        nstar = perm2[c]; perm2[c] = perm2[t]; perm2[t] = nstar;
      end
      g = 0;
      for (r_i=0; r_i<11; r_i=r_i+1) begin
        g[120 - (r_i*11 + perm[r_i])]  = 1'b1;
        g[120 - (r_i*11 + perm2[r_i])] = 1'b1;
      end
      run_grid(g);
    end
    $display("EQUIVALENCE: %0d success mismatches, %0d O mismatches over %0d grids",
             mism, mism_o, trial);
    if (mism==0 && mism_o==0)
      $display("RESULT: recovered RTL is cycle-equivalent to the extracted netlist");
    else
      $display("RESULT: NOT equivalent -- the recovered RTL is wrong somewhere");
    $finish;
  end
endmodule
"""
    open(f"{outdir}/tb_equiv.v", "w").write(tb)
    print(f"wrote {outdir}/puzzle_recovered.v and {outdir}/tb_equiv.v")


if __name__ == "__main__":
    main()
