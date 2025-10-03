# dedupe_nlu_examples.py
# Removes repeating examples across intents in a Rasa NLU YAML.
# - Keeps the FIRST intent where an example appears
# - Removes duplicate examples from other intents
# - De-duplicates within the same intent
# - Writes a cleaned file and a small report
#
# Usage:
#   py dedupe_nlu_examples.py --in nlu.yml --out nlu_clean.yml --min 2
#   (add --inplace to overwrite the input file)

# COMMAND
# # basic: read nlu.yml and write nlu_clean.yml
# py scpy/dedupe_nlu_examples.py --in data/nlu.yml --out nlu_clean.yml

# # overwrite in place
# py scpy/dedupe_nlu_examples.py --in data/nlu.yml --inplace

# # change the minimum threshold (default 2)
# py scpy/dedupe_nlu_examples.py --in data/nlu.yml --out nlu_clean.yml --min 3

import argparse, os, re, sys
from collections import OrderedDict
import yaml
from typing import List, Dict

def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def parse_examples_block(examples_str: str) -> List[str]:
    """Rasa stores examples as a block scalar string under 'examples'."""
    items = []
    if not isinstance(examples_str, str):
        return items
    for line in examples_str.splitlines():
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip())
    return items

def make_examples_block(items: List[str]) -> str:
    """Render back to block scalar content with '- ' lines."""
    # keep order & drop empty
    uniq = []
    seen = set()
    for it in items:
        t = it.strip()
        if not t: 
            continue
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return "\n".join(f"- {x}" for x in uniq)

def norm(s: str) -> str:
    """Normalize an example for cross-intent duplicate detection."""
    t = s.lower().strip()
    t = re.sub(r"\s+", " ", t)  # collapse whitespace
    # strip common edge punctuation/quotes
    t = re.sub(r"^[\"'“”‘’\-\.\,;:\!\?()\[\]\{\}]+|[\"'“”‘’\-\.\,;:\!\?()\[\]\{\}]+$", "", t)
    return t

def main():
    ap = argparse.ArgumentParser(description="De-duplicate NLU examples across intents.")
    ap.add_argument("--in", dest="inp", default="nlu.yml", help="Input NLU YAML (default: nlu.yml)")
    ap.add_argument("--out", dest="out", default="nlu_clean.yml", help="Output cleaned NLU YAML")
    ap.add_argument("--inplace", action="store_true", help="Overwrite the input file")
    ap.add_argument("--min", dest="min_count", type=int, default=2, help="Minimum examples per intent to flag (default: 2)")
    args = ap.parse_args()

    src = args.inp
    if not os.path.exists(src):
        print(f"❌ Input file not found: {src}")
        sys.exit(1)

    doc = load_yaml(src)
    if not isinstance(doc, dict) or "nlu" not in doc or not isinstance(doc["nlu"], list):
        print("❌ Invalid NLU YAML structure. Expected top-level key 'nlu' with a list.")
        sys.exit(1)

    # Preserve intent order
    intent_order: List[str] = []
    by_intent: Dict[str, List[str]] = OrderedDict()

    # First pass: collect examples (raw) & record order
    for blk in doc["nlu"]:
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

    # De-dup within intents (exact text)
    for intent, exs in by_intent.items():
        seen_local = set()
        uniq = []
        for e in exs:
            if e not in seen_local:
                uniq.append(e)
                seen_local.add(e)
        by_intent[intent] = uniq

    # Cross-intent de-dup (keep first occurrence globally)
    global_seen = {}
    removed = []   # (example, from_intent, kept_in_intent)
    for intent in intent_order:
        filtered = []
        for e in by_intent[intent]:
            k = norm(e)
            if k in global_seen:
                removed.append((e, intent, global_seen[k]))
                continue
            global_seen[k] = intent
            filtered.append(e)
        by_intent[intent] = filtered

    # Build cleaned YAML
    cleaned = {'version': doc.get('version', "3.1"), 'nlu': []}
    under_min = []

    for intent in intent_order:
        exs = by_intent[intent]
        if len(exs) < args.min_count:
            under_min.append((intent, len(exs)))
        cleaned["nlu"].append({
            "intent": intent,
            "examples": ("|\n" + "\n".join("  " + line for line in make_examples_block(exs).splitlines()))
                        if exs else "|\n  - "
        })

    # Write output
    out_path = src if args.inplace else args.out
    # We want nice block scalars like Rasa expects
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f'version: "{cleaned["version"]}"\n')
        f.write("nlu:\n\n")
        for blk in cleaned["nlu"]:
            f.write(f"- intent: {blk['intent']}\n")
            f.write("  examples: " + blk["examples"] + "\n\n")

    # Report
    print(f"✅ Cleaned NLU written to: {out_path}")
    if removed:
        print("\n🧹 Removed cross-intent duplicates (kept first occurrence):")
        for e, dup_intent, kept in removed[:30]:
            print(f" - '{e}' (from {dup_intent}) — kept under {kept}")
        if len(removed) > 30:
            print(f"   ... and {len(removed)-30} more")
    if under_min:
        print(f"\n⚠ Intents under minimum ({args.min_count} examples):")
        for name, cnt in under_min:
            print(f" - {name}: {cnt}")

if __name__ == "__main__":
    main()
