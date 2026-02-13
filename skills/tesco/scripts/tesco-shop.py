#!/usr/bin/env python3
"""Tesco meal prep helper: consolidate ingredients and generate shopping lists.

Usage:
  # Consolidate ingredients from multiple recipes
  python3 tesco-shop.py consolidate --input ingredients.json

  # Consolidate from stdin
  echo '[...]' | python3 tesco-shop.py consolidate

  # Parse a plain-text ingredient list into structured JSON
  python3 tesco-shop.py parse --input raw-ingredients.txt

Input format for consolidate (JSON):
  [
    {
      "recipe": "Salmon Pasta",
      "ingredients": [
        {"qty": 2, "unit": "fillets", "item": "salmon"},
        {"qty": 200, "unit": "ml", "item": "cream"},
        {"qty": 1, "unit": "tbsp", "item": "olive oil"}
      ]
    },
    ...
  ]

Output: consolidated shopping list as JSON.
"""

import argparse
import json
import re
import sys
from collections import defaultdict

# Pantry staples: items you likely already have. Buy once regardless of recipe count.
PANTRY_STAPLES = {
    "salt",
    "pepper",
    "black pepper",
    "white pepper",
    "olive oil",
    "vegetable oil",
    "sunflower oil",
    "cooking oil",
    "butter",
    "sugar",
    "caster sugar",
    "brown sugar",
    "plain flour",
    "self-raising flour",
    "baking powder",
    "bicarbonate of soda",
    "dried oregano",
    "dried basil",
    "dried thyme",
    "paprika",
    "cumin",
    "chilli flakes",
    "garlic powder",
    "onion powder",
    "soy sauce",
    "worcestershire sauce",
    "stock cubes",
    "chicken stock cubes",
    "beef stock cubes",
    "vegetable stock cubes",
    "tomato puree",
    "vinegar",
    "white wine vinegar",
    "balsamic vinegar",
    "honey",
    "mustard",
    "dijon mustard",
}

# Unit normalization map
UNIT_ALIASES = {
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "ml": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "l": "l",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "tbsp": "tbsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tsp": "tsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "cup": "cup",
    "cups": "cup",
    "pcs": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "fillet": "fillets",
    "fillets": "fillets",
    "breast": "breasts",
    "breasts": "breasts",
    "clove": "cloves",
    "cloves": "cloves",
    "bunch": "bunch",
    "bunches": "bunch",
    "tin": "tins",
    "tins": "tins",
    "can": "tins",
    "cans": "tins",
    "pack": "packs",
    "packs": "packs",
    "packet": "packs",
    "packets": "packs",
    "bag": "bags",
    "bags": "bags",
    "slice": "slices",
    "slices": "slices",
    "rasher": "rashers",
    "rashers": "rashers",
    "sprig": "sprigs",
    "sprigs": "sprigs",
    "handful": "handfuls",
    "handfuls": "handfuls",
    "pinch": "pinch",
    "dash": "dash",
    "drizzle": "drizzle",
    "splash": "splash",
}

# Units that can be summed (same dimension)
SUMMABLE_UNITS = {
    "g", "kg", "ml", "l", "tbsp", "tsp", "cup",
    "pcs", "fillets", "breasts", "cloves", "tins", "packs", "bags",
    "slices", "rashers", "sprigs", "handfuls", "bunch",
}

# Conversion factors to a base unit for summation
UNIT_CONVERSIONS = {
    "kg": ("g", 1000),
    "l": ("ml", 1000),
}


def normalize_unit(unit: str) -> str:
    """Normalize a unit string to a canonical form."""
    unit = unit.strip().lower()
    return UNIT_ALIASES.get(unit, unit)


def normalize_item(item: str) -> str:
    """Normalize an item name for deduplication."""
    item = item.strip().lower()
    # Remove leading articles
    item = re.sub(r"^(a |an |the |some )", "", item)
    # Remove trailing qualifiers in parens like "(chopped)" or "(diced)"
    item = re.sub(r"\s*\(.*?\)\s*$", "", item)
    return item.strip()


def is_pantry_staple(item: str) -> bool:
    """Check if an item is a pantry staple."""
    return normalize_item(item) in PANTRY_STAPLES


def convert_to_base(qty: float, unit: str) -> tuple[float, str]:
    """Convert kg->g, l->ml for consistent summation."""
    if unit in UNIT_CONVERSIONS:
        base_unit, factor = UNIT_CONVERSIONS[unit]
        return qty * factor, base_unit
    return qty, unit


