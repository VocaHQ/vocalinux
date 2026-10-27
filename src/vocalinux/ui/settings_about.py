"""About page content and trusted family links for Settings."""

import logging
import os
from typing import Any, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from ..utils.update_checker import (
    DEFAULT_CHECK_AUTOMATICALLY,
    build_channel,
    is_trusted_release_url,
)
from ..version import __copyright__, __url__, __version__

logger = logging.getLogger(__name__)

VOCALINUX_SITE_URL = "https://vocalinux.com"
VOCAHQ_SITE_URL = "https://vocahq.com"
VOCAMAC_SITE_URL = "https://vocamac.com"
VOCAWIN_SITE_URL = "https://vocawin.com"
VOCAPHONE_SITE_URL = "https://vocaphone.vocahq.com"
VOCAGATEWAY_SITE_URL = "https://vocagateway.vocahq.com"
GITHUB_REPO_URL = __url__
GITHUB_ISSUES_URL = "https://github.com/VocaHQ/vocalinux/issues"
VOCAHQ_DISCORD_URL = "https://discord.gg/t6muquAJbm"
VOCAHQ_X_URL = "https://x.com/vocahq"
VOCAHQ_MAILTO_URL = "mailto:hello@vocahq.com"

# About page links that are not GitHub release URLs.
_ABOUT_OPEN_URLS = frozenset(
    {
        VOCALINUX_SITE_URL,
        VOCAHQ_SITE_URL,
        VOCAMAC_SITE_URL,
        VOCAWIN_SITE_URL,
        VOCAPHONE_SITE_URL,
        VOCAGATEWAY_SITE_URL,
        GITHUB_REPO_URL,
        GITHUB_ISSUES_URL,
        VOCAHQ_DISCORD_URL,
        VOCAHQ_X_URL,
        VOCAHQ_MAILTO_URL,
    }
)

# Official Talk-to-us marks from VocaHQ/.github brand/vocahq/social (commit 61c8eee).
# Do not redraw. fill is currentColor; paint to match the dialog foreground so
# the marks stay visible on both light and dark surfaces.
_ABOUT_INK = "#14231C"
_ABOUT_INK_ON_DARK = "#E6E1D8"
_ABOUT_ICON_TEXT_PX = 18
_FAMILY_ICON_PX = 22


def _color_luminance(color: Any) -> float:
    """Relative luminance of a Gdk.RGBA (0 = black, 1 = white)."""
    return float(0.2126 * color.red + 0.7152 * color.green + 0.0722 * color.blue)


