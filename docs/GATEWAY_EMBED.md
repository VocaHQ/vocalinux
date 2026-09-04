# Local VocaGateway from Vocalinux (optional)

Vocalinux can start a **local** [VocaGateway](https://github.com/VocaHQ/vocagateway)
container from **Settings → Speech Engine**, next to Remote Server. This is an
optional power-user path. It is **not** on-device processing: microphone audio
still leaves the desktop client and is transcribed by the gateway process on
your machine (or LAN).

The default speech engine remains **whisper.cpp** on-device. Enabling a local
gateway never changes that default by itself. Use **Use this Gateway** only when
you want Vocalinux to talk to the gateway over the existing Remote API settings
(`remote_api_*`, endpoint `/v1/audio/transcriptions`). See [HTTP_REMOTE.md](HTTP_REMOTE.md).

## Requirements (Linux MVP)

- **podman** (preferred) or **docker**, with a working `compose` plugin (or
  `podman-compose` / `docker-compose`).
- Vocalinux does **not** bundle a container engine inside the AppImage.
- **Flatpak**: the sandbox cannot reach the host container socket. Run the
  native package or AppImage, or start VocaGateway on the host yourself and
  point Remote Server at it.

## What Vocalinux does

1. Pins upstream **VocaGateway `v0.1.0`** (git tag) under your XDG cache and uses
   that checkout's `compose.yaml` with Compose project name `vocagateway`.
2. Writes a private bootstrap token under `~/.config/vocalinux/gateway_embed/`
   (mode `600`) and a matching Compose `.env`.
3. Runs `compose -f compose.yaml --profile cpu up -d` for the `gateway` service.
   The v0.1.0 GitHub release has no published container image assets, so the first
   start **builds** the local image `vocagateway:v0.1.0` from that tag (override with
   `VOCAGATEWAY_IMAGE`; never `latest`). Later starts reuse the image/volume.
4. Polls `GET /health/live` and `GET /health/ready`, and (when live) authenticated
   `GET /v1/admin/pairing` for phone pairing.
5. Stops with `compose down` **without** `-v`, so the named data volume (models,
   config) is kept.

## Status labels

| Status | Meaning |
| --- | --- |
| Stopped | Not running (or not managed). |
| Starting | Compose up in progress, or live probe not green yet. |
| Live | Process answers `/health/live`. |
| Pairable | Live, plus a **non-loopback** phone URL and bearer token (QR-safe). |
| Ready | `/health/ready` is 200 (model selected in the gateway WebUI). |
| Error | Start/stop or probe failure (see the subtitle). |

Pairable can appear before Ready: you can pair a phone while a model is still
downloading.

## LAN / phone

By default the published host is `127.0.0.1` (desktop-only). Turn on **Allow LAN
access for Phone** to set `VOCAGATEWAY_PUBLISH_HOST=0.0.0.0` and to advertise a
LAN URL in pairing. Open port `8765` in your firewall only on trusted networks.
Never put `127.0.0.1` / `localhost` in the phone QR.

## Tray

While this Vocalinux session started the gateway, the tray menu offers **Stop
local Gateway**. Vocalinux does not auto-start the gateway on login in v1.

## Honesty

VocaGateway is optional self-hosted infrastructure for the Voca family. There is
no Voca account and no hosted Voca cloud. Prefer a trusted LAN, Tailscale, or
HTTPS. Do not expose port 8765 to the public internet.