def consolidate(recipes: list[dict]) -> dict:
    """Consolidate ingredients across recipes.

    Returns:
        {
          "shopping_list": [...],
          "pantry_staples": [...],
          "by_recipe": {...}
        }
    """
    # Collect all ingredients keyed by normalized name + unit
    merged: dict[str, dict] = defaultdict(
        lambda: {"qty": 0, "unit": "", "item": "", "sources": []}
    )

    for recipe in recipes:
        recipe_name = recipe.get("recipe", "Unknown")
        for ing in recipe.get("ingredients", []):
            raw_item = ing.get("item", "")
            raw_unit = ing.get("unit", "")
            raw_qty = float(ing.get("qty", 0) or 0)

            norm_item = normalize_item(raw_item)
            norm_unit = normalize_unit(raw_unit)

            # Convert to base units for consistent summation
            base_qty, base_unit = convert_to_base(raw_qty, norm_unit)

            key = f"{norm_item}|{base_unit}"
            entry = merged[key]
            entry["item"] = norm_item
            entry["unit"] = base_unit
            entry["sources"].append(recipe_name)

            if is_pantry_staple(norm_item):
                # Pantry staples: don't sum, just mark as needed
                entry["qty"] = max(entry["qty"], base_qty)
                entry["pantry"] = True
            else:
                # Regular items: sum quantities
                entry["qty"] += base_qty

    # Split into shopping list and pantry staples
    shopping_list = []
    pantry_staples = []

    for entry in sorted(merged.values(), key=lambda e: e["item"]):
        result = {
            "item": entry["item"],
            "qty": round(entry["qty"], 1) if entry["qty"] else None,
            "unit": entry["unit"] if entry["unit"] else None,
            "sources": sorted(set(entry["sources"])),
        }
        # Clean up display: convert back to kg/l if large
        if result["unit"] == "g" and result["qty"] and result["qty"] >= 1000:
            result["qty"] = round(result["qty"] / 1000, 2)
            result["unit"] = "kg"
        if result["unit"] == "ml" and result["qty"] and result["qty"] >= 1000:
            result["qty"] = round(result["qty"] / 1000, 2)
            result["unit"] = "l"

        if entry.get("pantry"):
            pantry_staples.append(result)
        else:
            shopping_list.append(result)

    return {
        "shopping_list": shopping_list,
        "pantry_staples": pantry_staples,
        "total_items": len(shopping_list) + len(pantry_staples),
        "total_shopping": len(shopping_list),
        "total_pantry": len(pantry_staples),
    }


# --- Plain text ingredient parser ---

# Unit keywords (longer first to avoid partial matches like "l" eating "lemon")
_UNIT_WORDS = (
    r"tablespoons?|teaspoons?|kilograms?|millilitres?|milliliters?"
    r"|litres?|liters?|grams?"
    r"|fillets?|breasts?|cloves?|bunch(?:es)?|tins?|cans?"
    r"|packs?|packets?|bags?|slices?|rashers?|sprigs?"
    r"|handfuls?|pieces?|cups?"
    r"|tbsp|tsp|kg|ml|g"
    r"|pinch|dash|drizzle|splash"
)

# Pattern: optional qty (number/fraction), optional unit (word-bounded), item name
QTY_PATTERN = re.compile(
    r"^"
    r"(?P<qty>\d+(?:[./]\d+)?(?:\s*-\s*\d+(?:[./]\d+)?)?|half|quarter)?"
    r"\s*"
    r"(?P<unit>" + _UNIT_WORDS + r")?"
    r"(?:\b|\s)"
    r"\s*(?:of\s+|a\s+)?"
    r"(?P<item>.+)"
    r"$",
    re.IGNORECASE,
)

FRACTION_MAP = {"half": 0.5, "quarter": 0.25}


def parse_qty(raw: str) -> float:
    """Parse a quantity string to float."""
    if not raw:
        return 0
    raw = raw.strip().lower()
    if raw in FRACTION_MAP:
        return FRACTION_MAP[raw]
    # Handle fractions like 1/2
    if "/" in raw:
        parts = raw.split("/")
        try:
            return float(parts[0]) / float(parts[1])
        except (ValueError, ZeroDivisionError):
            return 0
    # Handle ranges like 2-3 (take the higher)
    if "-" in raw:
        parts = raw.split("-")
        try:
            return float(parts[-1])
        except ValueError:
            return 0
    try:
        return float(raw)
    except ValueError:
        return 0


def parse_ingredient_line(line: str) -> dict | None:
    """Parse a single ingredient line into structured form."""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None
    # Strip leading list markers (bullets, "1.", "2)") but preserve qty digits
    line = re.sub(r"^(?:[\-\*\u2022]\s*|\d+[.)]\s+)", "", line).strip()
    if not line:
        return None

    match = QTY_PATTERN.match(line)
    if match:
        return {
            "qty": parse_qty(match.group("qty") or ""),
            "unit": normalize_unit(match.group("unit") or ""),
            "item": match.group("item").strip().rstrip(",;."),
        }
    # Fallback: treat the whole line as the item
    return {"qty": 0, "unit": "", "item": line.rstrip(",;.")}


def parse_ingredients(text: str) -> list[dict]:
    """Parse a block of plain-text ingredients into structured JSON."""
    results = []
    for line in text.splitlines():
        parsed = parse_ingredient_line(line)
        if parsed:
            results.append(parsed)
    return results


def cmd_consolidate(args: argparse.Namespace) -> int:
    """Consolidate ingredients from multiple recipes."""
    if args.input:
        with open(args.input) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    result = consolidate(data)
    print(json.dumps(result, indent=2))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse plain-text ingredients into structured JSON."""
    if args.input:
        with open(args.input) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    results = parse_ingredients(text)
    print(json.dumps(results, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Tesco meal prep helper: consolidate ingredients and generate shopping lists."
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_consolidate = sub.add_parser(
        "consolidate",
        help="Merge and deduplicate ingredients from multiple recipes",
    )
    p_consolidate.add_argument(
        "--input", "-i", help="JSON file path (default: stdin)"
    )

    p_parse = sub.add_parser(
        "parse",
        help="Parse plain-text ingredient list into structured JSON",
    )
    p_parse.add_argument(
        "--input", "-i", help="Text file path (default: stdin)"
    )

    args = ap.parse_args()

    if args.command == "consolidate":
        return cmd_consolidate(args)
    elif args.command == "parse":
        return cmd_parse(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
