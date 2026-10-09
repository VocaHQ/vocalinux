# Vocalinux for Nix.
#
# Consumed by the repo flake (packages.<system>.vocalinux) and buildable with
# plain callPackage:
#
#   pkgs.python3Packages.callPackage ./packaging/nix/package.nix {
#     pywhispercpp = pkgs.python3Packages.callPackage ./packaging/nix/pywhispercpp.nix { };
#     src = ./.;
#   }
#
# Layout mirrors packaging/native/nfpm.yaml: the interpreter, GTK, PyGObject
# and the AppIndicator typelib come from nixpkgs, pywhispercpp is built from
# its vendored sdist, and every host tool the injectors probe for
# (shutil.which) is wired onto PATH so the packaged binary behaves like the
# deb/rpm install with Recommends installed.
{
  lib,
  buildPythonApplication,
  setuptools,
  gobject-introspection,
  wrapGAppsHook3,
  gtk3,
  libayatana-appindicator,
  ibus,
  libnotify,
  glib,
  # Python dependencies (resolved from python3Packages scope).
  pywhispercpp,
  pynput,
  evdev,
  requests,
  pysocks,
  numpy,
  pyaudio,
  pygobject3,
  pycairo,
  psutil,
  onnxruntime,
  tqdm,
  platformdirs,
  # Host binaries the app probes for with shutil.which at runtime.
  xdotool,
  wtype,
  ydotool,
  wl-clipboard,
  xclip,
  xsel,
  xorg,
  pulseaudio,
  alsa-utils,
  src,
}:

let
  # Host tools the injectors, clipboard fallbacks, audio cues and layout
  # probing shell out to. Prepending them mirrors installing the deb/rpm
  # Recommends set. gdbus comes from glib.bin; ibus covers ibus/ibus-daemon.
  runtimeTools = [
    xdotool
    wtype
    ydotool # provides ydotoold too
    wl-clipboard # wl-copy / wl-paste
    xclip
    xsel
    xorg.xprop
    xorg.setxkbmap
    ibus
    libnotify # notify-send
    pulseaudio # paplay
    alsa-utils # aplay
    (lib.getBin glib) # gdbus
  ];
in
buildPythonApplication {
  pname = "vocalinux";

  # Track src/vocalinux/version.py so release bumps need no edit here.
  # builtins.match is POSIX ERE (no \s class), so flatten newlines first.
  version =
    let
      match = builtins.match ''.*__version__ = "([^"]+)".*'' (
        builtins.replaceStrings [ "\n" ] [ " " ] (
          builtins.readFile (src + "/src/vocalinux/version.py")
        )
      );
    in
    if match == null then "0.0.0" else builtins.head match;

  inherit src;
  pyproject = true;

  nativeBuildInputs = [
    # Registers GI_TYPELIB_PATH for every buildInput shipping typelibs, and
    # wraps the entry point with the GLib/GTK environment.
    gobject-introspection
    wrapGAppsHook3
  ];

  buildInputs = [
    gtk3 # Gtk-3.0
    libayatana-appindicator # AyatanaAppIndicator3-0.1 (+ AppIndicator3 fallback)
    ibus # IBus-1.0 typelib for the Wayland injection engine
    libnotify # Notify-0.7
  ];

  build-system = [ setuptools ];

  dependencies = [
    pywhispercpp # default whisper.cpp engine; vendored sdist build
    pynput # X11 hotkey backend
    evdev # Wayland/evdev hotkey backend + uinput clone
    requests
    pysocks
    numpy
    pyaudio
    pygobject3
    pycairo
    psutil
    onnxruntime # [vad] extra: Silero VAD
    tqdm # model download progress (pywhispercpp also depends on it)
    platformdirs
  ];

  # Optional engines are intentionally not packaged: [whisper] pulls PyTorch,
  # and vosk/sherpa-onnx/faster-whisper are not in nixpkgs. The whisper.cpp
  # engine remains the default; other engines can be layered on with an
  # overlay later.

  preFixup = ''
    gappsWrapperArgs+=(
      --prefix PATH : ${lib.makeBinPath runtimeTools}
    )
  '';

  postInstall = ''
    install -Dm644 vocalinux.desktop \
      $out/share/applications/vocalinux.desktop
    install -Dm644 resources/icons/scalable/vocalinux.svg \
      $out/share/icons/hicolor/scalable/apps/vocalinux.svg
  '';

  dontCheck = true; # test suite needs a session bus and X display

  pythonImportsCheck = [ "vocalinux" ];

  meta = {
    description = "Free, offline voice dictation for Linux";
    longDescription = ''
      Hold a shortcut or toggle dictation and text lands in almost any app on
      X11 or Wayland. Speech recognition runs locally with whisper.cpp after
      downloading a model on first use.

      Wayland/evdev shortcuts and ydotool injection need device access: on
      NixOS enable hardware.uinput and add your user to the "input" and
      "uinput" groups; the programs.vocalinux NixOS module does the first part.
    '';
    homepage = "https://github.com/VocaHQ/vocalinux";
    license = lib.licenses.agpl3Only;
    mainProgram = "vocalinux";
    platforms = lib.platforms.linux;
  };
}
