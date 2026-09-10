"""Keyboard-first evidence file picker for the terminal."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Static

from raven.exceptions import ConfigurationError
from raven.models import EvidenceDocument
from raven.repositories.knowledge_base import SUPPORTED_EVIDENCE_EXTENSIONS
from raven.services.directories import create_directory
from raven.tui.widgets.dialogs import ConfirmDialog


def filter_evidence_paths(paths: Iterable[Path]) -> list[Path]:
    """Keep visible directories and supported, non-hidden evidence files."""
    visible: list[Path] = []
    for path in paths:
        if path.name.startswith("."):
            continue
        try:
            if path.is_dir() or path.suffix.lower() in SUPPORTED_EVIDENCE_EXTENSIONS:
                visible.append(path)
        except OSError:
            continue
    return visible


def filter_directory_paths(paths: Iterable[Path]) -> list[Path]:
    """Keep non-hidden directories available for folder selection."""
    visible: list[Path] = []
    for path in paths:
        if path.name.startswith("."):
            continue
        try:
            if path.is_dir():
                visible.append(path)
        except OSError:
            continue
    return visible


def compact_path(path: Path, limit: int = 34) -> str:
    """Keep location bars useful without wrapping long absolute paths."""
    try:
        label = str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        label = str(path)
    if len(label) <= limit:
        return label
    parts = path.parts
    tail = Path(*parts[-2:]) if len(parts) >= 2 else path
    return f"…/{tail}"


class ScrollStableDirectoryTree(DirectoryTree):
    """Keep the clicked folder in place while its children are loaded."""

    def on_click(self, event: events.Click) -> None:
        metadata = event.style.meta
        if metadata.get("toggle", False) and "line" in metadata:
            self.cursor_line = metadata["line"]


class EvidenceDirectoryTree(ScrollStableDirectoryTree):
    """Directory tree that exposes folders and supported evidence formats only."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return filter_evidence_paths(paths)


