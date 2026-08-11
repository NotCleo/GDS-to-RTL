// ===========================================================================
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
//   A A A A A B B C D D E
//   A A F A A B C C D D E
//   A A F B B B B C C D E
//   A A F B G G G E C C E
//   F A F B G E E E E E E
//   F F F B G G G E H H H
//   B B B B B B G E H I I
//   B J J J G G G E H I I
//   B J J K E E E E H I I
//   B B J K K E E E H H H
//   B J J K E E E E E E E
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
      11'd0: region_id = 4'd0;
      11'd1: region_id = 4'd0;
      11'd2: region_id = 4'd0;
      11'd3: region_id = 4'd0;
      11'd4: region_id = 4'd0;
      11'd5: region_id = 4'd1;
      11'd6: region_id = 4'd1;
      11'd7: region_id = 4'd2;
      11'd8: region_id = 4'd3;
      11'd9: region_id = 4'd3;
      11'd10: region_id = 4'd4;
      11'd11: region_id = 4'd0;
      11'd12: region_id = 4'd0;
      11'd13: region_id = 4'd5;
      11'd14: region_id = 4'd0;
      11'd15: region_id = 4'd0;
      11'd16: region_id = 4'd1;
      11'd17: region_id = 4'd2;
      11'd18: region_id = 4'd2;
      11'd19: region_id = 4'd3;
      11'd20: region_id = 4'd3;
      11'd21: region_id = 4'd4;
      11'd22: region_id = 4'd0;
      11'd23: region_id = 4'd0;
      11'd24: region_id = 4'd5;
      11'd25: region_id = 4'd1;
      11'd26: region_id = 4'd1;
      11'd27: region_id = 4'd1;
      11'd28: region_id = 4'd1;
      11'd29: region_id = 4'd2;
      11'd30: region_id = 4'd2;
      11'd31: region_id = 4'd3;
      11'd32: region_id = 4'd4;
      11'd33: region_id = 4'd0;
      11'd34: region_id = 4'd0;
      11'd35: region_id = 4'd5;
      11'd36: region_id = 4'd1;
      11'd37: region_id = 4'd6;
      11'd38: region_id = 4'd6;
      11'd39: region_id = 4'd6;
      11'd40: region_id = 4'd4;
      11'd41: region_id = 4'd2;
      11'd42: region_id = 4'd2;
      11'd43: region_id = 4'd4;
      11'd44: region_id = 4'd5;
      11'd45: region_id = 4'd0;
      11'd46: region_id = 4'd5;
      11'd47: region_id = 4'd1;
      11'd48: region_id = 4'd6;
      11'd49: region_id = 4'd4;
      11'd50: region_id = 4'd4;
      11'd51: region_id = 4'd4;
      11'd52: region_id = 4'd4;
      11'd53: region_id = 4'd4;
      11'd54: region_id = 4'd4;
      11'd55: region_id = 4'd5;
      11'd56: region_id = 4'd5;
      11'd57: region_id = 4'd5;
      11'd58: region_id = 4'd1;
      11'd59: region_id = 4'd6;
      11'd60: region_id = 4'd6;
      11'd61: region_id = 4'd6;
      11'd62: region_id = 4'd4;
      11'd63: region_id = 4'd7;
      11'd64: region_id = 4'd7;
      11'd65: region_id = 4'd7;
      11'd66: region_id = 4'd1;
      11'd67: region_id = 4'd1;
      11'd68: region_id = 4'd1;
      11'd69: region_id = 4'd1;
      11'd70: region_id = 4'd1;
      11'd71: region_id = 4'd1;
      11'd72: region_id = 4'd6;
      11'd73: region_id = 4'd4;
      11'd74: region_id = 4'd7;
      11'd75: region_id = 4'd8;
      11'd76: region_id = 4'd8;
      11'd77: region_id = 4'd1;
      11'd78: region_id = 4'd9;
      11'd79: region_id = 4'd9;
      11'd80: region_id = 4'd9;
      11'd81: region_id = 4'd6;
      11'd82: region_id = 4'd6;
      11'd83: region_id = 4'd6;
      11'd84: region_id = 4'd4;
      11'd85: region_id = 4'd7;
      11'd86: region_id = 4'd8;
      11'd87: region_id = 4'd8;
      11'd88: region_id = 4'd1;
      11'd89: region_id = 4'd9;
      11'd90: region_id = 4'd9;
      11'd91: region_id = 4'd10;
      11'd92: region_id = 4'd4;
      11'd93: region_id = 4'd4;
      11'd94: region_id = 4'd4;
      11'd95: region_id = 4'd4;
      11'd96: region_id = 4'd7;
      11'd97: region_id = 4'd8;
      11'd98: region_id = 4'd8;
      11'd99: region_id = 4'd1;
      11'd100: region_id = 4'd1;
      11'd101: region_id = 4'd9;
      11'd102: region_id = 4'd10;
      11'd103: region_id = 4'd10;
      11'd104: region_id = 4'd4;
      11'd105: region_id = 4'd4;
      11'd106: region_id = 4'd4;
      11'd107: region_id = 4'd7;
      11'd108: region_id = 4'd7;
      11'd109: region_id = 4'd7;
      11'd110: region_id = 4'd1;
      11'd111: region_id = 4'd9;
      11'd112: region_id = 4'd9;
      11'd113: region_id = 4'd10;
      11'd114: region_id = 4'd4;
      11'd115: region_id = 4'd4;
      11'd116: region_id = 4'd4;
      11'd117: region_id = 4'd4;
      11'd118: region_id = 4'd4;
      11'd119: region_id = 4'd4;
      11'd120: region_id = 4'd4;
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