def _rgba_to_hex(color: Any) -> str:
    """Format a Gdk.RGBA as #rrggbb."""
    r = max(0, min(255, int(round(color.red * 255))))
    g = max(0, min(255, int(round(color.green * 255))))
    b = max(0, min(255, int(round(color.blue * 255))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _about_surface_is_dark() -> bool:
    """Return True when GTK is using a dark theme."""
    settings = Gtk.Settings.get_default()
    if settings is not None:
        try:
            if bool(settings.get_property("gtk-application-prefer-dark-theme")):
                return True
        except Exception:
            pass
        try:
            theme = str(settings.get_property("gtk-theme-name") or "").lower()
            if "dark" in theme:
                return True
        except Exception:
            pass
    try:
        from ..utils.gtk_color_scheme import read_os_color_scheme

        if read_os_color_scheme() == "prefer-dark":
            return True
    except Exception:
        pass
    return False


def _about_ink_hex(
    widget: Optional[Gtk.Widget] = None,
    dark: Optional[bool] = None,
) -> str:
    """Ink for currentColor marks: theme fg when known, else light/dark defaults."""
    if dark is None:
        dark = _about_surface_is_dark()
    if widget is not None:
        ctx = widget.get_style_context()
        for name in ("theme_fg_color", "theme_text_color", "fg_color"):
            try:
                found, color = ctx.lookup_color(name)
            except Exception:
                continue
            if not found:
                continue
            lum = _color_luminance(color)
            if dark and lum >= 0.45:
                return _rgba_to_hex(color)
            if not dark and lum <= 0.40:
                return _ABOUT_INK
    return _ABOUT_INK_ON_DARK if dark else _ABOUT_INK


# Official platform marks from VocaHQ/.github brand/promo/cards/platform
# (currentColor copies live in web/public/brand/platforms). Home is a simple
# house so HQ does not reuse a product lockup.
_VOCAHQ_FAMILY_LINKS = (
    (
        VOCAHQ_SITE_URL,
        "VocaHQ",
        "Family site",
        ("platform-home",),
        "Open vocahq.com",
    ),
    (
        VOCALINUX_SITE_URL,
        "Vocalinux",
        "Linux, available now",
        ("platform-linux",),
        "Open vocalinux.com",
    ),
    (
        VOCAMAC_SITE_URL,
        "VocaMac",
        "macOS, available now",
        ("platform-apple",),
        "Open vocamac.com",
    ),
    (
        VOCAWIN_SITE_URL,
        "VocaWin",
        "Windows, unsigned beta",
        ("platform-windows",),
        "Open vocawin.com",
    ),
    (
        VOCAPHONE_SITE_URL,
        "VocaPhone",
        "Android beta / iOS TestFlight",
        ("platform-android", "platform-apple"),
        "Open vocaphone.vocahq.com",
    ),
    (
        VOCAGATEWAY_SITE_URL,
        "VocaGateway",
        "Self-hosted, headless",
        ("platform-server",),
        "Open vocagateway.vocahq.com",
    ),
)


def _can_open_url(url: str) -> bool:
    """Return True for GitHub project URLs or the About page allowlist."""
    return bool(url) and (url in _ABOUT_OPEN_URLS or is_trusted_release_url(url))


class AboutSectionMixin(Gtk.Dialog):
    """Build About content on the Settings dialog."""

    def _about_mark_image(
        self: Any,
        icon_name: str,
        pixel_size: int = _ABOUT_ICON_TEXT_PX,
        dark: Optional[bool] = None,
    ) -> Optional[Gtk.Image]:
        """Load a currentColor SVG and paint it to match the dialog foreground."""
        from gi.repository import GdkPixbuf

        from ..utils.resource_manager import ResourceManager

        path = ResourceManager().get_icon_path(icon_name)
        if not os.path.exists(path):
            return None
        try:
            ink = _about_ink_hex(self, dark)
            with open(path, encoding="utf-8") as handle:
                svg = handle.read().replace("currentColor", ink)
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.set_size(pixel_size, pixel_size)
            loader.write(svg.encode("utf-8"))
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf is None:
                return None
            image = Gtk.Image.new_from_pixbuf(pixbuf)
            image.set_pixel_size(pixel_size)
            return image
        except Exception as exc:
            logger.warning("Failed to load About mark %s: %s", icon_name, exc)
            return None

    def _about_open_button(
        self: Any,
        url: str,
        tooltip: str,
        label: str = "Open",
        icon_name: Optional[str] = None,
        width: int = 100,
        dark: Optional[bool] = None,
    ) -> Gtk.Button:
        """Button that opens a trusted About URL.

        Unique labels (Website, Source code, Report a bug or idea) are the
        accessible name. Shared "Open" labels use the tooltip instead.
        """
        from .settings_dialog import _set_accessible_name

        button = Gtk.Button(label=label)
        button.set_size_request(width, -1)
        button.set_tooltip_text(tooltip)
        if label == "Open":
            _set_accessible_name(button, tooltip)
        if icon_name:
            image = self._about_mark_image(icon_name, dark=dark)
            if image is not None:
                image.set_margin_end(8)
                button.set_image(image)
                button.set_always_show_image(True)
                button.get_style_context().add_class("about-mark-button")
        button.connect("clicked", lambda *_args, dest=url: self._open_web_url(dest))
        return button

    def _family_tile(
        self: Any,
        url: str,
        title: str,
        subtitle: str,
        icon_names: tuple[str, ...],
        tooltip: str,
        dark: Optional[bool] = None,
    ) -> Gtk.Button:
        """Compact icon + name tile that opens a family site."""
        from .settings_dialog import _set_accessible_name

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        marks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        marks.set_valign(Gtk.Align.CENTER)
        for icon_name in icon_names:
            icon = self._about_mark_image(
                icon_name,
                pixel_size=_FAMILY_ICON_PX,
                dark=dark,
            )
            if icon is not None:
                marks.pack_start(icon, False, False, 0)
        inner.pack_start(marks, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name_label = Gtk.Label(label=title, xalign=0)
        name_label.get_style_context().add_class("family-tile-title")
        status_label = Gtk.Label(label=subtitle, xalign=0)
        status_label.get_style_context().add_class("family-tile-subtitle")
        status_label.set_line_wrap(True)
        text.pack_start(name_label, False, False, 0)
        text.pack_start(status_label, False, False, 0)
        inner.pack_start(text, True, True, 0)

        button = Gtk.Button()
        button.add(inner)
        button.get_style_context().add_class("family-tile")
        button.set_tooltip_text(tooltip)
        button.set_hexpand(True)
        button.set_halign(Gtk.Align.FILL)
        _set_accessible_name(button, tooltip)
        button.connect("clicked", lambda *_args, dest=url: self._open_web_url(dest))
        return button

    def _build_about_section(self: Any) -> None:
        """Build the About page using the same PreferenceRow cards as other pages."""
        about_tab = getattr(self, "about_tab")
        config_manager = getattr(self, "config_manager")
        on_check_updates_clicked = getattr(self, "_on_check_updates_clicked")
        on_update_checks_toggled = getattr(self, "_on_update_checks_toggled")
        on_update_channel_changed = getattr(self, "_on_update_channel_changed")
        on_open_release_clicked = getattr(self, "_on_open_release_clicked")

        from gi.repository import GdkPixbuf

        from ..utils.resource_manager import ResourceManager
        from .settings_dialog import (
            _CONTROL_WIDTH,
            PreferenceRow,
            PreferencesGroup,
            _combo_chrome,
            _combo_with_suffix,
            _set_accessible_name,
            _style_action_button,
        )

        dark = _about_surface_is_dark()
        about_icon = None
        logo_path = ResourceManager().get_icon_path("vocalinux")
        if os.path.exists(logo_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(logo_path)
                scaled = pixbuf.scale_simple(48, 48, GdkPixbuf.InterpType.BILINEAR)
                about_icon = Gtk.Image.new_from_pixbuf(scaled)
                about_icon.set_pixel_size(48)
            except Exception as exc:
                logger.warning("Failed to load About icon: %s", exc)

        app_group = PreferencesGroup(
            title="Vocalinux",
            description=(
                "Available now on Linux (X11 and Wayland). After a model is downloaded, "
                "speech is processed on this PC."
            ),
            keywords=("about", "version", "app"),
            header_icon=about_icon,
        )

        self.about_version_label = Gtk.Label(label=__version__)
        self.about_version_label.set_selectable(True)
        self.about_version_label.get_style_context().add_class("preference-row-subtitle")
        version_row = PreferenceRow(
            title="Version",
            subtitle="Currently installed Vocalinux build",
            widget=self.about_version_label,
            keywords=("version", "build"),
        )
        app_group.add_row(version_row)

        link_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        link_box.pack_start(
            self._about_open_button(
                VOCALINUX_SITE_URL,
                "Open vocalinux.com website",
                label="Website",
                width=110,
                dark=dark,
            ),
            False,
            False,
            0,
        )
        link_box.pack_start(
            self._about_open_button(
                GITHUB_REPO_URL,
                "Open the Vocalinux GitHub repository",
                label="Source code",
                width=120,
                dark=dark,
            ),
            False,
            False,
            0,
        )
        links_row = PreferenceRow(
            title="Open source",
            subtitle="Product site at vocalinux.com, source on GitHub.",
            widget=link_box,
            keywords=("website", "vocalinux.com", "github", "source", "repo", "code", "agpl"),
        )
        app_group.add_row(links_row)

        license_row = PreferenceRow(
            title="License",
            subtitle=f"GNU AGPL v3 · {__copyright__}",
            keywords=("license", "agpl", "gpl", "copyright"),
        )
        app_group.add_row(license_row)
        about_tab.pack_start(app_group, False, False, 0)

        talk_group = PreferencesGroup(
            title="Talk to us",
            description=(
                "Bugs, feedback, and feature ideas open a GitHub issue. You pick the "
                "template on the next screen."
            ),
            keywords=("github", "discord", "contact", "bug", "feedback", "email"),
        )
        report_btn = self._about_open_button(
            GITHUB_ISSUES_URL,
            "Open GitHub issues for a bug or idea",
            label="Report a bug or idea",
            icon_name="github",
            width=200,
            dark=dark,
        )
        talk_group.add_row(
            PreferenceRow(
                title="GitHub issues",
                subtitle="https://github.com/VocaHQ/vocalinux/issues",
                widget=report_btn,
                keywords=("github", "issue", "bug", "idea"),
            )
        )
        contact_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for url, label, tooltip, icon_name, width in (
            (VOCAHQ_DISCORD_URL, "Join Discord", "Open the VocaHQ Discord", "discord", 140),
            (VOCAHQ_X_URL, "Follow on X", "Open X @vocahq", "x", 130),
            (VOCAHQ_MAILTO_URL, "Email us", "Email hello@vocahq.com", "mail", 120),
        ):
            contact_box.pack_start(
                self._about_open_button(
                    url,
                    tooltip,
                    label=label,
                    icon_name=icon_name,
                    width=width,
                    dark=dark,
                ),
                False,
                False,
                0,
            )
        talk_group.add_row(
            PreferenceRow(
                title="Community",
                subtitle="Discord, X, and email",
                widget=contact_box,
                keywords=("discord", "x", "twitter", "email", "mail"),
            )
        )
        about_tab.pack_start(talk_group, False, False, 0)

        build = build_channel()
        updates_group = PreferencesGroup(
            title="Updates",
            description=(
                f"This is a {build} build, so background checks only look for "
                f"{build} releases. Pick a channel below to look one up by hand."
            ),
            keywords=("update", "version", "release", "upgrade", "appimage", "nightly", "channel"),
        )

        self.update_checks_switch = Gtk.Switch()
        self.update_checks_switch.set_active(
            config_manager.get_bool("updates", "check_automatically", DEFAULT_CHECK_AUTOMATICALLY)
        )
        self.update_checks_switch.connect("state-set", on_update_checks_toggled)
        updates_group.add_row(
            PreferenceRow(
                title="Check for updates automatically",
                subtitle=(
                    "Look for new releases in the background and show a tray entry and a "
                    "notification when one is out"
                ),
                widget=self.update_checks_switch,
                keywords=("update", "notification", "automatic", "check", "disable"),
            )
        )

        self.update_channel_combo = Gtk.ComboBoxText()
        self.update_channel_combo.append("stable", "Stable")
        self.update_channel_combo.append("nightly", "Nightly")
        _combo_chrome(
            self.update_channel_combo,
            tooltip=(
                "Stable uses the latest numbered release. Nightly uses the newest "
                "nightly-YYYY-MM-DD build."
            ),
        )
        self.update_channel_combo.set_active_id(build_channel())

        self.check_updates_btn = Gtk.Button(label="Check")
        self.check_updates_btn.get_style_context().add_class("suffix-button")
        _style_action_button(self.check_updates_btn, width=80)
        self.check_updates_btn.set_tooltip_text(
            "Look up the latest release for this channel on GitHub"
        )
        self.check_updates_btn.connect("clicked", on_check_updates_clicked)

        self.update_status_row = PreferenceRow(
            title="Channel",
            subtitle="Not checked yet",
            widget=_combo_with_suffix(
                self.update_channel_combo,
                self.check_updates_btn,
                combo_width=_CONTROL_WIDTH - 88,
            ),
            keywords=("channel", "stable", "nightly", "beta", "status", "check"),
        )
        updates_group.add_row(self.update_status_row)
        about_tab.pack_start(updates_group, False, False, 0)

        self.update_channel_combo.connect("changed", on_update_channel_changed)

        self.release_notes_group = PreferencesGroup(
            title="What's New",
            keywords=("changelog", "what's new", "release notes", "latest", "download"),
        )
        self.open_release_btn = Gtk.Button(label="Open")
        _style_action_button(self.open_release_btn)
        self.open_release_btn.set_sensitive(False)
        self.open_release_btn.set_tooltip_text(
            "Open the release page in your browser for download links and install steps"
        )
        _set_accessible_name(
            self.open_release_btn,
            "Open the latest release page",
        )
        self.open_release_btn.connect("clicked", on_open_release_clicked)
        self.release_notes_row = PreferenceRow(
            title="Release notes",
            subtitle="Notes appear here after a successful update check.",
            widget=self.open_release_btn,
            keywords=("notes", "changelog", "latest"),
        )
        self.latest_release_row = self.release_notes_row
        if self.release_notes_row.subtitle_label is not None:
            self.release_notes_row.subtitle_label.set_max_width_chars(72)
        self.release_notes_group.add_row(self.release_notes_row)
        about_tab.pack_start(self.release_notes_group, False, False, 0)
        self.release_notes_group.hide()

        family_group = PreferencesGroup(
            title="Part of VocaHQ",
            description="Private dictation for Linux, Mac, Windows, and phone.",
            keywords=("vocahq", "vocamac", "vocawin", "vocaphone", "vocagateway", "family"),
        )
        family_grid = Gtk.Grid()
        family_grid.set_column_spacing(8)
        family_grid.set_row_spacing(4)
        family_grid.set_column_homogeneous(True)
        family_grid.set_margin_start(8)
        family_grid.set_margin_end(8)
        family_grid.set_margin_top(4)
        family_grid.set_margin_bottom(8)
        for index, (url, title, subtitle, icon_names, open_name) in enumerate(_VOCAHQ_FAMILY_LINKS):
            tile = self._family_tile(url, title, subtitle, icon_names, open_name, dark=dark)
            family_grid.attach(tile, index % 2, index // 2, 1, 1)
        family_row = Gtk.ListBoxRow()
        family_row.set_activatable(False)
        family_row.add(family_grid)
        family_group.add_row(family_row)
        about_tab.pack_start(family_group, False, False, 0)
