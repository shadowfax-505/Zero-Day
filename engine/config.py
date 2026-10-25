"""Tunable game constants.

Every number here is a balancing knob (outline section 03). The defaults were
picked by play-testing and batch runs; change them and re-run
experiments/run_batch.py to see the effect on the win rate.
"""

MAX_ROUNDS = 40

# Zones
DMZ, OFFICE, DATACENTRE = 0, 1, 2
ZONE_NAMES = ["DMZ", "OFFICE", "DATA CENTRE"]
ZONE_SIZES = [(8, 10), (14, 18), (8, 10)]   # min/max nodes per zone

# Red actions and their noise levels
NOISE = {
    "scout": 0.20,
    "advance": 0.20,
    "capture": 0.45,
    "unlock": 0.80,
    "claim": 0.80,
}

# Blue actions and their action-point costs
BLUE_AP = 3
COST = {
    "monitor": 1,
    "patch": 1,
    "decoy": 2,
    "isolate": 2,
    "restore": 2,
}

MONITOR_BOOST = 1.6
FALSE_ALARM = 0.02
ISOLATE_ROUNDS = 2
MAX_ISOLATED = 1           # isolations Blue can keep running at once
ISOLATE_COOLDOWN = 4        # rounds a node stays immune after an isolation ends
MAX_DECOYS = 3
DECOY_APPARENT_WEAKNESS = 0.85
UNLOCK_SUCCESS = 0.9        # unlock succeeds with weakness(target) * this
CLAIM_BASE = 0.40           # claim succeeds with CLAIM_BASE + CLAIM_SCALE * weakness(db)
CLAIM_SCALE = 0.60
GATEWAY_GRACE = 15         # the gateway cannot be sealed in the first rounds
SEAL_COST = 3              # restoring (sealing) the gateway takes the whole turn
PATCH_FLOOR = 0.15           # patching never pushes weakness below this


def action_cost(kind, target, gateway):
    if kind == "restore" and target == gateway:
        return SEAL_COST
    return COST.get(kind, 99)
PATCH_FACTOR = 0.5         # patch multiplies weakness by this
RETRY_BONUS = 0.15         # each failed capture on a node adds this to the next try
ISOLATE_RECHARGE = 2       # rounds after an isolation ends before Blue can isolate again
