# VQC Demo — Projector Receiver / Decoder POC

Intensity-proxy proof of concept for the **Vortex Quaternion Conduit** software decoder, using a **Sony VPL-HW20A** (1080p SXRD lamp projector) as a free-space display and a camera as the receiver.

Parent simulations: [`vqc`](https://github.com/kinaar8340/vqc_sims_public) · [`vqc_proto`](https://github.com/kinaar8340/vqc_proto). This directory is self-contained.

> **Honesty first.** The VPL-HW20A cannot emit coherent Laguerre-Gaussian modes, helical phase fronts \(\exp(i\ell\phi)\), or nested helices-within-a-helix. It projects **incoherent RGB intensity**. Treat the projector footage as **marketing and data-path validation**, not the final optical claim. A real free-space OAM link still needs a laser + phase-only SLM + Fourier optics + a mode sorter. That is the garage-to-lab cost. Until then, the highest-leverage work is the software embodiment and the open demos.

The coherent handoff (phase maps you can load on a real SLM, no reverse-engineering required) is [`docs/SLM_QUICKSTART.md`](docs/SLM_QUICKSTART.md).

---

## What it does

```
payload  →  8 concentric LG donuts (ℓ = 1…8)
         →  PNG sequence @ 1920×1080
         →  ffmpeg → vqc_poc.mp4  (1080p24, yuv420p)
         →  HDMI → VPL-HW20A
         →  camera / captured MP4
         →  ring sampler + [[3,1,3]] majority QEC + CRC32
         →  recovered payload
```

| Piece | How this POC represents it |
|---|---|
| OAM multiplex | 8 concentric donuts (ℓ = 1…8). Sharp annuli carry bits; a faint true-LG wash gives the nested-donut look |
| DWDM proxy | Each ℓ is a distinct RGB colour (red→magenta). Not a wavelength mux |
| Orbital Braille PWM | Ring **on** = bit 1, faint guide = bit 0 |
| Quaternion shard | Gold spoke (angle from \(x,y\)). Decoder recovers a unit-q from the spoke |
| 16-qubit QEC proxy | Byte-level [[3,1,3]] or [[5,1,5]] majority vote |
| Quaternion alphabet | 24-vertex binary tetrahedral atlas (Hopf shard), snapped from the payload |
| Integrity | CRC-32 over the payload |
| ICA / demix | 3×3 colour-mix invert from the CALIB RGB patches — not FastICA |
| Pyramidal FM | Triangle luminance bar across the packet (visual only) |
| BMGL / turbulence | Named software presets (`projector`, `kolmogorov`, `bmgl`). Intensity proxies only |

Default test message is the patent Figure 1 payload: **`I live in Oregon`**.

---

## Quick start

```bash
cd ~/Projects/vqc_demo
python3 -m pip install -e ".[dev]"

# In-memory encode → decode (fast 320×180; add --full for 1080p)
python3 -m vqc_demo loopback "I live in Oregon"
python3 -m vqc_demo loopback "I live in Oregon" --preset projector
python3 -m vqc_demo loopback "I live in Oregon" --preset kolmogorov

# Render 1080p24 frames and stitch an MP4 for the VPL-HW20A
python3 -m vqc_demo encode "I live in Oregon" -o outputs/tx

# After you film the screen, decode the capture (writes fidelity.json)
python3 -m vqc_demo decode path/to/capture.mp4 --expected "I live in Oregon"

# Phase-only SLM package (bench, not the projector)
python3 -m vqc_demo slm "I live in Oregon" -o outputs/slm/generic_512

# Publish software-fidelity numbers
python3 -m vqc_demo stress -o docs/published_metrics.json
```

`encode` writes:

```
outputs/tx/
  frames/frame_00000.png …
  vqc_poc.mp4
  contact_sheet.png
  manifest.json
```

---

## Projector setup (VPL-HW20A)

| Setting | Value |
|---|---|
| Resolution | **1920×1080 native** (do not let the player letterbox) |
| Frame rate | **24p** (True Cinema) — each symbol is held 8 frames ≈ 333 ms |
| Input | HDMI from the laptop / media player |
| Pixel format | `yuv420p` Rec.709 (ffmpeg default for this encode) |
| Overscan | Off if the menu allows; rings sit inside an 88% safe area |
| Reality Creation / sharpness | Off or low — extra edge enhancement fights the decoder |
| Keystone | Avoid. Use lens shift and square the camera to the screen |
| Screen | Matte white. Kill ambient light |
| Camera | Tripod, match 24/30/60 fps, lock exposure / white balance |

ffmpeg line used by the stitcher:

```bash
ffmpeg -y -framerate 24 -i frames/frame_%05d.png \
  -c:v libx264 -pix_fmt yuv420p -s 1920x1080 -crf 18 \
  -tune stillimage -movflags +faststart vqc_poc.mp4
```

---

## Packet

```
[1 s calibration cross + RGB patches]
[0.5 s black]
SYNC 0xAA × 3
SYNC 0x55 × 3
length (u16 BE) × 3
version (u8) × 3
payload bytes, each × 3
CRC-32 (4 bytes), each × 3
SYNC 0xF0 × 3
[0.5 s black]
```

Each logical byte is one video symbol: eight rings, LSB = inner ring. Body bytes are XOR-whitened with `0xA5` so a zero length field does not look like a black frame. The decoder majority-votes the `hold_frames` copies of a symbol, then majority-votes the three QEC repeats.

---

## Tests

```bash
python3 -m pytest tests
```

Loopback tests run at 320×180 so CI stays fast. The same codec is used at 1080p.

---

## Layout

```
vqc_demo/
  configs/default.yaml     projector + optics + capture model
  src/vqc_demo/
    projector.py           VPL-HW20A profile
    lg.py                  LG p=0 intensity (from vqc_proto/lg_modes)
    codec.py               framing, CRC, QEC, quaternion spoke
    frames.py              1920×1080 renderer
    video.py               ffmpeg stitch / extract
    decoder.py             ring sampler + RGB demix + spoke recovery
    channel.py             software camera model
    fidelity.py            BER / QEC / quaternion error report
    pipeline.py            encode / decode / loopback
    cli.py
  tests/
```

Tunables (`hold_frames`, ring count, QEC reps, blur) live in `configs/default.yaml`.

---

## Published software metrics

`python3 -m vqc_demo stress` writes [`docs/published_metrics.json`](docs/published_metrics.json). Snapshot (v0.2.0, payload `I live in Oregon`, 320×180):

| Channel | QEC-3 | QEC-5 |
|---|---|---|
| clean | pass, BER 0 | pass, BER 0 |
| projector | pass, BER 0 | pass, BER 0 |
| bmgl (intensity proxy) | pass, BER 0 | pass, BER 0 |
| kolmogorov r₀=0.18 | **fail** (lost sync) | **fail** (lost sync) |

That last row is the point of the sweep: the decoder has a measured ceiling under a log-normal scintillation screen. These are **software intensity-proxy** numbers, not a free-space OAM BER.

---

## What this is not

- Not coherent OAM, not nested helices-within-a-helix, not BMGL on a real wavefront.
- Not Fisher–Rao font geometry or FastICA — those live in [`vqc_proto`](https://github.com/kinaar8340/vqc_proto) (HF Space included).
- Not the drift-resistant memory architecture — that is [`qvpic`](https://github.com/kinaar8340) / local `qvpic`.

The remaining ceiling is optical coherence and mode sorting. Until that equipment exists, keep the projector footage honest and keep the software + SLM export path open so anyone with a bench can load the phase patterns without reverse-engineering.

---

X: [@kinaar8340](https://x.com/kinaar8340)
