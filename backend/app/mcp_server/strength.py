"""compute_strength_equivalents: turn pounds lifted into fun comparisons.

Pure calculation (no database). These are silly, not science: every weight is a plausible ballpark figure for
one of the thing. The original six (bowling ball, concert grand, car, tree, elephant, blue whale) cite a source
checked on 2026-10-22; the rest (added 2026-10-23 for variety) say "ballpark" in their basis.

Tone (shared_rules.md rule 5): only animals and objects. Never the user's body, food, drink, or body weight.

The headline picks the highest TIER the total reaches, then picks at random among that tier's comparisons
that the total actually reaches, so a repeat visit can say something different.
"""

import random

BALLPARK = "Ballpark figure for a fun comparison, not a measurement"

# Smallest to largest. unit_weight_lbs is the approximate weight of ONE of the thing; tier groups similar sizes.
COMPARISONS = [
    {
        "key": "chihuahuas", "tier": 1,
        "name": "chihuahuas",
        "singular": "chihuahua",
        "unit_weight_lbs": 5,
        "basis": "A chihuahua: about 3-6 lb; 5 lb used",
        "source": BALLPARK,
    },
    {
        "key": "house_cats", "tier": 1,
        "name": "house cats",
        "singular": "house cat",
        "unit_weight_lbs": 10,
        "basis": "A typical adult house cat: about 8-11 lb; 10 lb used",
        "source": BALLPARK,
    },
    {
        "key": "bowling_balls", "tier": 1,
        "name": "bowling balls",
        "singular": "bowling ball",
        "unit_weight_lbs": 16,
        "basis": "Heaviest legal ten-pin ball, 16 lb (7.3 kg)",
        "source": "USBC Equipment Specifications and Certifications Manual, via https://en.wikipedia.org/wiki/Bowling_ball",
    },
    {
        "key": "raccoons", "tier": 2,
        "name": "large raccoons",
        "singular": "large raccoon",
        "unit_weight_lbs": 25,
        "basis": "A big, well-fed raccoon: about 20-30 lb; 25 lb used",
        "source": BALLPARK,
    },
    {
        "key": "toddlers", "tier": 2,
        "name": "toddlers",
        "singular": "toddler",
        "unit_weight_lbs": 27,
        "basis": "A typical 2-year-old: about 25-30 lb; 27 lb used",
        "source": BALLPARK,
    },
    {
        "key": "golden_retrievers", "tier": 2,
        "name": "golden retrievers",
        "singular": "golden retriever",
        "unit_weight_lbs": 70,
        "basis": "An adult golden retriever: about 55-75 lb; 70 lb used",
        "source": BALLPARK,
    },
    {
        "key": "giant_pandas", "tier": 3,
        "name": "giant pandas",
        "singular": "giant panda",
        "unit_weight_lbs": 220,
        "basis": "An adult giant panda: about 150-275 lb; 220 lb used",
        "source": BALLPARK,
    },
    {
        "key": "motorcycles", "tier": 3,
        "name": "motorcycles",
        "singular": "motorcycle",
        "unit_weight_lbs": 400,
        "basis": "A typical standard motorcycle: about 350-450 lb; 400 lb used",
        "source": BALLPARK,
    },
    {
        "key": "vending_machines", "tier": 4,
        "name": "vending machines",
        "singular": "vending machine",
        "unit_weight_lbs": 800,
        "basis": "A full-size vending machine: about 600-1,000 lb; 800 lb used",
        "source": BALLPARK,
    },
    {
        "key": "grand_pianos", "tier": 4,
        "name": "concert grand pianos",
        "singular": "concert grand piano",
        "unit_weight_lbs": 1064,
        "basis": "Steinway Model D concert grand, net weight 1,064 lb (483 kg)",
        "source": "https://www.steinway.com/pianos/steinway/grand/model-d",
    },
    {
        "key": "cows", "tier": 4,
        "name": "cows",
        "singular": "cow",
        "unit_weight_lbs": 1200,
        "basis": "An adult cow: about 1,000-1,400 lb; 1,200 lb used",
        "source": BALLPARK,
    },
    {
        "key": "cars", "tier": 5,
        "name": "full-size cars",
        "singular": "full-size car",
        "unit_weight_lbs": 4354,
        "basis": "Average new US vehicle, model year 2024: 4,354 lb",
        "source": "EPA, The 2025 EPA Automotive Trends Report (EPA-420-R-26-001, Feb 2026), section 3, 'Weight'",
    },
    {
        "key": "trees", "tier": 5,
        "name": "full-size trees",
        "singular": "full-size tree",
        "unit_weight_lbs": 4820,
        "basis": "Trunk (merchantable stem) of a mature hardwood 20 inches across at breast height: 2.41 tons. "
                 "Branches and roots would add more, so this is conservative",
        "source": "University of Arkansas Division of Agriculture, 'Landowner's Guide to Determining Weight of "
                  "Standing Hardwood Trees' (FSA5021), Table 1",
    },
    {
        "key": "elephants", "tier": 6,
        "name": "adult elephants",
        "singular": "adult elephant",
        "unit_weight_lbs": 11700,
        "basis": "Adult male African elephant: 4,500-6,100 kg; midpoint 5,300 kg is about 11,700 lb",
        "source": "Animal Diversity Web, University of Michigan Museum of Zoology: Loxodonta africana, "
                  "https://animaldiversity.org/accounts/Loxodonta_africana/",
    },
    {
        "key": "blue_whales", "tier": 7,
        "name": "blue whales",
        "singular": "blue whale",
        "unit_weight_lbs": 330000,
        "basis": "A very large blue whale: up to 330,000 lb (the top of the range; smaller populations are 100,000+ lb)",
        "source": "NOAA Fisheries, Blue Whale species page, https://www.fisheries.noaa.gov/species/blue-whale",
    },
]

