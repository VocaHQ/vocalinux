# Choosing a speech model

Vocalinux never downloads a speech model on its own. Changing the model pickers in
Settings → Speech Model only selects a model. If that model is not on disk yet, the
info card shows its download size and a **Download** button, and the transfer starts
only after you confirm it. Cancelling the download, or declining the confirmation,
puts the pickers back on the model you were already using.

This page is a static guide to help you pick. The numbers are approximate starting
points, not measurements of your machine. If dictation feels slow, go one size down;
if it makes too many mistakes and speed is fine, go one size up.

## whisper.cpp (default engine)

| Your hardware | Suggested size | Notes |
|---|---|---|
| Under 8 GB RAM, CPU only | Tiny | Fastest. Accuracy is noticeably lower. |
| 8 to 16 GB RAM, CPU only | Tiny or Base | Base is a good default on a recent CPU. |
| 16 GB RAM or more, CPU only | Base, or Small if you can wait | Small on CPU can take a few seconds per sentence. |
| Vulkan GPU (AMD, Intel, NVIDIA) with under 8 GB RAM | Base | |
| Vulkan GPU with 8 GB RAM or more | Small | Older or low power GPUs may still prefer Base. |
| NVIDIA GPU (CUDA) with under 4 GB VRAM | Base | |
| NVIDIA GPU (CUDA) with 4 to 8 GB VRAM | Small | |
| NVIDIA GPU (CUDA) with 8 GB VRAM or more | Medium, or Large v3 Turbo | Large v3 Turbo is close to Large in accuracy at lower cost. |

Settings → Speech Model may show a line such as "Suggested for this computer: Small".
That line is information only, based on the same rules as this table. It never changes
your model and never starts a download.

## Model sizes and variants

Each size comes in several variants. The quantized ones (`q5_0`, `q5_1`, `q8_0`) are
smaller files that use less memory, at a small cost in accuracy; `q8_0` is the
closest to the full model. The `.en` variants are English only and are a little
more accurate for English.

| Size | Full download | Q8_0 | Q5 | Parameters |
|---|---|---|---|---|
| Tiny | 74 MB | 32 MB | 15 MB (q5_1) | 39M |
| Base | 141 MB | 82 MB | 60 MB (q5_1) | 74M |
| Small | 465 MB | 190 MB | 163 MB (q5_1) | 244M |
| Medium | 1.4 GB | 823 MB | 568 MB (q5_0) | 769M |
| Large v3 Turbo | 1.6 GB | 874 MB | 574 MB (q5_0) | 809M |
| Large (v3) | 2.9 GB | | 1.1 GB (q5_0) | 1550M |

Sizes are the catalog values Vocalinux shows before a download; the file on disk can
differ slightly.

If you already have a quantized model of the size you want (for example Small Q8_0),
there is no reason to download the full model of the same size.

## Other engines

- **Vosk**: the small models (about 40 MB) run on any CPU and are the lightest
  option.
- **Faster Whisper** and **OpenAI Whisper**: the same size guidance as the table above.
- **Parakeet**: one model of about 640 MB.
- **Remote API**: transcription runs on your server, nothing is downloaded locally.

Models are stored under `~/.local/share/vocalinux/models/` by default. Deleting a file there
removes the model; Vocalinux will show it as not downloaded again.
