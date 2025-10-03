#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translate Rasa NLU + domain YAML into Cebuano/Bisaya while preserving structure.

What it does
------------
- Loads Rasa `nlu.yml` and/or `domain.yml`
- Translates only user-visible text:
  * NLU examples (each "- ...")
  * Domain responses: `text`, button `title`
- Preserves:
  * intent names, entity names, slot keys, action names, response keys
  * payloads starting with "/" (intents), entity labels (e.g., [text](entity))
  * URLs (http/https), emails, code/JSON blocks
- Writes `<input>_ceb.yml` files + JSON report of counts and skipped items
- Lets you plug in any translator: Google/DeepL/LLM, or a simple glossary

Usage
-----
python scpy/rasa_yaml_translate_ceb.py --nlu data/nlu.yml --domain domain.yml --out-dir data_translated --engine glossary --glossary scpy/glossary_ceb.json

python scpy/rasa_yaml_translate_ceb.py --nlu data/nlu.yml --domain domain.yml --out-dir data_translated --engine callable --callable mytrans.mod:to_ceb



Engines
-------
--engine glossary  : local dictionary-based translator (fast, offline, limited quality)
--engine noop      : no translation (dry-run structure pass)
--engine callable  : import a Python function `translate(text)->str` from a module path you provide with --callable "mymod:myfunc"
                     You can implement calls to an LLM or API there.
