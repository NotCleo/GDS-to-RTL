#!/usr/bin/env python3
"""
Decode the hidden message in the *inputs* of example_inputs.vcd.

Jane Street ship a waveform of "some inputs being fed to the design
(unfortunately, not the correct inputs to make success go high!)". They are not
a failed solve attempt. They are a message.

The header says so outright, if you open the file in a text editor first. Its
$version field reads "Leave no stone unturned!", and its $date is
"Sat Dec 31 23:59:60 2016", a real leap second rather than a real timestamp.

What gives the payload away, before decoding anything:
  * both frames contain exactly 38 stars -- identical, so not random;
  * columns 7..10 are empty in every row of both frames.

Eleven rows, seven usable columns, and seven bits is exactly one ASCII
character. Read each row as a 7-bit value with column 0 as the LSB and you get
text. Two frames of eleven characters:

    "The night s" + "ky awaits  "

Usage: python 20_vcd_message.py <example_inputs.vcd> [outdir]
"""
import sys, os, re


def frames_from_vcd(path):
    """Every value of I sampled on a rising clk edge while enable is high,
    split into frames wherever the gap between samples jumps."""
    txt = open(path).read()
    ids = dict(re.findall(r"\$var \w+ \d+ (\S+) (\w+)", txt))
    by_name = {v: k for k, v in ids.items()}
    clk, sig_i, en = by_name["clk"], by_name["I"], by_name["enable"]

    t, cur, samples = 0, {"I": "0", "enable": "0"}, []
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("#"):
            t = int(line[1:])
        elif len(line) > 1 and line[0] in "01":
            v, i = line[0], line[1:]
            if i == clk:
                if v == "1" and cur["enable"] == "1":
                    samples.append((t, v and cur["I"]))
            elif i == sig_i:
                cur["I"] = v
            elif i == en:
                cur["enable"] = v

    frames = [[samples[0]]]
    for a, b in zip(samples, samples[1:]):
        if b[0] - a[0] > 20000:
            frames.append([])
        frames[-1].append(b)
    return ["".join(v for _, v in f) for f in frames]


def main():
    vcd = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else None
    N, L = 11, []
    L.append(f"HIDDEN MESSAGE IN THE INPUTS OF {vcd}")
    L.append("=" * 60)
    L.append("")

    head = open(vcd).read().split("$scope")[0]
    for field in ("date", "version"):
        m = re.search(r"\$" + field + r"\s+(.*?)\s*\$end", head, re.S)
        if m:
            L.append(f"VCD ${field}: {m.group(1).strip()!r}")
    L.append("")

    text = ""
    for n, bits in enumerate(frames_from_vcd(vcd)):
        if len(bits) != N * N:
            L.append(f"frame {n}: {len(bits)} bits -- not an 11x11 grid, skipping")
            continue
        rows = [bits[r * N:(r + 1) * N] for r in range(N)]
        unused = {r[7:] for r in rows}
        L.append(f"frame {n}: {bits.count('1')} stars; columns 7..10 "
                 f"{'ALL EMPTY' if unused == {'0000'} else 'in use'}"
                 f"  <- 7 usable columns = 7 bits = one ASCII character per row")
        L.append("")
        for r in rows:
            v = int(r[6::-1], 2)
            ch = chr(v) if 32 <= v < 127 else "."
            L.append("   " + " ".join("*" if c == "1" else "." for c in r)
                     + f"   {r[:7]} -> {v:3d} -> {ch!r}")
            text += ch
        L.append("")

    L.append(f"MESSAGE: {text!r}")
    L.append(f"         {text.strip()!r}")
    out = "\n".join(L)
    print(out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        open(os.path.join(outdir, "vcd_message.txt"), "w").write(out + "\n")
        print(f"\nwrote {outdir}/vcd_message.txt")


if __name__ == "__main__":
    main()
