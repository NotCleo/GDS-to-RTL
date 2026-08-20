// ===========================================================================
// validator.v -- the recovered chip, split into the units it is actually built
//                from.
//
// This is puzzle-solution/08_recovered_rtl.v with the one big always block
// broken apart. Nothing about the behaviour changes: every register lives in
// exactly one submodule, every submodule clocks on the same edge, and each one
// reads the others through their pre-edge values, which is what the single
// block did anyway. tb_validator_equiv.v proves it cycle for cycle against the
// gates pulled out of puzzle.gds.
//
// The point of the split is that the five rules of a Star Battle stop being
// interleaved statements and become five named blocks:
//
//   frame_scanner  where in the grid we are, and when the frame ends
//   region_rom     which of the eleven regions a cell belongs to
//   count_bank     eleven saturating counters, used once for columns and
//                  once for regions
//   row_rule       exactly two stars per row
//   touch_rule     no two stars adjacent, diagonals included
//   star_total     twenty two stars in the frame
//   verdict_rom    the ASCII message that follows the verdict
//
// The region map is wired into region_rom as constants because that is how the
// chip has it: eleven region counters whose enables are hardwired ORs of cell
// positions. There is no region map input on the die, so this validator checks
// one specific puzzle and no other. solver.v is the generic half.
// ===========================================================================

// --- where in the grid we are ---------------------------------------------
module frame_scanner #(parameter N = 11) (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       enable,
  input  wire       I,
  output reg  [3:0] col,
  output reg  [3:0] row,
  output reg        done,
  output reg        done_d,
  output wire       running,
  output wire       star,
  output wire       last_col,
  output wire       last_cell,
  output wire       verdict_edge
);
  assign running      = enable & ~done;
  assign last_col     = (col == N-1);
  assign last_cell    = last_col & (row == N-1);
  assign star         = I & running;
  assign verdict_edge = done & ~done_d;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      col <= 4'd0; row <= 4'd0; done <= 1'b0; done_d <= 1'b0;
    end else begin
      done_d <= done;
      if (running) begin
        if (last_col) begin
          col <= 4'd0;
          row <= row + 1'b1;
          if (last_cell) done <= 1'b1;
        end else begin
          col <= col + 1'b1;
        end
      end
    end
  end
endmodule

// --- which region a cell belongs to ---------------------------------------
module region_rom (
  input  wire [3:0] row,
  input  wire [3:0] col,
  output reg  [3:0] region_id
);
  reg [43:0] rowmap;
  always @* begin
    case (row)
      4'd0 : rowmap = 44'h43321100000;
      4'd1 : rowmap = 44'h43322100500;
      4'd2 : rowmap = 44'h43221111500;
      4'd3 : rowmap = 44'h42246661500;
      4'd4 : rowmap = 44'h44444461505;
      4'd5 : rowmap = 44'h77746661555;
      4'd6 : rowmap = 44'h88746111111;
      4'd7 : rowmap = 44'h88746669991;
      4'd8 : rowmap = 44'h8874444a991;
      4'd9 : rowmap = 44'h777444aa911;
      4'd10: rowmap = 44'h4444444a991;
      default: rowmap = 44'h0;
    endcase
    region_id = rowmap[col*4 +: 4];
  end
endmodule

