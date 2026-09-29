"""
Floating on-screen dictation overlay for Vocalinux.

Shows a compact glowing indicator while recognition is active so users get a
clear visual cue beyond the system tray icon (similar to SuperWhisper-style
apps). The window is passive: it does not take keyboard focus or steal clicks.
"""

from __future__ import annotations

import logging
import math
from types import ModuleType
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gi.repository import Gtk

from ..common_types import RecognitionState

logger = logging.getLogger(__name__)

# Visual modes the overlay can display while visible.
MODE_LISTENING = "listening"
MODE_PROCESSING = "processing"

# Colors as (r, g, b) in 0..1 — listening = green (hot mic), processing = amber.
_COLORS = {
    MODE_LISTENING: (0.18, 0.76, 0.45),  # #2ec273
    MODE_PROCESSING: (0.95, 0.65, 0.15),  # #f2a626
}

# Animation / layout
# Thin full-width strip along the bottom; orb is drawn at horizontal center.
_STRIP_HEIGHT = 120
_ORB_SIZE = 96
_PULSE_PERIOD_MS = 1400
_ANIMATION_TICK_MS = 33  # ~30 fps
_BOTTOM_MARGIN = 48


class DictationOverlayController:
    """
    Pure state machine: enabled flag + RecognitionState → visible + mode.

    Separated from GTK so unit tests can drive show/hide without a display.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = bool(enabled)
        self._state = RecognitionState.IDLE

    @property
    def enabled(self) -> bool:
        """Whether the overlay feature is allowed to show."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the overlay feature (does not change recognition state)."""
        self._enabled = bool(enabled)

    @property
    def state(self) -> RecognitionState:
        """Last recognition state applied to the controller."""
        return self._state

    def set_state(self, state: RecognitionState) -> None:
        """Apply a recognition state transition."""
        self._state = state

    @property
    def visible(self) -> bool:
        """True when the overlay should be shown on screen."""
        if not self._enabled:
            return False
        return self._state in (RecognitionState.LISTENING, RecognitionState.PROCESSING)

    @property
    def mode(self) -> Optional[str]:
        """
        Active visual mode, or None when the overlay should be hidden.

        Returns:
            ``"listening"``, ``"processing"``, or ``None``.
        """
        if not self.visible:
            return None
        if self._state == RecognitionState.LISTENING:
            return MODE_LISTENING
        # visible is only True for LISTENING or PROCESSING
        return MODE_PROCESSING


def _try_import_layer_shell() -> Optional[ModuleType]:
    """
    Soft-import GtkLayerShell when available (Wayland, wlroots-based).

    Returns the GtkLayerShell module or None. Never raises — missing packages
    must not break installs on X11 or GNOME without the library.
    """
    try:
        import gi

        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell  # type: ignore

        module: ModuleType = GtkLayerShell
        return module
    except Exception:
        return None


