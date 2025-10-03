#!/usr/bin/env python3
"""
translate_rasa_to_ceb.py
----------------------------------
Auto-translate Rasa domain.yml and nlu.yml to Cebuano/Bisaya while keeping
ALL identifiers (intents, actions, slots) and payloads unchanged.

What gets translated:
  - domain.yml: responses[*].text, button titles, and common display fields (title, subtitle, description)
  - nlu.yml: each examples line (the text after "- ")

What is preserved (NOT translated):
  - intent names (e.g., anxiety_p0001) and the intents list
  - payloads in buttons
  - placeholders like {APPOINTMENT_LINK}, {slot_name}
  - entity labels in examples: the (entity) part is preserved; the [value] text can be translated
  - URLs (http://, https://), emojis, and non-text punctuation

Requires:
  pip install pyyaml deep-translator

Usage:
  python scpy/translate_rasa_to_ceb.py --domain-in "C:\BSIT JOURNEY\capstone\RASA\Lumichat_v1.7\lumichat-backend\rasa-bot\domain.yml" --nlu-in "C:\BSIT JOURNEY\capstone\RASA\Lumichat_v1.7\lumichat-backend\rasa-bot\data\nlu.yml" --domain-out "C:\BSIT JOURNEY\capstone\RASA\Lumichat_v1.7\lumichat-backend\rasa-bot\domain_ceb.yml" --nlu-out "C:\BSIT JOURNEY\capstone\RASA\Lumichat_v1.7\lumichat-backend\rasa-bot\data\nlu_ceb.yml"

Tip for LibreTranslate (offline/self-hosted): https://github.com/LibreTranslate/LibreTranslate
"""
import argparse
import re
import sys
from typing import List, Tuple
import yaml

# Translation providers
try:
    from deep_translator import GoogleTranslator, LibreTranslator
except Exception as e:
    GoogleTranslator = None
    LibreTranslator = None

# -------- Helpers for protecting spans we must NOT translate --------

PLACEHOLDER_PATTERNS = [
    r"\{[^}]+\}",                # {APPOINTMENT_LINK}, {slot_name}
    r"\[[^\]]+\]\([^)]+\)",      # markdown links [text](url)
    r"https?://\S+",             # URLs
]

ENTITY_SPAN_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")  # [value](entity)

def protect_spans(text: str, extra_patterns: List[str] = None) -> Tuple[str, List[str]]:
    """Replace protected spans with tokens __PH_i__ and return (masked_text, spans)."""
    patterns = PLACEHOLDER_PATTERNS[:]
    if extra_patterns:
        patterns.extend(extra_patterns)

    spans = []
    masked = text

    for patt in patterns:
        # replace left-to-right to ensure stable indexing
        while True:
            m = re.search(patt, masked)
            if not m:
                break
            spans.append(m.group(0))
            token = f"__PH_{len(spans)-1}__"
            masked = masked[:m.start()] + token + masked[m.end():]

    return masked, spans

def unprotect_spans(text: str, spans: List[str]) -> str:
    for i, s in enumerate(spans):
        text = text.replace(f"__PH_{i}__", s)
    return text

def split_entity_spans(text: str) -> List[Tuple[str, str, str]]:
    """
    Split an example into segments where entity spans [value](entity) are isolated.
    Returns list of tuples (kind, content, entity) where:
      - kind == 'entity'  : content is the value, entity is the label (we will translate content only)
      - kind == 'text'    : content is plain text, entity is ''
    """
    parts = []
    last = 0
    for m in ENTITY_SPAN_RE.finditer(text):
        if m.start() > last:
            parts.append(("text", text[last:m.start()], ""))
        parts.append(("entity", m.group(1), m.group(2)))
        last = m.end()
    if last < len(text):
        parts.append(("text", text[last:], ""))
    return parts

# ------------- Translator wrapper -------------

class CebuanoTranslator:
    def __init__(self, provider="google", libre_url=None):
        self.provider = provider
        if provider == "google":
            if GoogleTranslator is None:
                raise RuntimeError("deep-translator is not installed. Run: pip install deep-translator")
            self.t = GoogleTranslator(source="auto", target="ceb")
        elif provider == "libre":
            if LibreTranslator is None:
                raise RuntimeError("deep-translator is not installed. Run: pip install deep-translator")
            if not libre_url:
                raise ValueError("--libre-url is required when provider=libre")
            self.t = LibreTranslator(source="auto", target="ceb", api_url=libre_url)
        else:
            raise ValueError("Unknown provider. Use 'google' or 'libre'.")

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return text
        # Protect spans we must not translate
        masked, spans = protect_spans(text)
        # Call provider
        try:
            out = self.t.translate(masked)
        except Exception:
            # fallback to original if provider fails
            return text
        # Restore protected spans
        out = unprotect_spans(out, spans)
        # Basic cleanup
        out = re.sub(r"\s+", " ", out).strip()
        return out

    def translate_batch(self, texts: List[str]) -> List[str]:
        results = []
        for txt in texts:
            results.append(self.translate(txt))
        return results

