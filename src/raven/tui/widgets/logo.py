"""Responsive ASCII-art branding for the home screen."""

from __future__ import annotations

from textual.events import Resize
from textual.widgets import Static

WIDE_LOGO = r"""
      ___           ___           ___           ___           ___
     /\  \         /\  \         /\__\         /\  \         /\__\
    /::\  \       /::\  \       /:/  /        /::\  \       /::|  |
   /:/\:\  \     /:/\:\  \     /:/  /        /:/\:\  \     /:|:|  |
  /::\~\:\  \   /::\~\:\  \   /:/__/  ___   /::\~\:\  \   /:/|:|  |__
 /:/\:\ \:\__\ /:/\:\ \:\__\  |:|  | /\__\ /:/\:\ \:\__\ /:/ |:| /\__\
 \/_|::\/:/  / \/__\:\/:/  /  |:|  |/:/  / \:\~\:\ \/__/ \/__|:|/:/  /
    |:|::/  /       \::/  /   |:|__/:/  /   \:\ \:\__\       |:/:/  /
    |:|\/__/        /:/  /     \::::/__/     \:\ \/__/       |::/  /
    |:|  |         /:/  /       ~~~~          \:\__\         /:/  /
     \|__|         \/__/                       \/__/         \/__/
""".strip("\n")

COMPACT_LOGO = r"""
 ____    ___  _   _  _____  _   _
|  _ \  / _ \| | | ||  ___|| \ | |
| |_) || |_| | | | || |_   |  \| |
|  _ < |  _  | |_| ||  _|  | |\  |
|_| \_\|_| |_|\___/ |_|    |_| \_|
""".strip("\n")


class RavenLogo(Static):
    """Render the detailed logo when the terminal has enough width."""

    WIDE_MINIMUM = 76

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(COMPACT_LOGO, *args, **kwargs)

    def on_mount(self) -> None:
        self._render_for_width(self.size.width)

    def on_resize(self, event: Resize) -> None:
        self._render_for_width(event.size.width)

    def _render_for_width(self, width: int) -> None:
        self.update(WIDE_LOGO if width >= self.WIDE_MINIMUM else COMPACT_LOGO)
