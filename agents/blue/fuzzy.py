"""Mamdani fuzzy triage: how worried should Blue be? (outline section 06, part 2)

Inputs (each 0..1): alert strength, node value, belief confidence.
Output: threat score 0..100 by centroid defuzzification.
Below `watch` Blue ignores a node, between `watch` and `act` it watches it,
above `act` it acts.
"""

import numpy as np

OUT = np.linspace(0, 100, 101)


def tri(x, a, b, c):
    """Triangular membership; a == b or b == c give shoulders."""
    if x <= a:
        return 1.0 if a == b else 0.0
    if x >= c:
        return 1.0 if b == c else 0.0
    if x <= b:
        return (x - a) / (b - a) if b > a else 1.0
    return (c - x) / (c - b) if c > b else 1.0


def tri_vec(a, b, c):
    return np.array([tri(x, a, b, c) for x in OUT])


OUT_SETS = {
    "low": tri_vec(0, 0, 40),
    "medium": tri_vec(20, 45, 70),
    "high": tri_vec(50, 72, 90),
    "critical": tri_vec(75, 100, 100),
}

# (input, level) AND (input, level) -> output
RULES = [
    ((("alert", "high"), ("value", "high")), "critical"),
    ((("alert", "high"), ("conf", "high")), "critical"),
    ((("conf", "high"), ("value", "high")), "critical"),
    ((("alert", "medium"), ("conf", "high")), "high"),
    ((("conf", "high"), ("value", "medium")), "high"),
    ((("conf", "medium"), ("value", "high")), "high"),
    ((("alert", "high"), ("value", "low")), "medium"),
    ((("alert", "medium"), ("value", "medium")), "medium"),
    ((("conf", "medium"), ("alert", "low")), "medium"),
    ((("conf", "high"), ("value", "low")), "medium"),
    ((("conf", "low"), ("value", "low")), "low"),
    ((("alert", "low"), ("conf", "low")), "low"),
]


class FuzzyTriage:
    def __init__(self, alert_mid=0.45, conf_mid=0.35, watch=35.0, act=65.0):
        self.mid = {"alert": alert_mid, "value": 0.5, "conf": conf_mid}
        self.watch, self.act = watch, act

    def memberships(self, name, x):
        m = self.mid[name]
        return {"low": tri(x, 0, 0, m), "medium": tri(x, 0, m, 1), "high": tri(x, m, 1, 1)}

    def score(self, alert, value, conf):
        mu = {"alert": self.memberships("alert", alert),
              "value": self.memberships("value", value),
              "conf": self.memberships("conf", conf)}
        agg = np.zeros_like(OUT)
        for (a, b), out in RULES:
            strength = min(mu[a[0]][a[1]], mu[b[0]][b[1]])
            if strength > 0:
                agg = np.maximum(agg, np.minimum(strength, OUT_SETS[out]))
        if agg.sum() == 0:
            return 0.0
        return float((agg * OUT).sum() / agg.sum())

    def level(self, threat):
        if threat >= self.act:
            return "act"
        if threat >= self.watch:
            return "watch"
        return "ignore"
