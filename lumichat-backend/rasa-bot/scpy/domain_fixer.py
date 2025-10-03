# domain_fixer.py
# COMMAND
# python domain_fixer.py
# Specify paths:
# python scpy/domain_fixer.py --in domain.yml --out data\domain_fixed.yml

# Overwrite in place (keeps a timestamped .bak):
# python scpy/domain_fixer.py --in domain.yml --in-place


import argparse, os, sys, time, copy
import yaml

def load_yaml(path):
    with open(path, "r", encoding="utf-8-sig") as f:  # BOM-safe
        return yaml.safe_load(f) or {}

def save_yaml(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def backup(path):
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak.{ts}"
    try:
        with open(path, "rb") as src, open(bak, "wb") as dst:
            dst.write(src.read())
    except Exception:
        bak = None
    return bak

def as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])

def normalize_response_variants(variants):
    """Ensure variants is a list of dicts. Strings become {'text': ...}."""
    out = []
    for v in as_list(variants):
        if isinstance(v, dict):
            out.append(v)
        elif isinstance(v, str):
            out.append({"text": v})
        else:
            out.append({"text": str(v)})
    return out

def dedupe_variants(variants):
    seen = set()
    uniq = []
    for v in variants:
        # Build a hashable signature of fields that matter
        sig = (
            v.get("text", None),
            v.get("image", None),
            tuple(tuple(sorted(b.items())) for b in v.get("buttons", []) if isinstance(b, dict)),
            v.get("condition", None) and tuple(tuple(sorted(c.items())) for c in v["condition"]),
        )
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(v)
    return uniq

def ensure_session_config(doc, report):
    """Make sure session_config is at the root and well-formed."""
    # If someone placed the keys under responses, pull them out.
    responses = doc.get("responses")
    if isinstance(responses, dict):
        moved = False
        if "session_expiration_time" in responses:
            doc.setdefault("session_config", {})
            doc["session_config"]["session_expiration_time"] = responses.pop("session_expiration_time")
            moved = True
        if "carry_over_slots_to_new_session" in responses:
            doc.setdefault("session_config", {})
            doc["session_config"]["carry_over_slots_to_new_session"] = responses.pop("carry_over_slots_to_new_session")
            moved = True
        if moved:
            report.append("Moved session_config keys out of responses.")

    # If loose at root (not nested), wrap them
    moved2 = False
    if "session_expiration_time" in doc or "carry_over_slots_to_new_session" in doc:
        sc = doc.setdefault("session_config", {})
        if "session_expiration_time" in doc:
            sc["session_expiration_time"] = doc.pop("session_expiration_time")
            moved2 = True
        if "carry_over_slots_to_new_session" in doc:
            sc["carry_over_slots_to_new_session"] = doc.pop("carry_over_slots_to_new_session")
            moved2 = True
    if moved2:
        report.append("Wrapped loose session_config keys under session_config block.")

    # Defaults (optional)
    if "session_config" not in doc:
        doc["session_config"] = {"session_expiration_time": 60, "carry_over_slots_to_new_session": True}
        report.append("Added default session_config.")
    else:
        sc = doc["session_config"]
        if "session_expiration_time" not in sc:
            sc["session_expiration_time"] = 60
            report.append("Set default session_expiration_time: 60")
        if "carry_over_slots_to_new_session" not in sc:
            sc["carry_over_slots_to_new_session"] = True
            report.append("Set default carry_over_slots_to_new_session: true")

def move_utter_from_forms(doc, report):
    """Move any forms entries named like utter_* back into responses."""
    forms = doc.get("forms", {}) or {}
    responses = doc.get("responses", {}) or {}

    moved = []
    warnings = []

    keys_to_delete = []
    for form_name, form_val in forms.items():
        if isinstance(form_name, str) and form_name.startswith("utter_"):
            resp_list = normalize_response_variants(form_val)
            existing = normalize_response_variants(responses.get(form_name, []))
            merged = dedupe_variants(existing + resp_list)
            responses[form_name] = merged
            keys_to_delete.append(form_name)
            moved.append(form_name)
        else:
            if not isinstance(form_val, dict):
                warnings.append(f"Form '{form_name}' is {type(form_val).__name__}, expected dict.")

    for k in keys_to_delete:
        forms.pop(k, None)

    if moved:
        report.append(f"Moved {len(moved)} utter_* from forms -> responses: {', '.join(moved)}")
    if warnings:
        report.extend([f"Warning: {w}" for w in warnings])

    doc["responses"] = responses
    doc["forms"] = forms

def normalize_all_responses(doc, report):
    """Ensure every response key has a list of dict variants."""
    responses = doc.get("responses", {}) or {}
    changed = 0
    for k, v in list(responses.items()):
        norm = normalize_response_variants(v)
        dedup = dedupe_variants(norm)
        if dedup != v:
            responses[k] = dedup
            changed += 1
    if changed:
        report.append(f"Normalized {changed} response(s) to list-of-dicts form.")
    doc["responses"] = responses

def ensure_actions_list(doc, report):
    if "actions" not in doc:
        doc["actions"] = []
        report.append("Added missing actions: []")
    elif not isinstance(doc["actions"], list):
        doc["actions"] = []
        report.append("Fixed actions to be a list: []")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="domain.yml", help="Path to input domain.yml (default: domain.yml)")
    ap.add_argument("--out", dest="outp", default="domain_fixed.yml", help="Path to output fixed YAML (default: domain_fixed.yml)")
    ap.add_argument("--in-place", action="store_true", help="Overwrite the input file in place")
    args = ap.parse_args()

    src = args.inp
    if not os.path.exists(src):
        print(f"❌ Not found: {src}")
        sys.exit(2)

    doc = load_yaml(src)
    report = []

    # 1) Make sure responses exist as dict
    if "responses" not in doc or not isinstance(doc["responses"], dict):
        doc["responses"] = {}
        report.append("Created empty responses: {}")

    # 2) Move any utter_* accidentally put under forms
    move_utter_from_forms(doc, report)

    # 3) Normalize responses to list-of-dicts and de-duplicate
    normalize_all_responses(doc, report)

    # 4) Ensure session_config is at root and valid
    ensure_session_config(doc, report)

    # 5) Ensure actions is a list
    ensure_actions_list(doc, report)

    # Save (with backup if in-place)
    out = args.outp
    if args.in_place:
        bak = backup(src)
        if bak:
            print(f"[info] Backup saved: {bak}")
        out = src

    save_yaml(out, doc)

    print(f"✅ Fixed domain saved as {out}")
    if report:
        print("📝 Changes:")
        for r in report:
            print(" -", r)

if __name__ == "__main__":
    main()