"""

import argparse, os, re, yaml, json, importlib, copy
from typing import Dict, Any, List, Tuple

URL_RE = re.compile(r'(https?://\S+)', re.I)
EMAIL_RE = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
INTENT_PAYLOAD_RE = re.compile(r'^/\w')  # e.g., /book_appointment
ENTITY_ANN_RE = re.compile(r'\[(?P<text>.+?)\]\((?P<label>[^)\s]+)(?:\s+"[^"]*")?\)')
CODE_FENCE_RE = re.compile(r'```.*?```', re.S)
JSON_LIKE_RE = re.compile(r'^\s*\{.*\}\s*$', re.S)

def load_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml(obj: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True)

# --------------------- Translation Engines ---------------------
class Translator:
    def translate(self, text: str) -> str:
        raise NotImplementedError

class NoopTranslator(Translator):
    def translate(self, text: str) -> str:
        return text

class GlossaryTranslator(Translator):
    def __init__(self, glossary: Dict[str,str]):
        # normalize to lowercase keys, sort by length desc to prefer multi-word
        self.entries = sorted([(k.lower(), v) for k,v in glossary.items()], key=lambda x: len(x[0]), reverse=True)
    def translate(self, text: str) -> str:
        out = text
        for k,v in self.entries:
            pattern = re.compile(r'\b' + re.escape(k) + r'\b', re.I)
            out = pattern.sub(v, out)
        return out

class CallableTranslator(Translator):
    def __init__(self, module_func: str):
        mod, func = module_func.split(":")
        m = importlib.import_module(mod)
        self.fn = getattr(m, func)
    def translate(self, text: str) -> str:
        return self.fn(text)

def build_translator(engine: str, glossary_path: str=None, callable_spec: str=None) -> Translator:
    if engine == "noop":
        return NoopTranslator()
    if engine == "glossary":
        if not glossary_path:
            raise ValueError("--glossary is required for engine=glossary")
        with open(glossary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return GlossaryTranslator(data)
    if engine == "callable":
        if not callable_spec:
            raise ValueError("--callable is required for engine=callable")
        return CallableTranslator(callable_spec)
    raise ValueError(f"Unknown engine: {engine}")

# --------------------- Helpers ---------------------
def protect_tokens(text: str) -> Tuple[str, Dict[str,str]]:
    repl = {}
    def repl_fn(pattern, prefix, s):
        idx = 0
        def sub(m):
            nonlocal idx
            key = f"__{prefix}{idx}__"
            repl[key] = m.group(0)
            idx += 1
            return key
        return pattern.sub(sub, s)
    out = text
    out = repl_fn(CODE_FENCE_RE, "CODE_", out)
    out = repl_fn(URL_RE, "URL_", out)
    out = repl_fn(EMAIL_RE, "MAIL_", out)
    return out, repl

def unprotect_tokens(text: str, mapping: Dict[str,str]) -> str:
    out = text
    for k,v in mapping.items():
        out = out.replace(k, v)
    return out

def translate_keep_entities(s: str, translator: Translator) -> str:
    def repl(m):
        surface = m.group("text")
        label = m.group("label")
        surface_p, tokmap = protect_tokens(surface)
        surface_t = translator.translate(surface_p)
        surface_t = unprotect_tokens(surface_t, tokmap)
        return f"[{surface_t}]({label})"
    protected, mapping = protect_tokens(s)
    result_parts = []
    last = 0
    for m in ENTITY_ANN_RE.finditer(protected):
        pre = protected[last:m.start()]
        ent = protected[m.start():m.end()]
        pre_t = translator.translate(pre) if pre.strip() and not INTENT_PAYLOAD_RE.match(pre.strip()) else pre
        ent_t = repl(m)
        result_parts.append(pre_t + ent_t)
        last = m.end()
    rest = protected[last:]
    rest_t = translator.translate(rest) if rest.strip() and not INTENT_PAYLOAD_RE.match(rest.strip()) else rest
    out = "".join(result_parts) + rest_t
    out = unprotect_tokens(out, mapping)
    return out

# --------------------- NLU processing ---------------------
def process_nlu(nlu_obj: Any, translator: Translator, report: Dict) -> Any:
    if not isinstance(nlu_obj, dict):
        return nlu_obj
    if "nlu" not in nlu_obj:
        return nlu_obj
    new = copy.deepcopy(nlu_obj)
    count_examples = 0

    for item in new.get("nlu", []):
        if not isinstance(item, dict):
            continue
        ex = item.get("examples")
        if isinstance(ex, str):
            lines = ex.splitlines()
            fixed_lines = []
            for ln in lines:
                if not ln.strip():
                    fixed_lines.append(ln)
                    continue
                m = re.match(r'^(\s*)-\s+(.*)$', ln)
                if m:
                    lead, text = m.group(1), m.group(2)
                    if JSON_LIKE_RE.match(text.strip()) or INTENT_PAYLOAD_RE.match(text.strip()):
                        fixed_lines.append(ln)
                        continue
                    t = translate_keep_entities(text, translator)
                    fixed_lines.append(f"{lead}- {t}")
                    count_examples += 1
                else:
                    fixed_lines.append(ln)
            item["examples"] = "\n".join(fixed_lines) + ("\n" if ex.endswith("\n") else "")
    report["nlu_examples_translated"] = count_examples
    return new

# --------------------- DOMAIN processing ---------------------
def process_domain(domain_obj: Any, translator: Translator, report: Dict) -> Any:
    if not isinstance(domain_obj, dict):
        return domain_obj
    new = copy.deepcopy(domain_obj)
    count_texts = 0
    count_button_titles = 0

    resp = new.get("responses")
    if isinstance(resp, dict):
        for rkey, variants in resp.items():
            if not isinstance(variants, list):
                continue
            for var in variants:
                if not isinstance(var, dict):
                    continue
                if "text" in var and isinstance(var["text"], str):
                    txt = var["text"]
                    ptxt, mp = protect_tokens(txt)
                    var["text"] = unprotect_tokens(translator.translate(ptxt), mp)
                    count_texts += 1
                if "buttons" in var and isinstance(var["buttons"], list):
                    for btn in var["buttons"]:
                        if isinstance(btn, dict) and "title" in btn and isinstance(btn["title"], str):
                            ttxt, mp = protect_tokens(btn["title"])
                            btn["title"] = unprotect_tokens(translator.translate(ttxt), mp)
                            count_button_titles += 1
    report["domain_texts_translated"] = count_texts
    report["domain_button_titles_translated"] = count_button_titles
    return new

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nlu", help="Path to nlu.yml")
    ap.add_argument("--domain", help="Path to domain.yml")
    ap.add_argument("--out-dir", required=True, help="Directory to write translated files")
    ap.add_argument("--engine", choices=["noop","glossary","callable"], default="glossary")
    ap.add_argument("--glossary", help="Path to glossary JSON (for engine=glossary)")
    ap.add_argument("--callable", dest="callable_spec", help="Module:function implementing translate(text)->str (for engine=callable)")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    translator = build_translator(args.engine, args.glossary, args.callable_spec)

    report = {}
    if args.nlu:
        nlu = load_yaml(args.nlu)
        nlu_t = process_nlu(nlu, translator, report)
        nlu_out = os.path.join(args.out_dir, os.path.basename(args.nlu).replace(".yml", "_ceb.yml"))
        save_yaml(nlu_t, nlu_out)
        report["nlu_out"] = nlu_out

    if args.domain:
        dom = load_yaml(args.domain)
        dom_t = process_domain(dom, translator, report)
        dom_out = os.path.join(args.out_dir, os.path.basename(args.domain).replace(".yml", "_ceb.yml"))
        save_yaml(dom_t, dom_out)
        report["domain_out"] = dom_out

    rep_path = os.path.join(args.out_dir, "translate_report.json")
    with open(rep_path, "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
