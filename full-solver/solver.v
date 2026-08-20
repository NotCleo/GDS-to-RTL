// ===========================================================================
// solver.v -- an 11x11 Star Battle solver in hardware
//
// The chip in puzzle.gds only checks. Its eleven region counters have their
// enables wired to fixed cell positions, so it knows one region map and has no
// port to be told another. This is the half that was missing: feed it a region
// map and it produces the 121 bit frame that makes that chip say success.
//
// THE SEARCH
//
// A row of a Star Battle holds exactly two stars and they cannot touch, so a
// row is one of the 45 column pairs (a,b) with b >= a+2. The search is a depth
// first walk over rows, one row per level, and the whole state is
//
//   colcnt[c]   stars placed so far in column c
//   regcnt[g]   stars placed so far in region g
//   avail[g]    cells of region g still to come, in rows below this one
//   prev_mask   the column mask of the row above
//
// All 45 pairs are tested at once, which is what makes this worth building in
// hardware rather than in software: a clock either descends a level or backs up
// one, never merely tries a candidate. The plain version of this search, one
// candidate per clock, would be about 45 times slower.
//
// THE PRUNING
//
// Bounds alone, meaning no column or region over two, leaves 1.2 million
// clocks. What collapses it is asking whether a region can still be finished:
// if region g needs n more stars and only has fewer than n cells left below,
// this branch is already dead. That single test takes it to 10125 clocks.
//
// It is applied without looping over candidates. A region that needs at least
// one star from this row is short by one, and a region that needs two is short
// by two, so with
//
//   rshort1   regions that must be touched by this row
//   rshort2   regions that must take both of this row's stars
//
// a candidate survives when rshort1 lies inside the two regions it touches and
// rshort2 lies inside the region it doubles up on. Two mask compares, shared by
// all 45 candidates. The same trick covers columns against the rows remaining.
//
// Sharpening avail to exclude the cells the row above already blocks would take
// it to 6941 clocks, at the price of eleven population counts per candidate.
// That is not a trade worth making here.
// ===========================================================================

// --- the region map arrives one cell per clock ----------------------------
//
// 121 cells, row major, four bits each, exactly the order the validator reads
// its grid in. Alongside the map it counts cells per row per region, which is
// what the availability pruning runs on.
module region_loader #(parameter N = 11) (
  input  wire         clk,
  input  wire         rst_n,
  input  wire         enable,
  input  wire [3:0]   region_in,
  output reg  [483:0] region_flat,
  output reg  [483:0] rowreg_flat,
  output reg  [54:0]  total_flat,
  output wire         loaded,
  output reg  [3:0]   lrow,
  output reg  [3:0]   lcol
);
  assign loaded = (lrow == N);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lrow <= 4'd0; lcol <= 4'd0;
      region_flat <= 484'd0; rowreg_flat <= 484'd0; total_flat <= 55'd0;
    end else if (enable && !loaded) begin
      region_flat[lrow*44 + lcol*4 +: 4] <= region_in;
      rowreg_flat[lrow*44 + region_in*4 +: 4] <=
        rowreg_flat[lrow*44 + region_in*4 +: 4] + 1'b1;
      total_flat[region_in*5 +: 5] <= total_flat[region_in*5 +: 5] + 1'b1;
      if (lcol == N-1) begin
        lcol <= 4'd0;
        lrow <= lrow + 1'b1;
      end else begin
        lcol <= lcol + 1'b1;
      end
    end
  end
endmodule

