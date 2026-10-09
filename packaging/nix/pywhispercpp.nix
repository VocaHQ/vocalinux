# pywhispercpp is not in nixpkgs (same gap the .deb/.rpm note in
# packaging/native/nfpm.yaml calls out for Debian and Fedora), so the flake
# builds it here. The PyPI sdist already vendors whisper.cpp and pybind11, so
# no extra source fetches are needed; setup.py drives CMake from build_ext.
{
  lib,
  buildPythonPackage,
  fetchPypi,
  setuptools,
  wheel,
  cmake,
  numpy,
  requests,
  tqdm,
  platformdirs,
  autoPatchelfHook,
  stdenv,
}:

buildPythonPackage rec {
  pname = "pywhispercpp";
  version = "1.5.1";
  pyproject = true;

  src = fetchPypi {
    inherit pname version;
    hash = "sha256-XfiX5d2dnxaAT8k3vYW59YgKCymlX4hDWF4OA9dhleU=";
  };

  # python -m build verifies every build-system.requires entry resolves to an
  # installed Python package. The ones setup.py never imports are dropped:
  # ninja is try/except'd (Unix Makefiles are the fallback), repairwheel only
  # runs on Windows, setuptools-scm is unused, and cmake is a PATH tool, not a
  # Python package.
  postPatch = ''
    substituteInPlace pyproject.toml \
      --replace-fail '    "ninja",' "" \
      --replace-fail '    "cmake>=3.12",' "" \
      --replace-fail '    "repairwheel",' "" \
      --replace-fail '    "setuptools-scm>=8"' ""

    # setup() passes no version, so without setuptools-scm the wheel metadata
    # lands as 0.0.0; get_version() reads PYWHISPERCPP_VERSION instead.
    substituteInPlace setup.py \
      --replace-fail '    name="pywhispercpp",' '    name="pywhispercpp", version=get_version(),'
  '';

  env = {
    # The sdist ships no version.txt; setup.py falls back to this env var.
    PYWHISPERCPP_VERSION = version;
    # One static extension module (BUILD_SHARED_LIBS defaults ON upstream and
    # would need $ORIGIN rpath repair that never runs outside cibuildwheel) and
    # a portable baseline instead of -march=native.
    CMAKE_ARGS = "-DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON";
  };

  # env attrs are exported verbatim; expanding the core count needs a shell
  # phase.
  preBuild = ''
    export CMAKE_BUILD_PARALLEL_LEVEL="$NIX_BUILD_CORES"
  '';

  # cmake is only here so setup.py's build_ext can invoke it; letting the
  # cmake configure hook run standalone leaves a build/ dir that breaks the
  # pypa wheel build.
  dontUseCmakeConfigure = true;

  nativeBuildInputs = [
    cmake
    autoPatchelfHook
  ];

  build-system = [
    setuptools
    wheel
  ];

  # libstdc++/libgomp for the compiled extension.
  buildInputs = [ stdenv.cc.cc.lib ];

  dependencies = [
    numpy
    requests
    tqdm
    platformdirs
  ];

  # pywhispercpp.model pulls in the compiled _pywhispercpp extension, so
  # checking all three proves the native binding loads, not just the package.
  pythonImportsCheck = [ "pywhispercpp" "pywhispercpp.model" "_pywhispercpp" ];

  meta = {
    description = "Python bindings for whisper.cpp";
    homepage = "https://github.com/absadiki/pywhispercpp";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
  };
}