// --- eleven saturating two bit counters -----------------------------------
//
// One bank counts stars per column and a second counts stars per region. They
// saturate at three rather than wrapping, so a column with four stars stays
// distinguishable from a column with none.
module count_bank #(parameter N = 11) (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       bump,
  input  wire [3:0] idx,
  output reg        all_two
);
  reg [1:0] cnt [0:N-1];
  integer i;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (i = 0; i < N; i = i + 1) cnt[i] <= 2'd0;
    end else if (bump && cnt[idx] != 2'd3) begin
      cnt[idx] <= cnt[idx] + 1'b1;
    end
  end

  always @* begin
    all_two = 1'b1;
    for (i = 0; i < N; i = i + 1) if (cnt[i] != 2'd2) all_two = 1'b0;
  end
endmodule

// --- exactly two stars per row --------------------------------------------
//
// One counter serves all eleven rows because it is cleared at every row
// boundary, which is only sound if the grid arrives row major at one cell per
// clock. That single shared counter is what fixed the input format when the
// chip was read out of its gates.
module row_rule (
  input  wire clk,
  input  wire rst_n,
  input  wire running,
  input  wire star,
  input  wire last_col,
  output reg  row_err
);
  reg [1:0] rowcnt;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rowcnt <= 2'd0; row_err <= 1'b0;
    end else if (running) begin
      if (star && rowcnt != 2'd3) rowcnt <= rowcnt + 1'b1;
      if (last_col) begin
        if ((rowcnt + (star && rowcnt != 2'd3)) != 2'd2) row_err <= 1'b1;
        rowcnt <= 2'd0;
      end
    end
  end
endmodule

// --- no two stars touching, diagonals included ----------------------------
//
// Only one row of history is needed. cur_row collects the row being read,
// prev_row holds the one before it, and prev_cell covers the horizontal
// neighbour. At the row boundary prev_row takes cur_row including the star
// arriving in that same cycle, and cur_row starts again empty.
module touch_rule #(parameter N = 11) (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       running,
  input  wire       star,
  input  wire       last_col,
  input  wire [3:0] col,
  output reg        adj_err
);
  reg [N-1:0] prev_row, cur_row;
  reg         prev_cell;

  wire above_l = (col > 0)   ? prev_row[col-1] : 1'b0;
  wire above_c =               prev_row[col];
  wire above_r = (col < N-1) ? prev_row[col+1] : 1'b0;
  wire touches = prev_cell | above_l | above_c | above_r;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prev_row <= {N{1'b0}}; cur_row <= {N{1'b0}};
      prev_cell <= 1'b0; adj_err <= 1'b0;
    end else if (running) begin
      if (star) begin
        cur_row[col] <= 1'b1;
        if (touches) adj_err <= 1'b1;
      end
      prev_cell <= star;
      if (last_col) begin
        prev_cell <= 1'b0;
        prev_row  <= cur_row | (star << col);
        cur_row   <= {N{1'b0}};
      end
    end
  end
endmodule

// --- twenty two stars in the frame ----------------------------------------
module star_total (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       star,
  output reg  [7:0] total
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) total <= 8'd0;
    else if (star) total <= total + 1'b1;
  end
endmodule

// --- the ASCII verdict ----------------------------------------------------
//
// Five messages, chosen once when the frame ends and then streamed one
// character per clock. The fifth exists only to name the rule a grid broke
// when it got every count right and still touched.
module verdict_rom (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       verdict_edge,
  input  wire       counts_ok,
  input  wire       adj_err,
  input  wire [7:0] total,
  output wire [7:0] O
);
  localparam MAXC = 16;

  reg [7:0] rom [0:MAXC-1];
  reg [4:0] optr, mlen;
  reg       emitting;
  reg [7:0] o_q;
  integer   i, j;

  always @* begin
    if      (total == 8'd0)        j = 0;
    else if (total == 8'd121)      j = 1;
    else if (counts_ok & ~adj_err) j = 2;
    else if (counts_ok &  adj_err) j = 4;
    else                           j = 3;
    case (j)
      0: mlen = 9;  1: mlen = 8;  2: mlen = 15;  4: mlen = 13;  default: mlen = 9;
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
      4: begin rom[0]="T"; rom[1]="W"; rom[2]="O"; rom[3]=" "; rom[4]="N";
               rom[5]="O"; rom[6]="T"; rom[7]=" "; rom[8]="T"; rom[9]="O";
               rom[10]="U"; rom[11]="C"; rom[12]="H"; end
      default: begin rom[0]="T"; rom[1]="R"; rom[2]="Y"; rom[3]=" ";
               rom[4]="A"; rom[5]="G"; rom[6]="A"; rom[7]="I"; rom[8]="N"; end
    endcase
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      optr <= 5'd0; emitting <= 1'b0; o_q <= 8'h00;
    end else if (verdict_edge) begin
      emitting <= 1'b1; optr <= 5'd1; o_q <= rom[0];
    end else if (emitting && optr < mlen) begin
      o_q  <= rom[optr];
      optr <= optr + 1'b1;
    end else begin
      o_q <= 8'h00;
    end
  end

  assign O = o_q;
endmodule

// --- the chip -------------------------------------------------------------
module validator #(parameter N = 11) (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       I,
  input  wire       enable,
  output wire       success,
  output wire [7:0] O
);
  wire [3:0] col, row, region_id;
  wire       done, done_d, running, star, last_col, last_cell, verdict_edge;
  wire       cols_two, regs_two, row_err, adj_err;
  wire [7:0] total;

  frame_scanner #(N) U_SCAN (
    .clk(clk), .rst_n(rst_n), .enable(enable), .I(I),
    .col(col), .row(row), .done(done), .done_d(done_d),
    .running(running), .star(star), .last_col(last_col),
    .last_cell(last_cell), .verdict_edge(verdict_edge));

  region_rom U_MAP (.row(row), .col(col), .region_id(region_id));

  count_bank #(N) U_COLS (.clk(clk), .rst_n(rst_n), .bump(star),
                          .idx(col), .all_two(cols_two));

  count_bank #(N) U_REGS (.clk(clk), .rst_n(rst_n), .bump(star),
                          .idx(region_id), .all_two(regs_two));

  row_rule U_ROW (.clk(clk), .rst_n(rst_n), .running(running),
                  .star(star), .last_col(last_col), .row_err(row_err));

  touch_rule #(N) U_TOUCH (.clk(clk), .rst_n(rst_n), .running(running),
                           .star(star), .last_col(last_col), .col(col),
                           .adj_err(adj_err));

  star_total U_TOTAL (.clk(clk), .rst_n(rst_n), .star(star), .total(total));

  wire all_ok    = cols_two & regs_two;
  wire counts_ok = ~row_err & (total == 8'd22) & all_ok;

  reg succ_q;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)           succ_q <= 1'b0;
    else if (verdict_edge) succ_q <= counts_ok & ~adj_err;
  end
  assign success = succ_q;

  verdict_rom U_MSG (.clk(clk), .rst_n(rst_n), .verdict_edge(verdict_edge),
                     .counts_ok(counts_ok), .adj_err(adj_err), .total(total),
                     .O(O));
endmodule
