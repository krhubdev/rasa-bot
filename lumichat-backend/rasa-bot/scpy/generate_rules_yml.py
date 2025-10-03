# COMMAND
# python scpy/generate_rules_yml.py --out data/number_generator.yml range --prefix anxiety_p --start 1 --end 200 --zero-pad 4 --utter-prefix utter_anxiety_p


import argparse
from pathlib import Path
import csv
from typing import List, Optional, Tuple

def write_rules_yaml(pairs: List[Tuple[str, str]], out_path: Path):
    lines = []
    lines.append('version: "3.1"')
    lines.append("rules:")
    for intent, utter in pairs:
        rule_name = f"respond to {intent}"
        lines.append(f"- rule: {rule_name}")
        lines.append("  steps:")
        lines.append(f"    - intent: {intent}")
        lines.append(f"    - action: {utter}")
    out_path.write_text("\n".join(lines), encoding="utf-8")

def gen_pairs_from_range(prefix: str, start: int, end: int, zero_pad: int, utter_prefix: Optional[str] = None):
    if utter_prefix is None:
        utter_prefix = "utter_" + prefix
    pairs = []
    for i in range(start, end + 1):
        suffix = str(i).zfill(zero_pad) if zero_pad > 0 else str(i)
        intent = f"{prefix}{suffix}"
        utter = f"{utter_prefix}{suffix}"
        pairs.append((intent, utter))
    return pairs

def gen_pairs_from_csv(csv_path: Path, intent_col: str = "intent", utter_col: Optional[str] = None, default_utter_prefix: Optional[str] = None):
    pairs = []
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            intent = row[intent_col].strip()
            if utter_col and utter_col in row and row[utter_col].strip():
                utter = row[utter_col].strip()
            else:
                if not default_utter_prefix:
                    default_utter_prefix = "utter_"
                utter = default_utter_prefix + intent
            pairs.append((intent, utter))
    return pairs

def main():
    p = argparse.ArgumentParser(description="Generate Rasa rules.yml from intents and utters.")
    sub = p.add_subparsers(dest="mode", required=True)

    pr = sub.add_parser("range", help="Generate from a numeric range")
    pr.add_argument("--prefix", required=True, help="Intent prefix, e.g., anxiety_p")
    pr.add_argument("--start", type=int, required=True, help="Start index, e.g., 1")
    pr.add_argument("--end", type=int, required=True, help="End index, e.g., 1000")
    pr.add_argument("--zero-pad", type=int, default=4, help="Zero padding width, e.g., 4 to get 0001")
    pr.add_argument("--utter-prefix", default=None, help="Optional utter prefix; default uses 'utter_' + prefix")

    pc = sub.add_parser("csv", help="Generate from a CSV file")
    pc.add_argument("--csv", required=True, type=Path, help="CSV path with at least an 'intent' column")
    pc.add_argument("--intent-col", default="intent", help="Column name for intents")
    pc.add_argument("--utter-col", default=None, help="Optional column name for utter actions")
    pc.add_argument("--default-utter-prefix", default=None, help="If utter-col missing, use this to build utter names as prefix+intent (or 'utter_'+intent if not set)")

    p.add_argument("--out", required=True, type=Path, help="Output rules.yml")

    args = p.parse_args()

    if args.mode == "range":
        pairs = gen_pairs_from_range(args.prefix, args.start, args.end, args.zero_pad, args.utter_prefix)
    else:
        pairs = gen_pairs_from_csv(args.csv, args.intent_col, args.utter_col, args.default_utter_prefix)

    write_rules_yaml(pairs, args.out)

if __name__ == "__main__":
    main()
