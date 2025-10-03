# COMMAND
# py scpy/check_domain.py

from rasa.shared.utils.io import read_yaml_file
from rasa.shared.exceptions import YamlSyntaxException

def main():
    try:
        domain = read_yaml_file("domain.yml")
    except YamlSyntaxException as e:
        print("YAML error loading domain.yml:\n", e)
        print("\nTip: You likely have multiple 'responses:' blocks. Merge them into one.")
        return

    print("\n=== RESPONSES ===")
    for r in domain.get("responses", {}):
        print(f" - {r}")

    print("\n=== ACTIONS ===")
    for a in domain.get("actions", []):
        print(f" - {a}")

    print("\n=== FORMS ===")
    for f, slots in domain.get("forms", {}).items():
        print(f"Form: {f}")
        if f.startswith("utter_"):
            print("   ⚠ Looks like a response, not a form! Move this to 'responses:'")
        if isinstance(slots, dict):
            for s in slots.get("required_slots", {}):
                print(f"   - slot: {s}")
        else:
            print("   ⚠ Unexpected format under form, expected dict with required_slots")

if __name__ == "__main__":
    main()
