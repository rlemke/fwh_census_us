"""Census metric registry — the single source of truth for the indicator set.

Each metric declares how to compute a county/state value from raw ACS columns,
how to format it, which "direction" is worse (for ranking + the SVI), and whether
it contributes to the Social Vulnerability Index. The registry drives:

- the per-county derived values (``compute_metrics``),
- the per-state multi-metric choropleth (its dropdown),
- the national state rankings + choropleths,
- the SVI (``in_svi`` metrics, all oriented so higher = more vulnerable).

ACS tables used: B17001 (poverty), B23025 (employment), B15003 (education),
B25044 (vehicles), B01001 (age + total population), B25003 (tenure),
B19013 (median income), B19083 (Gini), B19058 (public assistance/SNAP),
B27001 (health insurance), B03002 (race/ethnicity), B05002 (nativity /
foreign-born), B07003 (geographic mobility / recent movers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# B01001 age bands for 65+ (male _020..025, female _044..049).
_AGE_65_PLUS = [f"B01001_{i:03d}E" for i in range(20, 26)] + [
    f"B01001_{i:03d}E" for i in range(44, 50)
]
# B15003 "less than high school" = no schooling (_002) .. 12th grade no diploma (_016).
_LT_HS = [f"B15003_{i:03d}E" for i in range(2, 17)]
# B27001 "No health insurance coverage" cells (male + female, all age bands).
_UNINSURED = [
    "B27001_005E", "B27001_008E", "B27001_011E", "B27001_014E", "B27001_017E",
    "B27001_020E", "B27001_023E", "B27001_026E", "B27001_029E", "B27001_033E",
    "B27001_036E", "B27001_039E", "B27001_042E", "B27001_045E", "B27001_048E",
    "B27001_051E", "B27001_054E", "B27001_057E",
]


@dataclass
class Metric:
    key: str
    label: str
    fmt: str  # "pct" | "dollar" | "index"
    worse: str  # "high" (more = more vulnerable) | "low" (less = more vulnerable)
    in_svi: bool  # contributes to the Social Vulnerability Index
    num: list[str] = field(default_factory=list)  # numerator columns (summed)
    den: str | None = None  # denominator column
    raw: str | None = None  # direct value column (median income, gini)
    invert: bool = False  # value = scale - (num/den*scale)  (e.g. "no bachelor's")
    scale: float = 100.0


# Order here = display order in the dropdown / rankings.
METRICS: list[Metric] = [
    Metric("poverty", "Below poverty", "pct", "high", True,
           num=["B17001_002E"], den="B17001_001E"),
    Metric("unemployment", "Unemployment", "pct", "high", True,
           num=["B23025_005E"], den="B23025_003E"),
    Metric("no_bachelors", "No bachelor's degree", "pct", "high", True,
           num=["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"],
           den="B15003_001E", invert=True),
    Metric("no_vehicle", "No vehicle", "pct", "high", True,
           num=["B25044_003E", "B25044_010E"], den="B25044_001E"),
    Metric("elderly", "Aged 65+", "pct", "high", True,
           num=_AGE_65_PLUS, den="B01001_001E"),
    Metric("renter", "Renter-occupied", "pct", "high", True,
           num=["B25003_003E"], den="B25003_001E"),
    Metric("less_than_hs", "Less than high school", "pct", "high", True,
           num=_LT_HS, den="B15003_001E"),
    Metric("hs_only", "High school only", "pct", "high", True,
           num=["B15003_017E", "B15003_018E"], den="B15003_001E"),
    Metric("snap", "SNAP / public assistance", "pct", "high", True,
           num=["B19058_002E"], den="B19058_001E"),
    Metric("uninsured", "No health insurance", "pct", "high", True,
           num=_UNINSURED, den="B27001_001E"),
    Metric("gini", "Income inequality (Gini)", "index", "high", True,
           raw="B19083_001E", scale=1.0),
    # Standalone (NOT in the SVI — these are inverse / wealth indicators):
    Metric("grad_degree", "Graduate/professional degree", "pct", "low", False,
           num=["B15003_023E", "B15003_024E", "B15003_025E"], den="B15003_001E"),
    Metric("median_income", "Median household income", "dollar", "low", False,
           raw="B19013_001E", scale=1.0),
    # Demographic context (standalone, NOT in the SVI — no "worse" direction;
    # worse="high" just orients dark=more / rank highest-first).
    Metric("total_population", "Total population", "count", "high", False,
           raw="B01001_001E", scale=1.0),
    Metric("people_of_color", "People of color", "pct", "high", False,
           num=["B03002_003E"], den="B03002_001E", invert=True),
    Metric("hispanic", "Hispanic / Latino", "pct", "high", False,
           num=["B03002_012E"], den="B03002_001E"),
    Metric("black", "Black", "pct", "high", False,
           num=["B03002_004E"], den="B03002_001E"),
    Metric("asian", "Asian", "pct", "high", False,
           num=["B03002_006E"], den="B03002_001E"),
    Metric("white_nh", "White (non-Hispanic)", "pct", "high", False,
           num=["B03002_003E"], den="B03002_001E"),
    Metric("foreign_born", "Foreign-born", "pct", "high", False,
           num=["B05002_013E"], den="B05002_001E"),
    Metric("recent_movers", "Recent movers (past year)", "pct", "high", False,
           num=["B07003_007E", "B07003_010E", "B07003_013E", "B07003_016E"],
           den="B07003_001E"),
]

BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}
SVI_METRICS: list[Metric] = [m for m in METRICS if m.in_svi]

# ACS tables every metric needs joined onto the county geometry.
REQUIRED_TABLES = [
    "B17001", "B23025", "B15003", "B25044", "B01001", "B25003",
    "B19013", "B19083", "B19058", "B27001",
    # Demographic context: B01001_001E (total pop, already pulled via B01001),
    # B03002 (race/ethnicity), B05002 (nativity), B07003 (geographic mobility).
    "B03002", "B05002", "B07003",
]


def _num(props: dict[str, Any], key: str) -> float | None:
    v = props.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_metric(props: dict[str, Any], m: Metric) -> float | None:
    """Compute one metric's value for a feature's properties, or None if the
    source columns are missing."""
    if m.raw is not None:
        v = _num(props, m.raw)
        # ACS uses large negative sentinels for "no data" (e.g. -666666666).
        if v is None or v <= -1e8:
            return None
        return round(v, 4 if m.fmt == "index" else 0 if m.fmt in ("dollar", "count") else 2)
    den = _num(props, m.den) if m.den else None
    if den is None or den == 0:
        return None
    total = sum(v for v in (_num(props, k) for k in m.num) if v is not None)
    val = total / den * m.scale
    if m.invert:
        val = m.scale - val
    return round(val, 2)


def compute_metrics(props: dict[str, Any]) -> dict[str, float | None]:
    """All metric values for one feature, keyed by metric key."""
    return {m.key: compute_metric(props, m) for m in METRICS}