// --- all 45 candidate rows, judged at once --------------------------------
//
// Combinational. Given the search state it reports the lowest numbered legal
// pair at or after resume, together with the column mask and the per region
// increment that choosing it would apply. have is low when the row is dead and
// the search must back up.
module row_candidates #(parameter N = 11) (
  input  wire [483:0] region_flat,
  input  wire [3:0]   row,
  input  wire [5:0]   resume,
  input  wire [10:0]  prev_mask,
  input  wire [21:0]  colcnt_flat,
  input  wire [21:0]  regcnt_flat,
  input  wire [54:0]  avail_flat,
  output reg          have,
  output reg  [5:0]   pick_k,
  output reg  [10:0]  pick_cmask,
  output reg  [21:0]  pick_rdelta
);
  wire [3:0]  rsel   = (row > N-1) ? N-1 : row;
  wire [43:0] rowids = region_flat[rsel*44 +: 44];
  wire [10:0] spread = prev_mask | (prev_mask << 1) | (prev_mask >> 1);

  reg [10:0] cfull, cshort1, cshort2;
  reg [10:0] rfull2, rshort1, rshort2;
  reg [10:0] m, rm, sm;
  reg [3:0]  ga, gb, pick_ga, pick_gb;
  reg [5:0]  k;
  reg        ok;
  integer    a, b, c, gi, left;

  always @* begin
    left = N - 1 - row;
    for (c = 0; c < N; c = c + 1) begin
      cfull[c]   = (colcnt_flat[c*2 +: 2] >= 2'd2);
      cshort1[c] = ((2 - colcnt_flat[c*2 +: 2]) > left);
      cshort2[c] = ((2 - colcnt_flat[c*2 +: 2]) > left + 1);
    end
    for (gi = 0; gi < N; gi = gi + 1) begin
      rfull2[gi]  = (regcnt_flat[gi*2 +: 2] >= 2'd2);
      rshort1[gi] = ((2 - regcnt_flat[gi*2 +: 2]) >  avail_flat[gi*5 +: 5]);
      rshort2[gi] = ((2 - regcnt_flat[gi*2 +: 2]) >  avail_flat[gi*5 +: 5] + 1);
    end

    have = 1'b0;
    pick_k = 6'd0;
    pick_cmask = 11'd0;
    pick_ga = 4'd0;
    pick_gb = 4'd0;
    k = 6'd0;
    for (a = 0; a < N; a = a + 1) begin
      for (b = a + 2; b < N; b = b + 1) begin
        m  = (11'd1 << a) | (11'd1 << b);
        ga = rowids[a*4 +: 4];
        gb = rowids[b*4 +: 4];
        rm = (11'd1 << ga) | (11'd1 << gb);
        sm = (ga == gb) ? (11'd1 << ga) : 11'd0;
        ok = (k >= resume)
          && ((m  & spread)   == 11'd0)
          && ((m  & cfull)    == 11'd0)
          && ((cshort1 & ~m)  == 11'd0)
          && (cshort2         == 11'd0)
          && ((rm & rfull2)   == 11'd0)
          && ((ga != gb) || (regcnt_flat[ga*2 +: 2] == 2'd0))
          && ((rshort1 & ~rm) == 11'd0)
          && ((rshort2 & ~sm) == 11'd0);
        if (ok && !have) begin
          have = 1'b1;
          pick_k = k;
          pick_cmask = m;
          pick_ga = ga;
          pick_gb = gb;
        end
        k = k + 1'b1;
      end
    end

    pick_rdelta = 22'd0;
    if (have) begin
      pick_rdelta[pick_ga*2 +: 2] = 2'd1;
      pick_rdelta[pick_gb*2 +: 2] = pick_rdelta[pick_gb*2 +: 2] + 2'd1;
    end
  end
endmodule

// --- the depth first stack ------------------------------------------------
//
// Eleven levels, one per row. A clock either pushes the chosen pair and drops a
// level, or pops the level above and resumes just past the pair that failed.
// Everything a pop has to undo is on the stack, so backing up costs the same
// one clock as going forward.
module search_stack #(parameter N = 11) (
  input  wire         clk,
  input  wire         rst_n,
  input  wire         init,
  input  wire         step,
  input  wire [483:0] rowreg_flat,
  input  wire [54:0]  total_flat,
  input  wire         have,
  input  wire [5:0]   pick_k,
  input  wire [10:0]  pick_cmask,
  input  wire [21:0]  pick_rdelta,
  output reg  [3:0]   row,
  output reg  [5:0]   resume,
  output reg  [21:0]  colcnt_flat,
  output reg  [21:0]  regcnt_flat,
  output reg  [54:0]  avail_flat,
  output reg  [10:0]  prev_mask,
  output reg          solved,
  output reg          unsat,
  output reg  [120:0] solution,
  output reg  [31:0]  steps
);
  reg [5:0]  st_k      [0:N-1];
  reg [10:0] st_cmask  [0:N-1];
  reg [21:0] st_rdelta [0:N-1];

  integer i, c, gi;
  reg [3:0] up;

  always @* begin
    prev_mask = (row == 4'd0) ? 11'd0 : st_cmask[row-1];
  end

  always @* begin
    solution = 121'd0;
    for (i = 0; i < N; i = i + 1)
      for (c = 0; c < N; c = c + 1)
        solution[120 - (i*N + c)] = st_cmask[i][c];
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      row <= 4'd0; resume <= 6'd0; solved <= 1'b0; unsat <= 1'b0;
      colcnt_flat <= 22'd0; regcnt_flat <= 22'd0; avail_flat <= 55'd0;
      steps <= 32'd0;
      for (i = 0; i < N; i = i + 1) begin
        st_k[i] <= 6'd0; st_cmask[i] <= 11'd0; st_rdelta[i] <= 22'd0;
      end
    end else if (init) begin
      row <= 4'd0; resume <= 6'd0; solved <= 1'b0; unsat <= 1'b0;
      colcnt_flat <= 22'd0; regcnt_flat <= 22'd0;
      steps <= 32'd0;
      for (gi = 0; gi < N; gi = gi + 1)
        avail_flat[gi*5 +: 5] <= total_flat[gi*5 +: 5]
                               - rowreg_flat[gi*4 +: 4];
      for (i = 0; i < N; i = i + 1) begin
        st_k[i] <= 6'd0; st_cmask[i] <= 11'd0; st_rdelta[i] <= 22'd0;
      end
    end else if (step) begin
      steps <= steps + 1'b1;
      if (have) begin
        st_k[row]      <= pick_k;
        st_cmask[row]  <= pick_cmask;
        st_rdelta[row] <= pick_rdelta;
        for (c = 0; c < N; c = c + 1)
          colcnt_flat[c*2 +: 2] <= colcnt_flat[c*2 +: 2] + pick_cmask[c];
        for (gi = 0; gi < N; gi = gi + 1)
          regcnt_flat[gi*2 +: 2] <= regcnt_flat[gi*2 +: 2]
                                  + pick_rdelta[gi*2 +: 2];
        if (row < N-1)
          for (gi = 0; gi < N; gi = gi + 1)
            avail_flat[gi*5 +: 5] <= avail_flat[gi*5 +: 5]
                                   - rowreg_flat[(row+1)*44 + gi*4 +: 4];
        row    <= row + 1'b1;
        resume <= 6'd0;
        if (row == N-1) solved <= 1'b1;
      end else if (row == 4'd0) begin
        unsat <= 1'b1;
      end else begin
        up = row - 1'b1;
        for (c = 0; c < N; c = c + 1)
          colcnt_flat[c*2 +: 2] <= colcnt_flat[c*2 +: 2] - st_cmask[up][c];
        for (gi = 0; gi < N; gi = gi + 1)
          regcnt_flat[gi*2 +: 2] <= regcnt_flat[gi*2 +: 2]
                                  - st_rdelta[up][gi*2 +: 2];
        for (gi = 0; gi < N; gi = gi + 1)
          avail_flat[gi*5 +: 5] <= avail_flat[gi*5 +: 5]
                                 + rowreg_flat[row*44 + gi*4 +: 4];
        row    <= up;
        resume <= st_k[up] + 1'b1;
      end
    end
  end
endmodule

// --- the solver -----------------------------------------------------------
//
// Load for 121 clocks, spend one clock setting the search up, then search. The
// solution appears on solution[120:0] with bit 120 as row 0 column 0, the same
// order the validator wants it fed in.
module solver #(parameter N = 11) (
  input  wire         clk,
  input  wire         rst_n,
  input  wire         enable,
  input  wire [3:0]   region_in,
  output wire         solved,
  output wire         unsat,
  output wire [120:0] solution,
  output wire [31:0]  steps
);
  wire [483:0] region_flat, rowreg_flat;
  wire [54:0]  total_flat;
  wire         loaded;
  wire [3:0]   lrow, lcol;
  reg          loaded_d;

  wire [3:0]  row;
  wire [5:0]  resume;
  wire [21:0] colcnt_flat, regcnt_flat;
  wire [54:0] avail_flat;
  wire [10:0] prev_mask;
  wire        have;
  wire [5:0]  pick_k;
  wire [10:0] pick_cmask;
  wire [21:0] pick_rdelta;

  region_loader #(N) U_LOAD (
    .clk(clk), .rst_n(rst_n), .enable(enable), .region_in(region_in),
    .region_flat(region_flat), .rowreg_flat(rowreg_flat),
    .total_flat(total_flat), .loaded(loaded), .lrow(lrow), .lcol(lcol));

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) loaded_d <= 1'b0;
    else        loaded_d <= loaded;
  end

  wire init = loaded & ~loaded_d;
  wire step = enable & loaded & loaded_d & ~solved & ~unsat;

  row_candidates #(N) U_CAND (
    .region_flat(region_flat), .row(row), .resume(resume),
    .prev_mask(prev_mask), .colcnt_flat(colcnt_flat),
    .regcnt_flat(regcnt_flat), .avail_flat(avail_flat),
    .have(have), .pick_k(pick_k), .pick_cmask(pick_cmask),
    .pick_rdelta(pick_rdelta));

  search_stack #(N) U_STACK (
    .clk(clk), .rst_n(rst_n), .init(init), .step(step),
    .rowreg_flat(rowreg_flat), .total_flat(total_flat),
    .have(have), .pick_k(pick_k), .pick_cmask(pick_cmask),
    .pick_rdelta(pick_rdelta),
    .row(row), .resume(resume), .colcnt_flat(colcnt_flat),
    .regcnt_flat(regcnt_flat), .avail_flat(avail_flat),
    .prev_mask(prev_mask), .solved(solved), .unsat(unsat),
    .solution(solution), .steps(steps));
endmodule
