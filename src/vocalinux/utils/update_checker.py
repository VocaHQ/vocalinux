"""Check GitHub Releases for newer Vocalinux versions."""

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from ..version import __url__

logger = logging.getLogger(__name__)

UPDATE_CHANNELS = ("stable", "nightly")
DEFAULT_UPDATE_CHANNEL = "stable"

_GITHUB_REPO_RE = re.compile(r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")
_PRE_RELEASE_SUFFIX_RE = re.compile(
    r"^(?P<main>\d+(?:\.\d+)*)(?:[-.](?P<pre>(?:alpha|beta|rc|pre|dev)\.?\d*))?$",
    re.IGNORECASE,
)
_NIGHTLY_TAG_RE = re.compile(r"^nightly-(\d{4}-\d{2}-\d{2})$", re.IGNORECASE)
# Nightly CI embeds the build day as ``.devYYYYMMDD[+sha]`` (see release names).
_DEV_DATE_RE = re.compile(r"(?:^|[.+-])dev(\d{8})(?:[.+-]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class ReleaseInfo:
    """Metadata for a GitHub release."""

    tag_name: str
    version: str
    name: str
    html_url: str
    body: str
    published_at: str
    prerelease: bool
    channel: str = DEFAULT_UPDATE_CHANNEL


def normalize_channel(channel: Optional[str]) -> str:
    """Return a supported update channel id."""
    value = (channel or DEFAULT_UPDATE_CHANNEL).strip().casefold()
    return value if value in UPDATE_CHANNELS else DEFAULT_UPDATE_CHANNEL


def _repo_parts(repo_url: str = __url__) -> tuple[str, str]:
    match = _GITHUB_REPO_RE.match(repo_url.strip())
    if not match:
        raise ValueError(f"Unsupported repository URL: {repo_url}")
    return match.group("owner"), match.group("repo")


def _repo_api_base(repo_url: str = __url__) -> str:
    owner, repo = _repo_parts(repo_url)
    return f"https://api.github.com/repos/{owner}/{repo}"


def normalize_version(version: str) -> str:
    """Strip a leading ``v`` and surrounding whitespace."""
    return version.strip().lstrip("vV")


def _version_key(version: str) -> tuple:
    """Build a sortable key for PEP-440-like version strings."""
    version = normalize_version(version)
    if not version:
        return (0, 0, 0, 0, "")

    match = _PRE_RELEASE_SUFFIX_RE.match(version)
    if match:
        main = match.group("main")
        prerelease = match.group("pre") or ""
    else:
        main, _, prerelease = version.partition("-")
        # Drop build metadata (+flatpak) so it does not pollute comparison.
        main = main.split("+", 1)[0]
        prerelease = prerelease.split("+", 1)[0]

    parts: list[int] = []
    for part in main.split("."):
        if part.isdigit():
            parts.append(int(part))
        elif part:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)

    # Stable releases outrank pre-releases with the same numeric prefix.
    release_rank = 1 if not prerelease else 0
    return tuple(parts) + (release_rank, prerelease.casefold())


def is_newer_version(current: str, latest: str) -> bool:
    """Return True when ``latest`` is newer than ``current`` (stable semver tags)."""
    return _version_key(latest) > _version_key(current)


def _nightly_date(tag_or_version: str) -> Optional[str]:
    """Return YYYY-MM-DD from a nightly tag or ``.devYYYYMMDD`` version, or None."""
    text = tag_or_version.strip()
    match = _NIGHTLY_TAG_RE.match(text) or _NIGHTLY_TAG_RE.match(normalize_version(text))
    if match:
        return match.group(1)

    # Installed nightlies report versions like ``0.14.2.dev20260802+27ecf88``.
    dev_match = _DEV_DATE_RE.search(text)
    if not dev_match:
        return None
    raw = dev_match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def is_update_available(
    current: str, latest: ReleaseInfo, channel: str = DEFAULT_UPDATE_CHANNEL
) -> bool:
    """Return whether ``latest`` is an update for ``current`` on the given channel."""
    channel = normalize_channel(channel)
    if channel == "nightly":
        current_tag = current.strip()
        if current_tag == latest.tag_name or normalize_version(current_tag) == latest.version:
            return False
        current_nightly = _nightly_date(current_tag)
        latest_nightly = _nightly_date(latest.tag_name) or _nightly_date(latest.name)
        if current_nightly and latest_nightly:
            return latest_nightly > current_nightly
        # Stable (or other) install following the nightly channel → offer latest nightly.
        return True
    return is_newer_version(current, latest.version)


# github.com/jatinkrmalik/vocalinux redirects here after the org transfer.
_VOCALINUX_GITHUB_OWNERS = frozenset({"VocaHQ", "jatinkrmalik"})


def _trusted_path_prefixes(repo_url: str = __url__) -> tuple[str, ...]:
    """Return GitHub path prefixes that belong to this project."""
    owner, repo = _repo_parts(repo_url)
    prefixes = [f"/{owner}/{repo}"]
    known_owners = {name.casefold() for name in _VOCALINUX_GITHUB_OWNERS}
    if repo.casefold() == "vocalinux" and owner.casefold() in known_owners:
        prefixes.extend(f"/{name}/vocalinux" for name in sorted(_VOCALINUX_GITHUB_OWNERS))
    seen: set[str] = set()
    unique: list[str] = []
    for prefix in prefixes:
        key = prefix.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(prefix)
    return tuple(unique)


def is_trusted_release_url(url: str, repo_url: str = __url__) -> bool:
    """Return True when ``url`` points at this project's GitHub pages."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        prefixes = _trusted_path_prefixes(repo_url)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        return False
    path = parsed.path.rstrip("/")
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def _release_from_payload(
    data: dict, channel: str, repo_url: str = __url__
) -> Optional[ReleaseInfo]:
    tag_name = data.get("tag_name") or ""
    if not tag_name:
        return None

    html_url = data.get("html_url") or ""
    if html_url and not is_trusted_release_url(html_url, repo_url):
        logger.warning("Ignoring untrusted release URL: %s", html_url)
        html_url = ""

    return ReleaseInfo(
        tag_name=str(tag_name),
        version=normalize_version(str(tag_name)),
        name=str(data.get("name") or tag_name),
        html_url=html_url,
        body=str(data.get("body") or ""),
        published_at=str(data.get("published_at") or ""),
        prerelease=bool(data.get("prerelease")),
        channel=channel,
    )


def fetch_latest_release(
    repo_url: str = __url__,
    timeout: float = 10.0,
    channel: str = DEFAULT_UPDATE_CHANNEL,
) -> Optional[ReleaseInfo]:
    """Fetch the newest GitHub release for ``channel`` (``stable`` or ``nightly``)."""
    import requests

    channel = normalize_channel(channel)
    api_base = _repo_api_base(repo_url)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Vocalinux-UpdateChecker",
    }

    try:
        if channel == "stable":
            response = requests.get(f"{api_base}/releases/latest", headers=headers, timeout=timeout)
            if response.status_code == 404:
                logger.warning("No latest release found for %s", api_base)
                return None
            if response.status_code == 403:
                logger.warning("GitHub API rate-limited or forbidden for %s", api_base)
                return None
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return None
            return _release_from_payload(data, channel, repo_url)

        # Page through releases so a burst of non-nightly tags cannot hide the
        # newest nightly beyond the first response page.
        max_pages = 10
        for page in range(1, max_pages + 1):
            response = requests.get(
                f"{api_base}/releases",
                headers=headers,
                params={"per_page": 30, "page": page},
                timeout=timeout,
            )
            if response.status_code == 403:
                logger.warning("GitHub API rate-limited or forbidden for %s", api_base)
                return None
            response.raise_for_status()
            releases = response.json()
            if not isinstance(releases, list) or not releases:
                break

            for item in releases:
                if not isinstance(item, dict) or item.get("draft"):
                    continue
                tag_name = str(item.get("tag_name") or "")
                if _NIGHTLY_TAG_RE.match(tag_name):
                    return _release_from_payload(item, channel, repo_url)

        logger.warning("No nightly release found for %s", api_base)
        return None
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning("Failed to fetch latest release: %s", exc)
        return None


def format_release_notes(body: str) -> str:
    """Convert common GitHub-flavored markdown to readable plain text."""
    if not body:
        return "No release notes were published for this version."

    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<img\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?details[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?summary[^>]*>", "", text, flags=re.IGNORECASE)
    # Keep fenced code contents (install commands) but drop the fences.
    text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", text)
    # Flatten markdown tables into "Area: Description" lines.
    text = re.sub(r"^\|[-:| ]+\|\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$",
        r"• \1: \2",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