class FolderDirectoryTree(ScrollStableDirectoryTree):
    """Directory tree used when the folder itself is the selected value."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return filter_directory_paths(paths)


class EvidenceFilePicker(ModalScreen[Path | None]):
    """Select one supported document from disk without typing its path."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("ctrl+enter", "confirm", "Add selected"),
    ]

    def __init__(self, start: Path | None = None) -> None:
        super().__init__()
        self.start = (start or Path.home()).resolve()
        self.selected: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="file-picker-dialog", classes="path-picker-dialog"):
            with Horizontal(classes="path-picker-header"):
                yield Static("SELECT EVIDENCE DOCUMENT", classes="path-picker-title")
                yield Static("Enter select · ^Enter add", classes="path-picker-help")
            with Horizontal(classes="path-picker-locations"):
                yield Button("Home", id="picker-home")
                yield Button("Project", id="picker-workspace")
                yield Button("Up", id="picker-up")
                yield Static(
                    compact_path(self.start),
                    id="file-picker-root",
                    classes="path-picker-root",
                    markup=False,
                )
            yield EvidenceDirectoryTree(self.start, id="evidence-directory-tree")
            with Horizontal(classes="path-picker-selection"):
                yield Static("SELECTED", classes="path-picker-selection-label")
                yield Static(
                    "No file selected",
                    id="selected-evidence-file",
                    classes="path-picker-selection-value",
                    markup=False,
                )
                yield Static("—", id="selected-evidence-format")
            with Horizontal(classes="path-picker-actions"):
                yield Static(
                    "PDF · DOC/DOCX · MD/MARKDOWN",
                    id="file-picker-formats",
                    classes="path-picker-formats",
                )
                yield Button(
                    "Add file", id="confirm-evidence-file", variant="primary", disabled=True
                )
                yield Button("Cancel", id="cancel-evidence-file")

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.height)
        root = self.query_one("#file-picker-root", Static)
        root.tooltip = str(self.start)
        self.query_one("#evidence-directory-tree", EvidenceDirectoryTree).focus()

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.height)

    def _set_responsive_layout(self, height: int) -> None:
        self.set_class(height <= 26, "compact-path-picker")

    def action_confirm(self) -> None:
        if self.selected is not None:
            self.dismiss(self.selected)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._select_file(event.path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-evidence-file":
            self.action_confirm()
        elif event.button.id == "cancel-evidence-file":
            self.dismiss(None)
        elif event.button.id == "picker-home":
            self._set_root(Path.home())
        elif event.button.id == "picker-workspace":
            self._set_root(Path.cwd())
        elif event.button.id == "picker-up":
            tree = self.query_one("#evidence-directory-tree", EvidenceDirectoryTree)
            self._set_root(tree.path.parent)

    def _select_file(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_EVIDENCE_EXTENSIONS:
            return
        self.selected = path.resolve()
        selected = self.query_one("#selected-evidence-file", Static)
        selected.update(self.selected.name)
        selected.tooltip = str(self.selected)
        self.query_one("#selected-evidence-format", Static).update(
            self.selected.suffix.removeprefix(".").upper()
        )
        self.query_one("#confirm-evidence-file", Button).disabled = False

    def _set_root(self, path: Path) -> None:
        resolved = path.resolve()
        self.selected = None
        self.query_one("#evidence-directory-tree", EvidenceDirectoryTree).path = resolved
        root = self.query_one("#file-picker-root", Static)
        root.update(compact_path(resolved))
        root.tooltip = str(resolved)
        selected = self.query_one("#selected-evidence-file", Static)
        selected.update("No file selected")
        selected.tooltip = None
        self.query_one("#selected-evidence-format", Static).update("—")
        self.query_one("#confirm-evidence-file", Button).disabled = True


class EvidenceStorageDirectoryPicker(ModalScreen[Path | None]):
    """Select the root under which Raven creates investigation directories."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("n", "add_folder", "Add folder"),
        Binding("ctrl+enter", "confirm", "Use selected"),
    ]

    def __init__(
        self,
        start: Path,
        *,
        title: str = "SELECT EVIDENCE STORAGE",
        description: str = "One subfolder will be created per investigation",
        confirmation: str = "Use folder",
    ) -> None:
        super().__init__()
        resolved = start.expanduser().resolve()
        self.start = resolved if resolved.is_dir() else Path.home().resolve()
        self.selected = self.start
        self.title = title
        self.description = description
        self.confirmation = confirmation

    def compose(self) -> ComposeResult:
        with Vertical(id="storage-picker-dialog", classes="path-picker-dialog"):
            with Horizontal(classes="path-picker-header"):
                yield Static(self.title, classes="path-picker-title")
                yield Static("Enter choose · ^Enter use", classes="path-picker-help")
            with Horizontal(classes="path-picker-locations"):
                yield Button("Home", id="storage-picker-home")
                yield Button("Project", id="storage-picker-workspace")
                yield Button("Up", id="storage-picker-up")
                yield Button("Add folder", id="storage-picker-add-folder")
                yield Static(
                    compact_path(self.start),
                    id="storage-picker-root",
                    classes="path-picker-root",
                    markup=False,
                )
            yield FolderDirectoryTree(self.start, id="storage-directory-tree")
            with Horizontal(classes="path-picker-selection"):
                yield Static("FOLDER", classes="path-picker-selection-label")
                yield Static(
                    compact_path(self.selected),
                    id="selected-storage-directory",
                    classes="path-picker-selection-value",
                    markup=False,
                )
            with Horizontal(classes="path-picker-actions storage-picker-actions"):
                yield Static(
                    self.description,
                    classes="path-picker-formats",
                )
                yield Button(
                    self.confirmation,
                    id="confirm-storage-directory",
                    variant="primary",
                )
                yield Button("Cancel", id="cancel-storage-directory")

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.height)
        self._update_path_widgets(self.selected)
        self.query_one("#storage-directory-tree", FolderDirectoryTree).focus()

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.height)

    def _set_responsive_layout(self, height: int) -> None:
        self.set_class(height <= 26, "compact-path-picker")

    def action_confirm(self) -> None:
        self.dismiss(self.selected)

    def action_add_folder(self) -> None:
        self.app.push_screen(
            NewDirectoryDialog(self.selected),
            callback=self._folder_created,
        )

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.selected = event.path.resolve()
        self._update_path_widgets(self.selected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-storage-directory":
            self.action_confirm()
        elif event.button.id == "cancel-storage-directory":
            self.dismiss(None)
        elif event.button.id == "storage-picker-home":
            self._set_root(Path.home())
        elif event.button.id == "storage-picker-workspace":
            self._set_root(Path.cwd())
        elif event.button.id == "storage-picker-up":
            tree = self.query_one("#storage-directory-tree", FolderDirectoryTree)
            self._set_root(tree.path.parent)
        elif event.button.id == "storage-picker-add-folder":
            self.action_add_folder()

    def _folder_created(self, path: Path | None) -> None:
        if path is not None:
            self._set_root(path)

    def _set_root(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        self.selected = resolved
        self.query_one("#storage-directory-tree", FolderDirectoryTree).path = resolved
        self._update_path_widgets(resolved)

    def _update_path_widgets(self, path: Path) -> None:
        root = self.query_one("#storage-picker-root", Static)
        root.update(compact_path(path))
        root.tooltip = str(path)
        selected = self.query_one("#selected-storage-directory", Static)
        selected.update(compact_path(path, limit=48))
        selected.tooltip = str(path)


class MarkdownExportPicker(ModalScreen[Path | None]):
    """Choose an existing folder and safe Markdown filename for chat export."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("n", "add_folder", "Add folder"),
        Binding("ctrl+enter", "confirm", "Save Markdown"),
    ]

    def __init__(self, start: Path, suggested_filename: str) -> None:
        super().__init__()
        resolved = start.expanduser().resolve()
        self.start = resolved if resolved.is_dir() else Path.home().resolve()
        self.selected = self.start
        self.suggested_filename = suggested_filename

    def compose(self) -> ComposeResult:
        with Vertical(id="markdown-export-dialog", classes="path-picker-dialog"):
            with Horizontal(classes="path-picker-header"):
                yield Static("SAVE LAST RESPONSE", classes="path-picker-title")
                yield Static("Enter choose · ^Enter save", classes="path-picker-help")
            with Horizontal(classes="path-picker-locations"):
                yield Button("Home", id="export-picker-home")
                yield Button("Project", id="export-picker-workspace")
                yield Button("Up", id="export-picker-up")
                yield Button("Add folder", id="export-picker-add-folder")
                yield Static(
                    compact_path(self.start),
                    id="markdown-export-root",
                    classes="path-picker-root",
                    markup=False,
                )
            yield FolderDirectoryTree(self.start, id="markdown-export-directory-tree")
            with Horizontal(classes="path-picker-selection"):
                yield Static("FOLDER", classes="path-picker-selection-label")
                yield Static(
                    compact_path(self.selected, limit=48),
                    id="selected-markdown-export-directory",
                    classes="path-picker-selection-value",
                    markup=False,
                )
            with Horizontal(classes="markdown-export-name-row"):
                yield Static("FILE NAME", classes="markdown-export-name-label")
                yield Input(value=self.suggested_filename, id="markdown-export-name")
            yield Static("", id="markdown-export-error", markup=False)
            with Horizontal(classes="path-picker-actions"):
                yield Static(
                    "A new .md file will be created; existing files are never overwritten.",
                    classes="path-picker-formats",
                )
                yield Button(
                    "Save Markdown",
                    id="confirm-markdown-export",
                    variant="primary",
                )
                yield Button("Cancel", id="cancel-markdown-export")

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.height)
        self._update_path_widgets(self.selected)
        self.query_one("#markdown-export-name", Input).focus()

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.height)

    def _set_responsive_layout(self, height: int) -> None:
        self.set_class(height <= 26, "compact-path-picker")

    def action_confirm(self) -> None:
        destination = self._destination()
        if destination is not None:
            self.dismiss(destination)

    def action_add_folder(self) -> None:
        self.app.push_screen(NewDirectoryDialog(self.selected), callback=self._folder_created)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "markdown-export-name":
            self.action_confirm()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.selected = event.path.resolve()
        self._update_path_widgets(self.selected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-markdown-export":
            self.action_confirm()
        elif event.button.id == "cancel-markdown-export":
            self.dismiss(None)
        elif event.button.id == "export-picker-home":
            self._set_root(Path.home())
        elif event.button.id == "export-picker-workspace":
            self._set_root(Path.cwd())
        elif event.button.id == "export-picker-up":
            tree = self.query_one("#markdown-export-directory-tree", FolderDirectoryTree)
            self._set_root(tree.path.parent)
        elif event.button.id == "export-picker-add-folder":
            self.action_add_folder()

    def _folder_created(self, path: Path | None) -> None:
        if path is not None:
            self._set_root(path)

    def _set_root(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        self.selected = resolved
        self.query_one("#markdown-export-directory-tree", FolderDirectoryTree).path = resolved
        self._update_path_widgets(resolved)

    def _update_path_widgets(self, path: Path) -> None:
        root = self.query_one("#markdown-export-root", Static)
        root.update(compact_path(path))
        root.tooltip = str(path)
        selected = self.query_one("#selected-markdown-export-directory", Static)
        selected.update(compact_path(path, limit=48))
        selected.tooltip = str(path)
        self.query_one("#markdown-export-error", Static).update("")

    def _destination(self) -> Path | None:
        raw_name = self.query_one("#markdown-export-name", Input).value.strip()
        error = self.query_one("#markdown-export-error", Static)
        if not raw_name or raw_name.startswith(".") or "/" in raw_name or "\\" in raw_name:
            error.update("Enter a visible filename without folder separators")
            return None
        filename = Path(raw_name)
        if filename.suffix.lower() != ".md":
            filename = filename.with_suffix(".md")
            self.query_one("#markdown-export-name", Input).value = filename.name
        destination = self.selected / filename.name
        if destination.exists():
            error.update("That file already exists; choose another filename")
            return None
        return destination


class NewDirectoryDialog(ModalScreen[Path | None]):
    """Create a direct child of the folder selected in the storage picker."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, parent: Path) -> None:
        super().__init__()
        self.parent_directory = parent

    def compose(self) -> ComposeResult:
        with Vertical(id="new-directory-dialog"):
            yield Static("CREATE FOLDER", id="new-directory-title")
            yield Static(
                f"Inside {compact_path(self.parent_directory, limit=44)}",
                id="new-directory-parent",
                markup=False,
            )
            yield Input(placeholder="Folder name", id="new-directory-name")
            yield Static("", id="new-directory-error", markup=False)
            with Horizontal(id="new-directory-actions"):
                yield Button("Create", id="confirm-new-directory", variant="primary")
                yield Button("Cancel", id="cancel-new-directory")

    def on_mount(self) -> None:
        self.query_one("#new-directory-name", Input).focus()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-new-directory":
            self._create()
        elif event.button.id == "cancel-new-directory":
            self.dismiss(None)

    def _create(self) -> None:
        name = self.query_one("#new-directory-name", Input).value
        try:
            destination = create_directory(self.parent_directory, name)
        except ConfigurationError as exc:
            self.query_one("#new-directory-error", Static).update(str(exc))
            return
        self.dismiss(destination)


class ConfirmEvidenceDelete(ConfirmDialog):
    """Name the destructive target and require an explicit confirmation."""

    def __init__(self, document: EvidenceDocument) -> None:
        self.document = document
        super().__init__(
            dialog_id="delete-evidence-dialog",
            title="Delete evidence document?",
            title_id="delete-evidence-title",
            subject=document.original_name,
            subject_id="delete-evidence-name",
            warning=(
                "The Raven copy and its metadata will be removed. The source file is unchanged."
            ),
            warning_id="delete-evidence-warning",
            actions_id="delete-evidence-actions",
            confirm_label="Delete",
            confirm_id="confirm-delete-evidence",
            cancel_id="cancel-delete-evidence",
            centered_actions=False,
        )