MAX_LBS = 1_000_000_000   # sanity cap so absurd input can't produce nonsense


def _count_text(count: float) -> str:
    """'3.2', '14', or '0.45': enough precision to feel right at each size."""
    if count >= 10:
        return f"{round(count):,}"
    if count >= 1:
        return f"{count:.1f}"
    return f"{count:.2f}"


def compute_strength_equivalents(total_weight_lifted_lbs: float, rng: random.Random | None = None) -> dict:
    """Comparisons for a total weight lifted (pounds). Raises ValueError on a negative or absurd total.
    rng picks among a tier's options (tests pass a seeded one; the app uses a fresh random pick each time)."""
    rng = rng or random.Random()
    total = float(total_weight_lifted_lbs)
    if total != total or total < 0 or total > MAX_LBS:   # total != total catches NaN
        raise ValueError(f"total_weight_lifted_lbs must be between 0 and {MAX_LBS:,}.")

    if total == 0:
        return {
            "total_weight_lifted_lbs": 0,
            "headline": None,
            "comparisons": [],
            "message": "Nothing lifted yet, so there is nothing to compare. Log a workout with weights to unlock these.",
            "note": "Fun approximations, not measurements.",
        }

    comparisons = []
    for c in COMPARISONS:
        count = total / c["unit_weight_lbs"]
        comparisons.append({
            "name": c["name"],
            "count": round(count, 2),
            "count_text": _count_text(count),
            "phrase": f"about {_count_text(count)} {c['singular'] if round(count, 1) == 1.0 else c['name']}",
            "unit_weight_lbs": c["unit_weight_lbs"],
            "tier": c["tier"],
            "basis": c["basis"],
            "source": c["source"],
        })

    # Headline: the highest tier the total reaches, then a random pick among the things in that tier it reaches.
    # Below the smallest thing (one chihuahua), say what fraction of one.
    reached = [c for c in comparisons if c["count"] >= 1]
    if reached:
        top = max(c["tier"] for c in reached)
        options = [c for c in reached if c["tier"] == top]
        pick = rng.choice(options)
        headline = f"You've lifted {pick['phrase']}!"
    else:
        options, pick = [comparisons[0]], comparisons[0]
        headline = f"You've lifted {pick['count_text']} of a {COMPARISONS[0]['singular']}. Keep going!"
    return {
        "total_weight_lifted_lbs": round(total, 1),
        "headline": headline,
        "headline_comparison": pick["name"],
        "headline_options": [c["name"] for c in options],
        "comparisons": comparisons,
        "note": "Fun approximations, not measurements. Each comparison lists its basis (and source, where one exists).",
    }
