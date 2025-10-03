#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rasa NLU YAML auto-fixer (v3, aggressive)
- Normalizes whitespace (tabs -> 2 spaces, CRLF->LF, strip BOM)
- Detects blocks starting with '- intent:', '- regex:', '- synonym:', '- lookup:'
- For each `examples:` block:
    * Ensures `examples: |`
    * Ensures every non-empty line becomes a bullet: '- ...'
      - Lines starting with '#' become bullets with the hash removed ('# Title' -> '- Title')
    * Optionally merges likely continuation lines into the previous bullet
      (if line starts with lowercase and previous bullet doesn't end with [.?!:;] or closing quote/paren)
    * Indents bullet lines exactly 2 spaces deeper than `examples:`
- Adds `version: "3.1"` at top if missing
- Ensures there is an 'nlu:' root; if absent, wraps the discovered list under 'nlu:'
- Produces a JSON change report alongside the output file
- Optionally validates with PyYAML if available
Usage:
python scpy/rasa_nlu_autofix.py --in data/nlu.yml --out data/nlu_format_fixed.yml
# Enable continuation merging (recommended for long wrapped sentences)
python scpy/rasa_nlu_autofix.py--in data/nlu.yml --out data/nlu_format_fixed.yml --merge-continuations
"""
import argparse, os, re, sys, shutil
from datetime import datetime

BLOCK_KEYS = ("intent", "regex", "synonym", "lookup")

def detab_and_normalize(text: str) -> str:
    # Strip UTF-8 BOM if present
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "  ")
    return text

def make_backup(src_path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{src_path}.bak.{ts}"
    shutil.copy2(src_path, backup_path)
    return backup_path

def ensure_version_header(lines, report):
    has_version = any(re.match(r'^\s*version\s*:\s*["\']?\d+(\.\d+)?["\']?\s*$', ln) for ln in lines[:5])
    if not has_version:
        lines = ['version: "3.1"\n'] + lines
        report['added_version_header'] = True
    return lines

def detect_has_nlu_root(lines):
    for ln in lines:
        if re.match(r'^\s*nlu\s*:\s*$', ln):
            return True
    return False

def wrap_under_nlu_if_needed(lines, report):
    """
    If the file appears to be a plain list of blocks without 'nlu:' root, wrap it.
    Heuristic: if the first non-comment, non-empty line starts with '- ' then wrap.
    """
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx < len(lines) and re.match(r'^\s*#', lines[idx]):
        # Skip initial comments
        while idx < len(lines) and (lines[idx].strip() == "" or lines[idx].lstrip().startswith("#")):
            idx += 1
    if idx < len(lines) and lines[idx].lstrip().startswith('- ') and not detect_has_nlu_root(lines):
        report['wrapped_under_nlu'] = True
        new_lines = ["nlu:\n"]
        # indent all content by 2 spaces
        for ln in lines:
            if ln.strip() == "":
                new_lines.append(ln)
            else:
                new_lines.append("  " + ln)
        return new_lines
    return lines

def fix_examples_blocks(lines, report):
    block_start_re = re.compile(r'^(?P<li>\s*)-\s*(?P<key>' + "|".join(BLOCK_KEYS) + r')\s*:\s*(?P<val>.+?)\s*$')
    examples_re = re.compile(r'^(?P<ind>\s*)examples:\s*(?P<pipe>\|?-?)\s*$')

    i = 0
    n = len(lines)
    changes = 0
    bullets_forced = 0
    comments_coerced = 0
    continuations_merged = 0

    def is_probably_continuation(text: str, prev: str) -> bool:
        # lowercase start and previous bullet not ending in terminal punctuation or closing
        if not text or not prev: 
            return False
        t = text.lstrip()
        if t.startswith('- '):
            return False
        if not t or not t[0].islower():
            return False
        prev = prev.rstrip()
        if prev.endswith(('.', '!', '?', ':', ';', '"', "'", ')', ']', '”', '’')):
            return False
        return True

    while i < n:
        m0 = block_start_re.match(lines[i])
        if not m0:
            i += 1
            continue

        # Find examples line within this block
        j = i + 1
        while j < n and not block_start_re.match(lines[j]):
            m = examples_re.match(lines[j])
            if not m:
                j += 1
                continue

            base_indent = len(m.group('ind'))
            # Normalize to pipe block if missing
            if m.group('pipe') == "" or m.group('pipe') is None:
                lines[j] = f"{' ' * base_indent}examples: |\n"
                changes += 1

            desired_indent = ' ' * (base_indent + 2)

            # Collect the raw example lines until the block ends or next block starts
            k = j + 1
            collected = []
            while k < n and not block_start_re.match(lines[k]):
                ln = lines[k]
                collected.append(ln)
                k += 1

            # Process collected
            processed = []
            last_bullet_index = -1
            for raw in collected:
                # Keep exact text but normalize indentation and artifacts
                m2 = re.match(r'^(\s*)(.*)$', raw)
                cur_indent = len(m2.group(1) or "")
                content = m2.group(2)

                # Skip pure whitespace lines -> keep as blank (no warning from Rasa)
                if content.strip() == "":
                    processed.append(desired_indent + "\n")
                    continue

                # Clean obvious artifacts
                content = re.sub(r'"\s*"', ' ', content)

                # Coerce comments or any non-bullet to bullets
                stripped = content.lstrip()
                if stripped.startswith('#'):
                    text = stripped.lstrip('#').strip()
                    if text == "":
                        # ignore empty comment
                        processed.append(desired_indent + "\n")
                        continue
                    content = "- " + text
                    comments_coerced += 1
                elif not stripped.startswith('- '):
                    # Try continuation-merge with prior bullet
                    if last_bullet_index >= 0:
                        prev_text = processed[last_bullet_index].strip()
                        # remove leading indent for analysis
                        prev_text_clean = re.sub(r'^\s*-\s*', '', prev_text)
                        if is_probably_continuation(stripped, prev_text_clean):
                            # merge into previous bullet
                            merged = re.sub(r'\s*\n$', '', processed[last_bullet_index])
                            merged += " " + stripped + "\n"
                            processed[last_bullet_index] = merged
                            continuations_merged += 1
                            continue
                    # else force bullet
                    content = "- " + stripped
                    bullets_forced += 1

                # Ensure proper indent
                line_fixed = f"{desired_indent}{content.strip()}\n"
                processed.append(line_fixed)
                if content.strip().startswith('- '):
                    last_bullet_index = len(processed) - 1

            # Write processed back
            new_chunk = "".join(processed)
            old_chunk = "".join(collected)
            if new_chunk != old_chunk:
                changes += 1
                lines[j+1:k] = processed
                # adjust n after slice replacement
                n = len(lines)
            # Jump to k
            j = k
            break

        i = j

    report['example_blocks_changed'] = changes
    report['bullets_forced'] = bullets_forced
    report['comments_to_bullets'] = comments_coerced
    report['continuations_merged'] = continuations_merged
    return lines

def optional_yaml_validate(text: str, report) -> bool:
    try:
        import yaml  # type: ignore
    except Exception:
        report['yaml_validation'] = 'skipped (PyYAML not installed)'
        return True
    try:
        yaml.safe_load(text)
        report['yaml_validation'] = 'ok'
        return True
    except Exception as e:
        report['yaml_validation'] = f'fail: {e}'
        return False

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Path to input nlu.yml")
    ap.add_argument("--out", dest="outp", required=True, help="Path to write fixed YAML")
    ap.add_argument("--no-backup", action="store_true", help="Do not create a backup of the input file")
    ap.add_argument("--merge-continuations", action="store_true", help="Try to merge likely continuation lines into previous bullet")
    args = ap.parse_args()

    src = args.inp
    dst = args.outp

    report = {
        "source": src,
        "output": dst,
        "added_version_header": False,
        "wrapped_under_nlu": False,
        "example_blocks_changed": 0,
        "bullets_forced": 0,
        "comments_to_bullets": 0,
        "continuations_merged": 0,
    }

    if not os.path.exists(src):
        print(f"[error] Input not found: {src}", file=sys.stderr)
        sys.exit(2)

    if not args.no_backup:
        try:
            backup = make_backup(src)
            report["backup"] = backup
            print(f"[info] Backup created: {backup}")
        except Exception as e:
            print(f"[warn] Could not create backup: {e}")

    with open(src, "r", encoding="utf-8") as f:
        text = f.read()

    text = detab_and_normalize(text)
    lines = text.split("\n")
    # Re-add trailing newline to all but the last split parts
    lines = [ln + "\n" for ln in lines[:-1]] + ([lines[-1] + "\n"] if lines else [])

    # Version header
    lines = ensure_version_header(lines, report)
    # nlu root
    lines = wrap_under_nlu_if_needed(lines, report)
    # examples fixing
    lines = fix_examples_blocks(lines, report)

    out_text = "".join(lines)

    ok = optional_yaml_validate(out_text, report)

    # Always write output
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(out_text)

    # Write report
    rep_path = dst + ".report.json"
    with open(rep_path, "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2)

    if ok:
        print(f"[ok] Wrote fixed YAML to: {dst}")
    else:
        print(f"[warn] YAML may still contain issues. Wrote best-effort fix to: {dst}")
    print(f"[info] Change report: {rep_path}")

if __name__ == "__main__":
    main()
