# quick_autofix_block_scalars.py
# COMMAND
# python scpy\quick_domain_fix.py
# python scpy\quick_domain_fix.py --in domain.yml.autofixed.yml --out domain_fixed.yml

import re

path = "domain.yml"
with open(path, "r", encoding="utf-8-sig") as f:
    lines = f.readlines()

changed = 0
# detab
lines = [ln.replace("\t", "  ") for ln in lines]

i = 0
while i < len(lines):
    ln = lines[i]
    m = re.match(r'^(\s*)text:\s*\|[-\+]?(\s*)$', ln)
    if m:
        base = len(m.group(1))
        # find next non-empty
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j < len(lines):
            cur_ind = len(lines[j]) - len(lines[j].lstrip(" "))
            if cur_ind <= base:
                lines[j] = " " * (base + 2) + lines[j].lstrip(" ")
                changed += 1
    i += 1

if changed:
    with open(path + ".autofixed.yml", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    print(f"Auto-indented {changed} block-scalar start(s). Wrote {path}.autofixed.yml")
else:
    print("No obvious block-scalar indentation issues fixed.")
