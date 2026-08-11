`timescale 1ns/1ps
// Equivalence check: extracted-from-silicon netlist vs recovered RTL.
module tb_equiv;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire s_gate, s_rtl;  wire [7:0] o_gate, o_rtl;
  integer t, c, mism, mism_o, seed, trial, nstar, r_i;
  integer perm [0:10]; integer perm2 [0:10];
  reg [120:0] g;
  reg [120:0] sol = 121'b0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000;

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
    trial = 2; run_grid({121{1'b1}});
    // 3. near misses: flip exactly one cell of the solution
    //    ({$random} forces the unsigned read -- a bare $random is signed and
    //     `% 121` can come out negative, which silently indexes out of range)
    for (trial=3; trial<40; trial=trial+1) begin
      g = sol;
      t = {$random(seed)} % 121;
      g[t] = ~g[t];
      run_grid(g);
    end
    // 4. random sparse grids
    for (trial=40; trial<240; trial=trial+1) begin
      g = 0;
      nstar = 1 + ({$random(seed)} % 30);
      for (c=0; c<nstar; c=c+1) g[{$random(seed)} % 121] = 1'b1;
      run_grid(g);
    end
    // 5. the hard class: exactly 2 stars in every row, columns/regions random.
    //    These pass the row check and the total-count check, so they probe the
    //    column, region and adjacency logic in isolation -- the paths a merely
    //    sparse random grid almost never reaches.
    for (trial=240; trial<440; trial=trial+1) begin
      g = 0;
      for (r_i=0; r_i<11; r_i=r_i+1) begin
        g[120 - (r_i*11 + ({$random(seed)} % 11))] = 1'b1;
        g[120 - (r_i*11 + ({$random(seed)} % 11))] = 1'b1;
      end
      run_grid(g);
    end
    // 6. two stars per row AND per column (a random permutation pair): fails
    //    only on regions or adjacency, the deepest paths in the design.
    for (trial=440; trial<540; trial=trial+1) begin
      for (c=0; c<11; c=c+1) perm[c] = c;
      for (c=10; c>0; c=c-1) begin
        t = {$random(seed)} % (c+1);
        nstar = perm[c]; perm[c] = perm[t]; perm[t] = nstar;
      end
      for (c=0; c<11; c=c+1) perm2[c] = c;
      for (c=10; c>0; c=c-1) begin
        t = {$random(seed)} % (c+1);
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
