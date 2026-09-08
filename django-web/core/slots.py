SLOT_COUNT = 3

SLOT_CHOICES = [
    (1, "早"),
    (2, "中"),
    (3, "晚"),
]

SLOT_LABELS = dict(SLOT_CHOICES)
SLOT_PERIODS = {1: "morning", 2: "noon", 3: "evening"}
PERIOD_SLOTS = {value: key for key, value in SLOT_PERIODS.items()}


def is_valid_slot(slot) -> bool:
    try:
        value = int(slot)
    except (TypeError, ValueError):
        return False
    return 1 <= value <= SLOT_COUNT


def slot_label(slot):
    """User-facing compartment label: only 早、中、晚 are valid."""
    try:
        value = int(slot)
    except (TypeError, ValueError):
        return "未指定"
    return SLOT_LABELS.get(value, "未指定")


def period_for_slot(slot):
    """Map physical compartment 1/2/3 to schedule period morning/noon/evening."""
    try:
        value = int(slot)
    except (TypeError, ValueError):
        return "morning"
    return SLOT_PERIODS.get(value, "morning")


def slot_for_period(period):
    return PERIOD_SLOTS.get(str(period or "").strip().lower())


def slot_payload():
    return [
        {"slot": value, "label": label, "period": SLOT_PERIODS[value]}
        for value, label in SLOT_CHOICES
    ]
