#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Merge English + Cebuano domain.yml into one bilingual domain with conditional responses.

Usage:
    python rasa_domain_bilingual_merge.py --en domain_en.yml --ceb domain_ceb.yml --out domain.yml --default en

This script:
- Copies all non-response fields from EN file (intents, entities, slots, forms, etc.)
- Ensures a `language` slot exists (type text, mapped from entity language)
- Merges responses:
    * If both EN and CEB exist -> creates conditional variants with slot=language
    * If only one exists -> keeps it, also adds it as fallback
- Adds a fallback variant (default to EN, unless --default ceb is set)
- Writes a JSON merge report alongside the output.
"""

import os, json, yaml, argparse, copy, sys
from collections import OrderedDict

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def dump_yaml(data, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def ensure_language_slot(domain_obj):
    slots = domain_obj.setdefault("slots", OrderedDict())
    lang = slots.get("language")
    if not isinstance(lang, dict):
        slots["language"] = {
            "type": "text",
            "influence_conversation": True,
            "mappings": [
                {"type": "from_entity", "entity": "language"}
            ]
        }
        return True
    # ensure mapping exists
    mappings = lang.setdefault("mappings", [])
    if not any(isinstance(m, dict) and m.get("type")=="from_entity" and m.get("entity")=="language" for m in mappings):
        mappings.append({"type":"from_entity","entity":"language"})
        return True
    return False

def normalize_variants(lst):
    if not isinstance(lst, list):
        return []
    out = []
    for v in lst:
        if isinstance(v, dict):
            out.append(v)
        elif isinstance(v, str):
            out.append({"text": v})
    return out

def merge_responses(en_resp, ceb_resp, default_lang="en"):
    merged = OrderedDict()
    all_keys = set()
    if isinstance(en_resp, dict):
        all_keys |= set(en_resp.keys())
    if isinstance(ceb_resp, dict):
        all_keys |= set(ceb_resp.keys())

    for key in sorted(all_keys):
        en_list = normalize_variants((en_resp or {}).get(key, []))
        ceb_list = normalize_variants((ceb_resp or {}).get(key, []))

        n = max(len(en_list), len(ceb_list))
        merged_list = []

        for i in range(n):
            en_item = en_list[i] if i < len(en_list) else None
            ceb_item = ceb_list[i] if i < len(ceb_list) else None

            if ceb_item is not None:
                item_ceb = copy.deepcopy(ceb_item)
                item_ceb["condition"] = [{"type":"slot","name":"language","value":"ceb"}]
                merged_list.append(item_ceb)

            if en_item is not None:
                item_en = copy.deepcopy(en_item)
                item_en["condition"] = [{"type":"slot","name":"language","value":"en"}]
                merged_list.append(item_en)

        # Add unconditional fallback
        fallback_item = None
        if default_lang == "en":
            if len(en_list)>0:
                fallback_item = copy.deepcopy(en_list[0])
            elif len(ceb_list)>0:
                fallback_item = copy.deepcopy(ceb_list[0])
        else: # ceb default
            if len(ceb_list)>0:
                fallback_item = copy.deepcopy(ceb_list[0])
            elif len(en_list)>0:
                fallback_item = copy.deepcopy(en_list[0])

        if fallback_item is not None:
            if isinstance(fallback_item, dict) and "condition" in fallback_item:
                fallback_item = copy.deepcopy(fallback_item)
                fallback_item.pop("condition", None)
            merged_list.append(fallback_item)

        merged[key] = merged_list

    return merged

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", required=True, help="Path to English domain.yml")
    ap.add_argument("--ceb", required=True, help="Path to Cebuano domain.yml")
    ap.add_argument("--out", required=True, help="Path to merged output domain.yml")
    ap.add_argument("--default", choices=["en","ceb"], default="en", help="Default fallback language")
    args = ap.parse_args()

    en = load_yaml(args.en)
    ceb = load_yaml(args.ceb)

    out = OrderedDict()

    # Copy top-level fields from EN as base
    for k,v in en.items():
        if k != "responses":
            out[k] = v

    if "version" not in out:
        out["version"] = "3.1"

    slot_added = ensure_language_slot(out)

    en_resp = en.get("responses", {})
    ceb_resp = ceb.get("responses", {})
    merged_resp = merge_responses(en_resp, ceb_resp, default_lang=args.default)
    out["responses"] = merged_resp

    dump_yaml(out, args.out)

    report = {
        "base_en": args.en,
        "base_ceb": args.ceb,
        "output": args.out,
        "default_fallback": args.default,
        "slot_language_added": slot_added,
        "responses_merged": sorted(list(merged_resp.keys())),
        "counts": {
            "en_only": [k for k in en_resp.keys() if k not in ceb_resp],
            "ceb_only": [k for k in ceb_resp.keys() if k not in en_resp],
            "both": [k for k in en_resp.keys() if k in ceb_resp]
        }
    }
    with open(args.out + ".merge_report.json", "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
