"""Away Mode helper — escalates snoop-relevant events to critical when enabled."""

# Categories that signal "someone is touching this computer" — escalated to
# critical when the user has flipped Away Mode on.
SNOOP_CATEGORIES = {"login", "session", "usb", "rdp", "filesystem", "network", "power"}


def maybe_escalate(config, category: str, severity: str) -> tuple[str, bool]:
    """If Away Mode is on and `category` is snoop-relevant, force severity=critical.

    Returns (severity, escalated_bool).
    """
    if (category in SNOOP_CATEGORIES
            and config
            and config.get("general", "away_mode")):
        return "critical", True
    return severity, False
