#!/usr/bin/env python3
"""
Post-process G-code to apply a temporary Z offset ONLY within the layer block
that starts at a given Z_HEIGHT marker, then return to normal at the next
CHANGE_LAYER.

Layer markers expected (as in your example):
  ; CHANGE_LAYER
  ; Z_HEIGHT: 6.4
  ; LAYER_HEIGHT: 0.2

What it does:
- Find the block whose header contains "; CHANGE_LAYER" followed by a matching
  "; Z_HEIGHT: <target>"
- From that point until the next "; CHANGE_LAYER", add +offset to any Z value
  on G0/G1 lines (only the code part, not trailing ';' comments)
- Also adjusts the "; Z_HEIGHT: ..." comment line inside that block

Usage:
  python zheight_layer_offset.py in.gcode out.gcode --zheight 6.4 --offset 0.05
"""

import argparse
import re
from decimal import Decimal, ROUND_HALF_UP


CHANGE_LAYER_RE = re.compile(r'^\s*;\s*CHANGE_LAYER\s*$')
Z_HEIGHT_RE = re.compile(r'^\s*;\s*Z_HEIGHT\s*:\s*([-+]?\d*\.?\d+)\s*$')

# Capture Z parameter in a G0/G1 line (ignores anything after a ';' comment)
Z_PARAM_RE = re.compile(r'(?P<prefix>\bZ)(?P<val>[-+]?\d*\.?\d+)')


def fmt_decimal(x: Decimal, places=5) -> str:
    q = Decimal('1.' + '0' * places)
    s = str(x.quantize(q, rounding=ROUND_HALF_UP))
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s


def add_offset_to_g0g1_z(line: str, offset: Decimal) -> str:
    # Split off trailing comment so we don't rewrite Z inside comments
    if ';' in line:
        code, comment = line.split(';', 1)
        comment = ';' + comment
    else:
        code, comment = line, ''

    stripped = code.lstrip()
    if not (stripped.startswith('G0') or stripped.startswith('G1')):
        return line

    def repl(m):
        old = Decimal(m.group('val'))
        new = old + offset
        return f"{m.group('prefix')}{fmt_decimal(new)}"

    new_code, n = Z_PARAM_RE.subn(repl, code, count=1)  # at most one Z per line
    if n == 0:
        return line
    return new_code + comment


def process(in_path: str, out_path: str, target_zheight: float, offset: float, tol: float = 1e-6):
    target = float(target_zheight)
    offset_d = Decimal(str(offset))

    in_target_block = False
    pending_change_layer = False
    found_target = False

    with open(in_path, 'r', encoding='utf-8', errors='ignore') as fin, \
         open(out_path, 'w', encoding='utf-8', newline='') as fout:

        for line in fin:
            # Detect layer boundaries
            if CHANGE_LAYER_RE.match(line):
                # entering a new layer header; end previous target block
                in_target_block = False
                pending_change_layer = True
                fout.write(line)
                continue

            # If we're in the header of a new layer, look for its Z_HEIGHT
            if pending_change_layer:
                mzh = Z_HEIGHT_RE.match(line)
                if mzh:
                    z = float(mzh.group(1))
                    if abs(z - target) <= tol:
                        in_target_block = True
                        found_target = True
                        # rewrite this Z_HEIGHT comment with offset applied
                        z_new = Decimal(mzh.group(1)) + offset_d
                        fout.write(re.sub(r'([-+]?\d*\.?\d+)', fmt_decimal(z_new), line, count=1))
                    else:
                        fout.write(line)
                    # remain in "pending header" until next non-comment? We can just
                    # stop treating it as pending after we see Z_HEIGHT line.
                    pending_change_layer = False
                    continue

                # still in header, but not Z_HEIGHT line
                fout.write(line)
                # keep pending_change_layer True until we see Z_HEIGHT (some files may place it immediately)
                continue

            # Normal lines: apply offset only inside target block
            if in_target_block:
                fout.write(add_offset_to_g0g1_z(line, offset_d))
            else:
                fout.write(line)

    if not found_target:
        raise SystemExit(f"Did not find a layer header with '; Z_HEIGHT: {target_zheight}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Input G-code path")
    ap.add_argument("output", help="Output G-code path")
    ap.add_argument("--zheight", type=float, required=True, help="Target Z_HEIGHT value (e.g., 6.4)")
    ap.add_argument("--offset", type=float, required=True, help="Temporary Z offset for that layer (e.g., 0.05)")
    ap.add_argument("--tol", type=float, default=1e-6, help="Tolerance for matching Z_HEIGHT (default: 1e-6)")
    args = ap.parse_args()

    process(args.input, args.output, args.zheight, args.offset, args.tol)


if __name__ == "__main__":
    main()