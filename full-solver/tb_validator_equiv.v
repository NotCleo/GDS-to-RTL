`timescale 1ns/1ps
// ===========================================================================
// tb_validator_equiv.v -- the split up validator against the gates
//
// validator.v rearranges puzzle-solution/08_recovered_rtl.v into seven
// submodules. This is the proof that the rearrangement did not change what the
// chip does: the same stimulus goes into the gate netlist extracted from
// puzzle.gds, into the original single block RTL and into the split up version,
// and every cycle of success and O[7:0] is compared across all three.
//
// The grid classes are the ones the main pipeline uses. The last set matters
// most: grids that get every count right and only break the no touch rule.
// They are the only ones that tell the fifth message apart from the fourth.
// ===========================================================================
module tb_validator_equiv;
  reg clk = 0, rst_n = 0, I = 0, enable = 0;
  wire s_gate, s_mono, s_mod;
  wire [7:0] o_gate, o_mono, o_mod;

  integer t, c, mism, mism_o, seed, trial, nstar, r_i, ndone;
  integer perm [0:10];
  integer perm2 [0:10];
  reg [120:0] g;
  reg [120:0] sol = 121'b0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000;
  reg [120:0] hard [0:23];

  puzzle_extracted  U_GATE (.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                            .success(s_gate), .O(o_gate));
  puzzle_recovered  U_MONO (.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                            .success(s_mono), .O(o_mono));
  validator         U_MOD  (.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                            .success(s_mod),  .O(o_mod));

  always #5 clk = ~clk;

  task run_grid;
    input [120:0] grid;
    begin
      rst_n = 0; enable = 0; I = 0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n = 1; enable = 1;
      for (c = 0; c < 140; c = c + 1) begin
        I = (c < 121) ? grid[120-c] : 1'b0;
        @(posedge clk);
        if (s_mod !== s_gate || s_mod !== s_mono) begin
          mism = mism + 1;
          if (mism < 5)
            $display("  MISMATCH success trial=%0d cycle=%0d gate=%b mono=%b mod=%b",
                     trial, c+1, s_gate, s_mono, s_mod);
        end
        if (o_mod !== o_gate || o_mod !== o_mono) begin
          mism_o = mism_o + 1;
          if (mism_o < 5)
            $display("  MISMATCH O trial=%0d cycle=%0d gate=%02h mono=%02h mod=%02h",
                     trial, c+1, o_gate, o_mono, o_mod);
        end
        @(negedge clk);
      end
      I = 0; enable = 0;
    end
  endtask

  task try_grid;
    input [120:0] grid;
    begin
      ndone = ndone + 1;
      run_grid(grid);
    end
  endtask

  initial begin
    mism = 0; mism_o = 0; seed = 1; ndone = 0;
    hard[0] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001100000000000000000110000100000100010010000;
    hard[1] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000010001000000010000100000100010010000;
    hard[2] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000010000100000010000100000100100010000;
    hard[3] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000010000000100010000100000100110000000;
    hard[4] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000001001000000100000100000100010010000;
    hard[5] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000001001000000010000100001000010010000;
    hard[6] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000001000100000100000100000100100010000;
    hard[7] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000001000100000010000100001000100010000;
    hard[8] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000001000000100100000100000100110000000;
    hard[9] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010001000000001000000100010000100001000110000000;
    hard[10] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000010010000000010000100000100010010000;
    hard[11] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000010000100000010000100000101000010000;
    hard[12] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000010000000100010000100000101010000000;
    hard[13] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000001010000000100000100000100010010000;
    hard[14] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000001010000000010000100001000010010000;
    hard[15] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000001000100000100000100000101000010000;
    hard[16] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000001000100000010000100001001000010000;
    hard[17] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000001000000100100000100000101010000000;
    hard[18] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000100000001000000100010000100001001010000000;
    hard[19] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000000000011011000000000000100000100010010000;
    hard[20] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000000000011010100000000000100000100100010000;
    hard[21] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000000000011010000100000000100000100110000000;
    hard[22] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000000000011001100000000000100000101000010000;
    hard[23] = 121'b1100000000000000010100000000010100011000000010001000000000001010000000010010000000000011001000100000000100000101010000000;
    trial = 0; try_grid(sol);
    trial = 1; try_grid(121'b0);
    trial = 2; try_grid({121{1'b1}});
    for (trial = 3; trial < 40; trial = trial + 1) begin
      g = sol; t = {$random(seed)} % 121; g[t] = ~g[t]; try_grid(g);
    end
    for (trial = 40; trial < 240; trial = trial + 1) begin
      g = 0; nstar = 1 + ({$random(seed)} % 30);
      for (c = 0; c < nstar; c = c + 1) g[{$random(seed)} % 121] = 1'b1;
      try_grid(g);
    end
    for (trial = 240; trial < 440; trial = trial + 1) begin
      g = 0;
      for (r_i = 0; r_i < 11; r_i = r_i + 1) begin
        g[120 - (r_i*11 + ({$random(seed)} % 11))] = 1'b1;
        g[120 - (r_i*11 + ({$random(seed)} % 11))] = 1'b1;
      end
      try_grid(g);
    end
    for (trial = 440; trial < 540; trial = trial + 1) begin
      for (c = 0; c < 11; c = c + 1) perm[c] = c;
      for (c = 10; c > 0; c = c - 1) begin
        t = {$random(seed)} % (c+1);
        nstar = perm[c]; perm[c] = perm[t]; perm[t] = nstar;
      end
      for (c = 0; c < 11; c = c + 1) perm2[c] = c;
      for (c = 10; c > 0; c = c - 1) begin
        t = {$random(seed)} % (c+1);
        nstar = perm2[c]; perm2[c] = perm2[t]; perm2[t] = nstar;
      end
      g = 0;
      for (r_i = 0; r_i < 11; r_i = r_i + 1) begin
        g[120 - (r_i*11 + perm[r_i])]  = 1'b1;
        g[120 - (r_i*11 + perm2[r_i])] = 1'b1;
      end
      try_grid(g);
    end
    for (trial = 540; trial < 564; trial = trial + 1) try_grid(hard[trial-540]);

    $display("");
    $display("  grids compared         %0d", ndone);
    $display("  success mismatches     %0d", mism);
    $display("  O[7:0] mismatches      %0d", mism_o);
    if (mism == 0 && mism_o == 0)
      $display("  RESULT  the split up validator is cycle equivalent to the gates");
    else
      $display("  RESULT  FAILED");
    $finish;
  end
endmodule
