"""compute_strength_equivalents: turn pounds lifted into fun comparisons.

Pure calculation (no database). Every comparison uses a real approximate weight with a source
checked on 2026-10-22; they are fun approximations, not measurements.
"""

# Smallest to largest. unit_weight_lbs is the approximate weight of ONE of the thing.
COMPARISONS = [
    {
        "key": "bowling_balls",
        "name": "bowling balls",
        "singular": "bowling ball",
        "unit_weight_lbs": 16,
        "basis": "Heaviest legal ten-pin ball, 16 lb (7.3 kg)",
        "source": "USBC Equipment Specifications and Certifications Manual, via https://en.wikipedia.org/wiki/Bowling_ball",
    },
    {
        "key": "grand_pianos",
        "name": "concert grand pianos",
        "singular": "concert grand piano",
        "unit_weight_lbs": 1064,
        "basis": "Steinway Model D concert grand, net weight 1,064 lb (483 kg)",
        "source": "https://www.steinway.com/pianos/steinway/grand/model-d",
    },
    {
        "key": "cars",
        "name": "full-size cars",
        "singular": "full-size car",
        "unit_weight_lbs": 4354,
        "basis": "Average new US vehicle, model year 2024: 4,354 lb",
        "source": "EPA, The 2025 EPA Automotive Trends Report (EPA-420-R-26-001, Feb 2026), section 3, 'Weight'",
    },
    {
        "key": "trees",
        "name": "full-size trees",
        "singular": "full-size tree",
        "unit_weight_lbs": 4820,
        "basis": "Trunk (merchantable stem) of a mature hardwood 20 inches across at breast height: 2.41 tons. "
                 "Branches and roots would add more, so this is conservative",
        "source": "University of Arkansas Division of Agriculture, 'Landowner's Guide to Determining Weight of "
                  "Standing Hardwood Trees' (FSA5021), Table 1",
    },
    {
        "key": "elephants",
        "name": "adult elephants",
        "singular": "adult elephant",
        "unit_weight_lbs": 11700,
        "basis": "Adult male African elephant: 4,500-6,100 kg; midpoint 5,300 kg is about 11,700 lb",
        "source": "Animal Diversity Web, University of Michigan Museum of Zoology: Loxodonta africana, "
                  "https://animaldiversity.org/accounts/Loxodonta_africana/",
    },
    {
        "key": "blue_whales",
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


def compute_strength_equivalents(total_weight_lifted_lbs: float) -> dict:
    """Comparisons for a total weight lifted (pounds). Raises ValueError on a negative or absurd total."""
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
            "basis": c["basis"],
            "source": c["source"],
        })

    # Headline: the biggest thing the total reaches. Below one bowling ball, say what fraction of one.
    reached = [c for c in comparisons if c["count"] >= 1]
    pick = reached[-1] if reached else comparisons[0]
    headline = f"You've lifted {pick['phrase']}!" if reached else (
        f"You've lifted {pick['count_text']} of a bowling ball. Keep going!")
    return {
        "total_weight_lifted_lbs": round(total, 1),
        "headline": headline,
        "headline_comparison": pick["name"],
        "comparisons": comparisons,
        "note": "Fun approximations, not measurements. Each comparison lists its basis and source.",
    }
