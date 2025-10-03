# # keep long examples AND add the short pieces
# py scpy/example_generator.py --in data/nlu.yml --out nlu_generated.yml --max-len 25 --mode append

# # OR replace long examples with the short pieces (lighter training)
# py scpy/example_generator.py --in data/nlu.yml --out nlu_generated.yml --max-len 25 --mode replace_long



import re, os, argparse, sys, yaml
from collections import OrderedDict

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def parse_examples_block(examples_str):
    items = []
    if not isinstance(examples_str, str):
        return items
    for line in examples_str.splitlines():
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip().strip('"'))
    return items

def split_into_phrases(text, max_len_words=25):
    # Split by sentences, then sub-split long sentences on commas/semicolons
    sentences = re.split(r'(?<=[.!?])\s+', text.strip().strip('"'))
    phrases = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s.split()) > max_len_words:
            subs = [p.strip(" ,;") for p in re.split(r'[;,]\s+', s) if p.strip(" ,;")]
            phrases.extend(subs if subs else [s])
        else:
            phrases.append(s)
    # trim & drop empties
    phrases = [p for p in (p.strip() for p in phrases) if p]
    return phrases

def dedupe_keep_order(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def build_clean_yaml(version, intent_order, by_intent, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f'version: "{version or "3.1"}"\n')
        f.write("nlu:\n\n")
        for intent in intent_order:
            exs = by_intent.get(intent, [])
            f.write(f"- intent: {intent}\n")
            f.write("  examples: |\n")
            for e in exs:
                f.write(f"    - {e}\n")
            f.write("\n")

def main():
    ap = argparse.ArgumentParser(description="Generate short examples from long NLU examples (clean YAML output).")
    ap.add_argument("--in", dest="inp", default="nlu.yml", help="Input NLU YAML")
    ap.add_argument("--out", dest="out", default="nlu_generated.yml", help="Output NLU YAML")
    ap.add_argument("--max-len", dest="max_len", type=int, default=25, help="Max words before splitting (default 25)")
    ap.add_argument("--mode", choices=["append","replace_long"], default="append",
                    help="append: keep long + add shorts; replace_long: replace only the long ones")
    args = ap.parse_args()

    if not os.path.exists(args.inp):
        print(f"❌ Could not find {args.inp}. Use --in to point to your NLU file.")
        sys.exit(1)

    data = load_yaml(args.inp)
    if not isinstance(data, dict) or "nlu" not in data:
        print("❌ Invalid NLU YAML: expected top-level key 'nlu'.")
        sys.exit(1)

    version = data.get("version", "3.1")
    intent_order = []
    by_intent = OrderedDict()

    # Read existing blocks
    for blk in data["nlu"]:
        if not isinstance(blk, dict): 
            continue
        intent = blk.get("intent")
        if not intent:
            continue
        if intent not in by_intent:
            intent_order.append(intent)
            by_intent[intent] = []
        exs = parse_examples_block(blk.get("examples", ""))
        by_intent[intent].extend(exs)

    # Generate shorter examples
    for intent in intent_order:
        originals = by_intent[intent]
        new_list = []
        for ex in originals:
            words = ex.split()
            if len(words) > args.max_len:
                shorts = split_into_phrases(ex, args.max_len)
                if args.mode == "append":
                    # keep original + add splits
                    new_list.append(ex)
                    new_list.extend(shorts)
                else:  # replace_long
                    new_list.extend(shorts)
            else:
                new_list.append(ex)
        by_intent[intent] = dedupe_keep_order(new_list)

    # Write CLEAN YAML (no \n escapes)
    build_clean_yaml(version, intent_order, by_intent, args.out)
    print(f"✅ Wrote clean YAML to {args.out}")

if __name__ == "__main__":
    main()