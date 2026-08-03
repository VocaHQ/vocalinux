"""OpenAI Whisper model metadata.

The download URLs match the ones shipped in the ``openai-whisper`` package. Each
URL embeds the SHA256 digest of the checkpoint it serves, which is where the
pinned digests in ``model_hashes.json`` come from.
"""

_WHISPER_CDN_BASE = "https://openaipublic.azureedge.net/main/whisper/models"

WHISPER_MODEL_URLS = {
    "tiny": f"{_WHISPER_CDN_BASE}/"
    "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
    "base": f"{_WHISPER_CDN_BASE}/"
    "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
    "small": f"{_WHISPER_CDN_BASE}/"
    "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
    "medium": f"{_WHISPER_CDN_BASE}/"
    "345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
    "large": f"{_WHISPER_CDN_BASE}/"
    "e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt",
}
