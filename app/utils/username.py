import hashlib
import random
import re

_ADJECTIVES = [
    "swift",
    "bright",
    "calm",
    "bold",
    "keen",
    "warm",
    "clear",
    "glad",
    "neat",
    "fine",
    "kind",
    "true",
    "wise",
    "fair",
    "safe",
    "pure",
    "cool",
    "soft",
    "sharp",
    "quick",
    "fresh",
    "light",
    "smart",
    "ready",
    "easy",
    "quiet",
    "brave",
    "noble",
    "loyal",
    "merry",
    "jolly",
    "sunny",
    "breezy",
    "cozy",
    "snappy",
    "zippy",
    "rosy",
    "handy",
    "nifty",
    "plucky",
]

_NOUNS = [
    "mover",
    "packer",
    "shifter",
    "helper",
    "scout",
    "guide",
    "planner",
    "sorter",
    "hauler",
    "finder",
    "keeper",
    "holder",
    "builder",
    "maker",
    "walker",
    "seeker",
    "thinker",
    "dreamer",
    "mixer",
    "handler",
    "watcher",
    "ranger",
    "rider",
    "dancer",
    "trader",
    "baker",
    "coder",
    "driver",
    "crafter",
    "shaper",
    "picker",
    "stacker",
    "loader",
    "settler",
    "dweller",
    "porter",
    "hunter",
    "roamer",
    "glider",
    "drifter",
]

USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9]{3,19}$")


def generate_username() -> str:
    adj = random.choice(_ADJECTIVES).capitalize()
    noun = random.choice(_NOUNS).capitalize()
    num = random.randint(100, 999)
    return f"{adj}{noun}{num}"


def make_conversation_id(uid_a: str, uid_b: str) -> str:
    joined = "".join(sorted([uid_a, uid_b]))
    return hashlib.sha1(joined.encode()).hexdigest()[:20]


def is_valid_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username))