# ------------- domain.yml translation -------------

DISPLAY_FIELDS = ("text", "title", "subtitle", "description", "label")

def translate_domain(data: dict, tr: CebuanoTranslator) -> dict:
    out = yaml.safe_load(yaml.dump(data))  # deep copy
    responses = out.get("responses", {})
    for utter, variants in list(responses.items()):
        if isinstance(variants, list):
            for v in variants:
                if not isinstance(v, dict):
                    continue
                # Translate known display fields
                for key in DISPLAY_FIELDS:
                    if key in v and isinstance(v[key], str):
                        v[key] = tr.translate(v[key])
                # Translate buttons' titles (keep payloads)
                if "buttons" in v and isinstance(v["buttons"], list):
                    for btn in v["buttons"]:
                        if isinstance(btn, dict) and "title" in btn and isinstance(btn["title"], str):
                            btn["title"] = tr.translate(btn["title"])
                        # never touch payload
    return out

# ------------- nlu.yml translation -------------

def translate_nlu(data: dict, tr: CebuanoTranslator, batch_size: int = 30) -> dict:
    out = yaml.safe_load(yaml.dump(data))  # deep copy
    nlu_blocks = out.get("nlu", [])
    for block in nlu_blocks:
        ex = block.get("examples")
        if not isinstance(ex, str):
            continue
        # Split into lines and process only lines that start with '- '
        lines = ex.splitlines()
        new_lines = []
        buffer = []

        def flush_buffer():
            nonlocal buffer, new_lines
            if not buffer:
                return
            translated = tr.translate_batch(buffer)
            new_lines.extend([f"- {t}" for t in translated])
            buffer = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                text = line.split("- ", 1)[1]

                # Preserve [value](entity): translate value only, not "(entity)" label
                parts = split_entity_spans(text)
                rebuilt = ""
                ent_idx = 0
                for kind, content, ent in parts:
                    if kind == "text":
                        rebuilt += content
                    else:
                        rebuilt += f"[__ENTVAL_{ent_idx}__]({ent})"
                        ent_idx += 1

                # Protect entity tokens so they don't get translated
                masked, spans = protect_spans(rebuilt, extra_patterns=[r"__ENTVAL_\d+__"])
                translated_text = tr.translate(masked)
                translated_text = unprotect_spans(translated_text, spans)

                # Reinsert translated entity values
                ent_idx = 0
                final_line = translated_text
                for kind, content, ent in parts:
                    if kind == "entity":
                        val_tr = tr.translate(content)
                        final_line = final_line.replace(
                            f"[__ENTVAL_{ent_idx}__]({ent})",
                            f"[{val_tr}]({ent})",
                            1
                        )
                        ent_idx += 1

                buffer.append(final_line)
            else:
                flush_buffer()
                new_lines.append(line)

        flush_buffer()
        block["examples"] = "\n".join(new_lines)

    return out

# ------------- CLI -------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain-in", required=True)
    ap.add_argument("--nlu-in", required=True)
    ap.add_argument("--domain-out", required=True)
    ap.add_argument("--nlu-out", required=True)
    ap.add_argument("--provider", choices=["google", "libre"], default="google")
    ap.add_argument("--libre-url", help="LibreTranslate server URL when --provider=libre")
    ap.add_argument("--batch-size", type=int, default=30)
    args = ap.parse_args()

    # Load YAML
    with open(args.domain_in, "r", encoding="utf-8") as f:
        domain = yaml.safe_load(f) or {}
    with open(args.nlu_in, "r", encoding="utf-8") as f:
        nlu = yaml.safe_load(f) or {}

    # Init translator
    tr = CebuanoTranslator(provider=args.provider, libre_url=args.libre_url)

    # Translate
    domain_out = translate_domain(domain, tr)
    nlu_out = translate_nlu(nlu, tr, batch_size=args.batch_size)

    # Save
    with open(args.domain_out, "w", encoding="utf-8") as f:
        yaml.dump(domain_out, f, allow_unicode=True, sort_keys=False)
    with open(args.nlu_out, "w", encoding="utf-8") as f:
        yaml.dump(nlu_out, f, allow_unicode=True, sort_keys=False)

    print("Done.")
    print("Written:", args.domain_out)
    print("Written:", args.nlu_out)

if __name__ == "__main__":
    main()
