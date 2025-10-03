# COMMAND:
# py scpy/scan_top_keys.py domain.yml
import re, sys

path = sys.argv[1] if len(sys.argv) > 1 else "domain.yml"
top = {}
with open(path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, start=1):
        if line.lstrip().startswith("#"):  # ignore comments
            continue
        if line.startswith(" ") or line.startswith("\t"):  # ignore indented keys
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*$", line)
        if m:
            key = m.group(1)
            top.setdefault(key, []).append(i)

dupes = {k:v for k,v in top.items() if len(v) > 1}
if not dupes:
    print("No duplicate top-level keys found.")
else:
    print("Duplicate top-level keys (key: line_numbers):")
    for k, lines in dupes.items():
        print(f" - {k}: {lines}")
