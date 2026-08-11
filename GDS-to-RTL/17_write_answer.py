#!/usr/bin/env python3
"""
Render the final human-readable answer files from the recovered region map and
the solution bitstream.

Usage: python 17_write_answer.py <regions.json> <solution_bits> <outdir>
"""
import sys, json, os, collections

N = 11


def main():
    regions, sol, outdir = sys.argv[1], sys.argv[2][:121], sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    reg = {int(k): v for k, v in json.load(open(regions))["region_of_cell"].items()}

    L = ["THE PUZZLE (11x11 Star Battle / 'Two Not Touch')", "=" * 52,
         "Place 2 stars in every row, every column, and every lettered region.",
         "No two stars may touch, not even diagonally.", "",
         "REGION MAP", "     " + " ".join(str(c) for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + " ".join(reg[r * N + c] for c in range(N)))
    L += ["", "THE UNIQUE SOLUTION   (* = star)",
          "     " + " ".join(str(c) for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + " ".join("*" if sol[r * N + c] == "1" else "."
                                         for c in range(N)))
    L += ["", "SOLUTION OVERLAID ON THE REGIONS",
          "     " + " ".join(str(c) for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + " ".join("*" if sol[r * N + c] == "1"
                                         else reg[r * N + c].lower()
                                         for c in range(N)))
    L += ["", "STAR COORDINATES (row, col), 0-indexed"]
    for r in range(N):
        L.append(f"  row {r:2d}: cols {[c for c in range(N) if sol[r*N+c]=='1']}")
    rc = collections.Counter(reg[k] for k in range(N * N) if sol[k] == "1")
    L += ["", "CHECKS",
          "  row sums : " + " ".join(str(sum(int(sol[r*N+c]) for c in range(N)))
                                     for r in range(N)),
          "  col sums : " + " ".join(str(sum(int(sol[r*N+c]) for r in range(N)))
                                     for c in range(N)),
          "  region   : " + " ".join(f"{k}={rc[k]}" for k in sorted(rc)),
          f"  total stars: {sol.count('1')}"]
    open(f"{outdir}/solution_grid.txt", "w").write("\n".join(L) + "\n")

    S = ["INPUT SEQUENCE TO UNLOCK THE CHIP", "=" * 40, "",
         "  rst_n : hold low >=2 clocks, then release high",
         "  enable: hold HIGH for the entire run",
         "  I     : one grid cell per rising clock edge, ROW-MAJOR",
         "          (row 0 col 0 first, row 10 col 10 last = 121 bits)", "",
         "  success rises on the FIRST clock after the 121st cell -- i.e. the",
         "  122nd enabled rising edge -- and then latches.",
         "  O[7:0] streams the ASCII verdict from that same edge, one character",
         "  per clock, 15 characters (enabled clocks 122..136).", "",
         "I, cycles 1..121 (the grid, row-major):", "  " + sol, "",
         "Same 121 bits split by row:"]
    for r in range(N):
        S.append(f"  row {r:2d}: {sol[r*N:(r+1)*N]}")
    S += ["", "OUTPUT: (* TWO STARS *)"]
    open(f"{outdir}/input_sequence.txt", "w").write("\n".join(S) + "\n")
    print(f"wrote {outdir}/solution_grid.txt and {outdir}/input_sequence.txt")


if __name__ == "__main__":
    main()
