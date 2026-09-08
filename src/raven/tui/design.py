"""Fixed semantic colors: actions, healthy services, warnings and failures."""

from textual.theme import Theme


def raven_theme() -> Theme:
    accent = "#8db9ff"
    return Theme(
        name="raven",
        primary=accent,
        secondary="#b4a0ed",
        accent=accent,
        background="#0c1018",
        surface="#121925",
        panel="#1a2535",
        foreground="#e2e9f3",
        success="#54d38a",
        warning="#f0bd4f",
        error="#ff747e",
        dark=True,
        variables={
            "text-muted": "#98a9bf",
            "primary-muted": "#273347",
            "footer-background": "#121925",
            "footer-key-foreground": accent,
            "button-focus-text-style": "bold",
        },
    )
