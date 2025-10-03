# COMMAND
# python scpy/generate_intents.py --prefix addiction_p --start 1 --end 170 --zero-pad 4 --out data/intents.yml

import argparse
from pathlib import Path

def write_intents_yaml(prefix: str, start: int, end: int, zero_pad: int, out_path: Path):
    lines = []
    lines.append('version: "3.1"')
    lines.append("intents:")
    for i in range(start, end + 1):
        suffix = str(i).zfill(zero_pad) if zero_pad > 0 else str(i)
        intent = f"{prefix}{suffix}"
        lines.append(f"  - {intent}")
    out_path.write_text("\n".join(lines), encoding="utf-8")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", required=True, help="Intent prefix, e.g., anxiety_p")
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--zero-pad", type=int, default=4)
    p.add_argument("--out", required=True, type=Path, help="Output YAML file")
    args = p.parse_args()

    write_intents_yaml(args.prefix, args.start, args.end, args.zero_pad, args.out)