class DictationOverlay:
    """
    Floating glowing dictation indicator backed by a GTK window.

    Uses a full-width bottom strip so the orb is always bottom-center of the
    monitor (Wayland often ignores move() on a small centered popup). The
    window is passive: no keyboard focus, click-through input region.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.controller = DictationOverlayController(enabled=enabled)
        self._window: Optional[Gtk.Window] = None
        self._drawing_area: Optional[Gtk.DrawingArea] = None
        self._anim_id: Optional[int] = None
        self._phase = 0.0
        self._gtk_ready = False
        self._use_layer_shell = False

        try:
            self._init_gtk_window()
            self._gtk_ready = True
        except Exception as e:
            # Headless / missing display: keep controller usable for tests.
            logger.warning("Dictation overlay window unavailable: %s", e)
            self._gtk_ready = False

    def _init_gtk_window(self) -> None:
        """Construct the floating transparent always-on-top bottom strip."""
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk  # noqa: F401

        self._GLib = GLib
        self._Gdk = Gdk
        self._Gtk = Gtk

        # TOPLEVEL is required by gtk-layer-shell; passive flags below avoid
        # keyboard focus so the active editor keeps receiving injected text.
        # Size/position are applied after map via _layout_bottom_strip.
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_title("Vocalinux Dictation")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_accept_focus(False)
        window.set_can_focus(False)
        window.set_focus_on_map(False)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        # NOTIFICATION/TOOLTIP hints: not a normal app window, less likely to
        # activate and steal focus from the dictation target.
        window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        window.set_keep_above(True)
        window.set_app_paintable(True)
        window.set_modal(False)

        # RGBA visual for true transparency when the compositor supports it.
        screen = window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            window.set_visual(visual)

        # Soft Wayland layer-shell (optional — never required).
        layer_shell = _try_import_layer_shell()
        if layer_shell is not None:
            try:
                if layer_shell.is_supported():
                    layer_shell.init_for_window(window)
                    layer_shell.set_layer(window, layer_shell.Layer.OVERLAY)
                    # Full-width bottom strip → orb drawn at horizontal center.
                    layer_shell.set_anchor(window, layer_shell.Edge.BOTTOM, True)
                    layer_shell.set_anchor(window, layer_shell.Edge.LEFT, True)
                    layer_shell.set_anchor(window, layer_shell.Edge.RIGHT, True)
                    layer_shell.set_margin(window, layer_shell.Edge.BOTTOM, _BOTTOM_MARGIN)
                    layer_shell.set_exclusive_zone(window, 0)
                    # Do not grab keyboard — critical so the focused app keeps input.
                    if hasattr(layer_shell, "set_keyboard_mode"):
                        layer_shell.set_keyboard_mode(window, layer_shell.KeyboardMode.NONE)
                    elif hasattr(layer_shell, "set_keyboard_interactivity"):
                        layer_shell.set_keyboard_interactivity(window, False)
                    self._use_layer_shell = True
                    logger.info("Dictation overlay using GtkLayerShell")
            except Exception as e:
                logger.debug("GtkLayerShell setup failed, using fallback: %s", e)
                self._use_layer_shell = False

        drawing = Gtk.DrawingArea()
        drawing.set_size_request(1, _STRIP_HEIGHT)
        drawing.set_can_focus(False)
        drawing.connect("draw", self._on_draw)
        window.add(drawing)
        window.connect("size-allocate", self._on_size_allocate)
        window.connect("realize", self._on_realize)
        window.connect("map-event", self._on_map_event)
        # Fallback placement is stale the moment monitor geometry or the
        # compositor changes; layer shell re-anchors itself on these signals.
        screen.connect("size-changed", self._on_screen_geometry_changed)
        screen.connect("monitors-changed", self._on_screen_geometry_changed)
        screen.connect("composited-changed", self._on_composited_changed)

        self._window = window
        self._drawing_area = drawing

    def _on_realize(self, widget) -> None:
        """Make the window click-through and non-focus once it has a Gdk window."""
        try:
            import cairo

            gdk_win = widget.get_window()
            if gdk_win is None:
                return
            # Empty input region → pointer events pass through to apps below.
            region = cairo.Region()
            gdk_win.input_shape_combine_region(region, 0, 0)
            # Also clear the shape region so the surface is fully transparent to hits.
            try:
                gdk_win.shape_combine_region(None, 0, 0)
            except Exception:
                pass
            try:
                # X11: override-redirect popups do not take focus; no-op on Wayland.
                if hasattr(gdk_win, "set_override_redirect"):
                    gdk_win.set_override_redirect(True)
            except Exception:
                pass
            try:
                gdk_win.set_accept_focus(False)
            except Exception:
                pass
        except Exception as e:
            logger.debug("Could not set click-through region: %s", e)

    def _on_map_event(self, widget, event) -> bool:
        """Re-apply layout after map (Wayland often ignores pre-show move())."""
        if not self._use_layer_shell:
            self._layout_bottom_strip()
        self._on_realize(widget)
        return False

    def _on_size_allocate(self, widget, allocation) -> None:
        """Keep the empty input shape after size changes."""
        if widget.get_realized():
            self._on_realize(widget)

    def _on_screen_geometry_changed(self, *_args: object) -> None:
        """Re-run fallback placement when monitors or resolution change."""
        if not self._use_layer_shell and self._window is not None and self._window.get_visible():
            self._layout_bottom_strip()

    def _on_composited_changed(self, *_args: object) -> None:
        """Re-evaluate the hide strategy when a compositor appears or leaves."""
        self._sync_window()

    def _is_wayland(self) -> bool:
        """True when the default display is a Wayland one."""
        try:
            wayland_cls = getattr(self._Gdk, "WaylandDisplay", None)
            if wayland_cls is None:
                return False
            return isinstance(self._Gdk.Display.get_default(), wayland_cls)
        except Exception:
            return False

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the feature and sync the window."""
        self.controller.set_enabled(enabled)
        self._sync_window()

    def on_recognition_state(self, state: RecognitionState) -> None:
        """Handle a recognition state change (same path as the tray icon)."""
        self.controller.set_state(state)
        self._sync_window()

    def destroy(self) -> None:
        """Tear down animation and window."""
        self._stop_animation()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def _sync_window(self) -> None:
        """Show/hide and restyle the GTK window from controller state."""
        if not self._gtk_ready or self._window is None:
            return

        mode = self.controller.mode
        if mode is None:
            self._stop_animation()
            # Opacity 0 instead of hide() — hide/show cycles re-activate the
            # window on many Wayland compositors and steal editor focus (which
            # breaks IBus/wtype injection into the previously focused app).
            # On a non-composited display opacity is a no-op, so hide the
            # window outright rather than leave a stale orb claiming the mic
            # is live.
            try:
                composited = self._window.is_composited()
            except Exception:
                composited = False
            try:
                self._window.set_opacity(0.0)
            except Exception:
                composited = False
            if not composited and self._window.get_visible():
                self._window.hide()
            return

        # Layout before first map so the first frame is already bottom-center.
        if not self._use_layer_shell:
            self._layout_bottom_strip()

        if not self._window.get_visible():
            # Map once; never call present() (steals keyboard focus).
            self._window.set_accept_focus(False)
            self._window.set_can_focus(False)
            self._window.set_focus_on_map(False)
            self._window.show_all()
            if not self._use_layer_shell:
                self._GLib.idle_add(self._layout_bottom_strip_idle)

        try:
            self._window.set_opacity(1.0)
        except Exception:
            pass

        self._start_animation()
        if self._drawing_area is not None:
            self._drawing_area.queue_draw()

    def _layout_bottom_strip_idle(self) -> bool:
        self._layout_bottom_strip()
        return False  # one-shot idle

    def _layout_bottom_strip(self) -> None:
        """
        Size the window as a full-width bottom strip and place it on the primary monitor.

        Drawing the orb at the strip's horizontal center always yields bottom-center
        of the screen, even when the compositor only roughly honors move().
        On Wayland without layer shell, move() is a hint the compositor can
        ignore entirely, so ask for a centered compact window instead of
        promising a bottom position it cannot place.
        """
        if self._window is None:
            return
        try:
            display = self._Gdk.Display.get_default()
            if display is None:
                return
            monitor = display.get_primary_monitor()
            if monitor is None and display.get_n_monitors() > 0:
                monitor = display.get_monitor(0)
            if monitor is None:
                return
            geom = monitor.get_geometry()
            height = _STRIP_HEIGHT
            wayland = self._is_wayland()
            if wayland:
                self._window.set_position(self._Gtk.WindowPosition.CENTER_ALWAYS)
                width = _ORB_SIZE
            else:
                width = max(geom.width, _ORB_SIZE)
            self._window.resize(width, height)
            if self._drawing_area is not None:
                self._drawing_area.set_size_request(width, height)
            if not wayland:
                x = geom.x
                y = geom.y + geom.height - height - _BOTTOM_MARGIN
                self._window.move(x, y)
        except Exception as e:
            logger.debug("Could not layout overlay strip: %s", e)

    def _start_animation(self) -> None:
        if self._anim_id is not None:
            return
        self._phase = 0.0
        self._anim_id = self._GLib.timeout_add(_ANIMATION_TICK_MS, self._on_anim_tick)

    def _stop_animation(self) -> None:
        if self._anim_id is not None:
            try:
                self._GLib.source_remove(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def _on_anim_tick(self) -> bool:
        self._phase = (self._phase + _ANIMATION_TICK_MS / _PULSE_PERIOD_MS) % 1.0
        if self._drawing_area is not None:
            self._drawing_area.queue_draw()
        # Keep ticking while visible.
        return self.controller.visible

    def _on_draw(self, widget, cr) -> bool:
        """Cairo draw: soft multi-ring glow + solid core at bottom-center of strip."""
        mode = self.controller.mode
        if mode is None:
            return False

        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        # Orb sits in the horizontal center of the full-width strip.
        cx = width / 2.0
        cy = height / 2.0
        # Draw relative to a fixed orb diameter so a wide strip does not stretch it.
        orb = float(min(_ORB_SIZE, width, height))
        base_r, base_g, base_b = _COLORS[mode]

        # Clear to fully transparent (SOURCE then OVER for compositors with alpha).
        try:
            import cairo as _cairo

            cr.set_operator(_cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(_cairo.OPERATOR_OVER)
        except Exception:
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()

        # Pulse 0..1 → soft scale/alpha modulation (quieter while processing).
        if mode == MODE_PROCESSING:
            pulse = 0.55 + 0.25 * math.sin(self._phase * 2.0 * math.pi)
            alpha_scale = 0.75
            core_a = 0.8
        else:
            pulse = 0.5 + 0.5 * math.sin(self._phase * 2.0 * math.pi)
            alpha_scale = 1.0
            core_a = 0.95

        # Outer glow rings.
        for radius_scale, ring_a in ((0.95, 0.12), (0.72, 0.22), (0.52, 0.35)):
            radius = (orb * 0.42) * radius_scale * (0.92 + 0.08 * pulse)
            alpha = ring_a * (0.55 + 0.45 * pulse) * alpha_scale
            cr.set_source_rgba(base_r, base_g, base_b, alpha)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.fill()

        # Expanding ripple (listening only).
        if mode == MODE_LISTENING:
            ripple_r = (orb * 0.28) + self._phase * (orb * 0.28)
            ripple_a = max(0.0, 0.45 * (1.0 - self._phase))
            cr.set_source_rgba(base_r, base_g, base_b, ripple_a)
            cr.set_line_width(2.0)
            cr.arc(cx, cy, ripple_r, 0, 2 * math.pi)
            cr.stroke()

        # Solid core.
        core_r = orb * 0.16 * (0.95 + 0.05 * pulse)
        cr.set_source_rgba(base_r, base_g, base_b, core_a)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()

        return False
