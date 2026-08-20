`timescale 1ns/1ps
// ===========================================================================
// tb_full_solver.v -- the whole pipeline, region map in, verdict out
//
// The only thing this testbench knows is the region map. It does not know the
// answer, it does not tell the solver anything else, and it never touches the
// validator: the solver drives it through the same four pins the die exposes.
//
// What it checks
//   the solver finishes and does not report the puzzle unsatisfiable
//   the frame it produced is a legal Star Battle for the map that went in
//   that frame is the one the SAT solver found from the gates
//   solved lands on edge 121+x and success on edge 244+x, as drawn
//   O[7:0] spells the verdict the chip prints for a correct grid
// ===========================================================================
module tb_full_solver;
  localparam N = 11;

  reg  clk = 0, rst_n = 0, enable = 0;
  reg  [3:0] region_in = 4'd0;
  wire success, solved, unsat;
  wire [7:0] O;
  wire [31:0] steps;

  full_solver #(N) DUT (
    .clk(clk), .rst_n(rst_n), .enable(enable), .region_in(region_in),
    .success(success), .O(O), .solved(solved), .unsat(unsat), .steps(steps));

  always #5 clk = ~clk;

  integer cyc;
  always @(posedge clk) begin
    if (!rst_n) cyc <= 0;
    else        cyc <= cyc + 1;
  end

  // The map the die was built around. Nibble c of row r is the region of cell
  // (r,c), letters A to K as 0 to 10. This is stimulus here, nothing more: the
  // solver has never seen it before edge 1.
  reg [43:0] rowmap [0:N-1];
  reg [3:0]  map    [0:120];
  reg [120:0] frame;
  reg [120:0] key = 121'b0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000;
  reg [8*16-1:0] msg;

  integer i, r, c, g, errs, t_solved, t_success, x;
  reg [7:0] letter;
  integer rcnt [0:N-1];
  integer ccnt [0:N-1];
  integer gcnt [0:N-1];
  reg [10:0] grid [0:N-1];

  initial begin
    rowmap[0]  = 44'h43321100000;
    rowmap[1]  = 44'h43322100500;
    rowmap[2]  = 44'h43221111500;
    rowmap[3]  = 44'h42246661500;
    rowmap[4]  = 44'h44444461505;
    rowmap[5]  = 44'h77746661555;
    rowmap[6]  = 44'h88746111111;
    rowmap[7]  = 44'h88746669991;
    rowmap[8]  = 44'h8874444a991;
    rowmap[9]  = 44'h777444aa911;
    rowmap[10] = 44'h4444444a991;
    for (r = 0; r < N; r = r + 1)
      for (c = 0; c < N; c = c + 1)
        map[r*N + c] = rowmap[r][c*4 +: 4];
  end

  initial begin
    $dumpfile("full_solver.vcd");
    // Named one at a time rather than by scope. A scope dump would drag in the
    // loop temporaries inside row_candidates, which take 45 values per clock
    // and turn a readable trace into a hundred megabytes of nothing.
    $dumpvars(0, tb_full_solver.clk, tb_full_solver.rst_n,
                 tb_full_solver.enable, tb_full_solver.region_in,
                 tb_full_solver.cyc);
    $dumpvars(0, DUT.I, DUT.val_rst_n, DUT.val_en, DUT.feeding, DUT.feed,
                 DUT.armed, DUT.solved, DUT.unsat, DUT.success, DUT.O);
    $dumpvars(0, DUT.U_SOLVER.loaded, DUT.U_SOLVER.init, DUT.U_SOLVER.step,
                 DUT.U_SOLVER.have, DUT.U_SOLVER.pick_k,
                 DUT.U_SOLVER.pick_cmask);
    $dumpvars(0, DUT.U_SOLVER.U_LOAD.lrow, DUT.U_SOLVER.U_LOAD.lcol);
    $dumpvars(0, DUT.U_SOLVER.U_STACK.row, DUT.U_SOLVER.U_STACK.resume,
                 DUT.U_SOLVER.U_STACK.prev_mask,
                 DUT.U_SOLVER.U_STACK.colcnt_flat,
                 DUT.U_SOLVER.U_STACK.regcnt_flat,
                 DUT.U_SOLVER.U_STACK.avail_flat,
                 DUT.U_SOLVER.U_STACK.steps,
                 DUT.U_SOLVER.U_STACK.solution);
    $dumpvars(0, DUT.U_VALIDATOR.running, DUT.U_VALIDATOR.star,
                 DUT.U_VALIDATOR.col, DUT.U_VALIDATOR.row,
                 DUT.U_VALIDATOR.region_id, DUT.U_VALIDATOR.done,
                 DUT.U_VALIDATOR.verdict_edge, DUT.U_VALIDATOR.cols_two,
                 DUT.U_VALIDATOR.regs_two, DUT.U_VALIDATOR.row_err,
                 DUT.U_VALIDATOR.adj_err, DUT.U_VALIDATOR.total,
                 DUT.U_VALIDATOR.counts_ok, DUT.U_VALIDATOR.succ_q);
    $dumpvars(0, DUT.U_VALIDATOR.U_TOUCH.prev_row,
                 DUT.U_VALIDATOR.U_TOUCH.cur_row,
                 DUT.U_VALIDATOR.U_TOUCH.prev_cell,
                 DUT.U_VALIDATOR.U_TOUCH.touches,
                 DUT.U_VALIDATOR.U_ROW.rowcnt);
    $dumpvars(0, DUT.U_VALIDATOR.U_MSG.emitting, DUT.U_VALIDATOR.U_MSG.optr,
                 DUT.U_VALIDATOR.U_MSG.mlen, DUT.U_VALIDATOR.U_MSG.o_q);
  end

  initial begin
    errs = 0; t_solved = 0; t_success = 0;

    $display("");
    $display("SOLVER PLUS VALIDATOR, 11x11 STAR BATTLE");
    $display("======================================================================");
    $display("");

    rst_n = 0; enable = 0;
    @(posedge clk); @(posedge clk); @(negedge clk);
    rst_n = 1; enable = 1;

    // --- phase 1, 121 clocks: the region map goes in ---
    for (i = 0; i < 121; i = i + 1) begin
      region_in = map[i];
      @(posedge clk); @(negedge clk);
    end
    region_in = 4'd0;
    if (cyc != 121) begin
      $display("  FAIL  region map took %0d clocks, expected 121", cyc);
      errs = errs + 1;
    end else begin
      $display("  edge %0d      region map loaded, 121 cells", cyc);
    end

    // --- phase 2, x clocks: the search ---
    while (!solved && !unsat && cyc < 400000) @(negedge clk);
    t_solved = cyc;
    x = t_solved - 121;
    if (unsat) begin
      $display("  FAIL  the solver reports the puzzle unsatisfiable");
      errs = errs + 1;
    end else if (!solved) begin
      $display("  FAIL  the solver never finished");
      errs = errs + 1;
    end else begin
      $display("  edge %0d    solved, x = %0d clocks (1 to set up, %0d to search)",
               t_solved, x, steps);
    end

    frame = DUT.U_SOLVER.solution;

    // --- phase 3 and 4: handover, then 121 clocks of the frame ---
    while (!success && cyc < 400000) @(negedge clk);
    t_success = cyc;

    msg = 0;
    for (i = 0; i < 15; i = i + 1) begin
      msg = {msg[8*15-1:0], O};
      @(negedge clk);
    end

    // --- what the solver actually produced ---
    for (r = 0; r < N; r = r + 1) begin
      grid[r] = 11'd0;
      for (c = 0; c < N; c = c + 1)
        grid[r][c] = frame[120 - (r*N + c)];
    end

    $display("  edge %0d    success high, O reads \"%0s\"", t_success, msg);
    $display("");
    $display("THE FRAME THE SOLVER BUILT");
    $display("----------------------------------------------------------------------");
    for (r = 0; r < N; r = r + 1) begin
      $write("   ");
      for (c = 0; c < N; c = c + 1)
        $write(" %0s", grid[r][c] ? "*" : ".");
      $write("\n");
    end
    $display("");

    // --- is it a legal Star Battle for the map that went in ---
    for (i = 0; i < N; i = i + 1) begin
      rcnt[i] = 0; ccnt[i] = 0; gcnt[i] = 0;
    end
    for (r = 0; r < N; r = r + 1)
      for (c = 0; c < N; c = c + 1)
        if (grid[r][c]) begin
          rcnt[r] = rcnt[r] + 1;
          ccnt[c] = ccnt[c] + 1;
          g = map[r*N + c];
          gcnt[g] = gcnt[g] + 1;
        end
    for (i = 0; i < N; i = i + 1) begin
      if (rcnt[i] != 2) begin
        $display("  FAIL  row %0d holds %0d stars", i, rcnt[i]); errs = errs + 1;
      end
      if (ccnt[i] != 2) begin
        $display("  FAIL  column %0d holds %0d stars", i, ccnt[i]); errs = errs + 1;
      end
      if (gcnt[i] != 2) begin
        letter = 8'h41 + i[7:0];
        $display("  FAIL  region %0s holds %0d stars", letter, gcnt[i]);
        errs = errs + 1;
      end
    end
    for (r = 0; r < N; r = r + 1)
      for (c = 0; c < N; c = c + 1)
        if (grid[r][c]) begin
          if (c < N-1 && grid[r][c+1]) begin
            $display("  FAIL  stars touch at row %0d columns %0d and %0d", r, c, c+1);
            errs = errs + 1;
          end
          if (r < N-1) begin
            if (grid[r+1][c]) begin
              $display("  FAIL  stars touch vertically at column %0d rows %0d and %0d",
                       c, r, r+1);
              errs = errs + 1;
            end
            if (c > 0 && grid[r+1][c-1]) begin
              $display("  FAIL  stars touch diagonally at (%0d,%0d) and (%0d,%0d)",
                       r, c, r+1, c-1);
              errs = errs + 1;
            end
            if (c < N-1 && grid[r+1][c+1]) begin
              $display("  FAIL  stars touch diagonally at (%0d,%0d) and (%0d,%0d)",
                       r, c, r+1, c+1);
              errs = errs + 1;
            end
          end
        end

    $display("CHECKS");
    $display("----------------------------------------------------------------------");
    $display("  two per row, two per column, two per region, nothing touching");

    if (frame !== key) begin
      $display("  FAIL  the frame is not the one SAT read out of the gates");
      errs = errs + 1;
    end else begin
      $display("  the frame equals the 121 bit key SAT found in the netlist");
    end

    if (t_success != 244 + x) begin
      $display("  FAIL  success on edge %0d, the drawing says %0d", t_success, 244 + x);
      errs = errs + 1;
    end else begin
      $display("  success on edge %0d, which is 244 + x with x = %0d", t_success, x);
    end

    if (msg !== "(* TWO STARS *)") begin
      $display("  FAIL  O spells \"%0s\"", msg);
      errs = errs + 1;
    end else begin
      $display("  O[7:0] spells (* TWO STARS *), the chip's word for a correct grid");
    end

    $display("");
    if (errs == 0)
      $display("RESULT  the pipeline solves the puzzle and the chip accepts it");
    else
      $display("RESULT  FAILED, %0d checks", errs);
    $display("");
    $finish;
  end
endmodule
