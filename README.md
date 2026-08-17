# VQC Demo — Projector Receiver / Decoder POC

Intensity-proxy proof of concept for the **Vortex Quaternion Conduit** software decoder, using a **Sony VPL-HW20A** (1080p SXRD lamp projector) as a free-space display and a camera as the receiver.

Parent simulations live in [`../vqc`](../vqc) and [`../vqc_proto`](../vqc_proto). This directory is self-contained and does **not** require those packages at runtime.

> **Honesty first.** The VPL-HW20A cannot emit coherent Laguerre-Gaussian modes, helical phase fronts \(\exp(i\ell\phi)\), or nested helices-within-a-helix. It projects **incoherent RGB intensity**. This POC is a data-path / decoder demo and a presentation channel — not a physical OAM link. A real optical embodiment still needs a laser + SLM transmitter and a mode-sorting receiver.

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
| 16-qubit QEC proxy | Byte-level [[3,1,3]] repetition + majority vote |
| Integrity | CRC-32 over the payload |
| ICA / demix | 3×3 colour-mix invert from the CALIB RGB patches — not FastICA |
| Pyramidal FM | Triangle luminance bar across the packet (visual only) |
| BMGL / turbulence | Software blur/gamma/noise in `--channel`. Not physical scintillation |

Default test message is the patent Figure 1 payload: **`I live in Oregon`**.

---

## Quick start

```bash
cd ~/Projects/vqc_demo
python3 -m pip install -e ".[dev]"

# In-memory encode → decode (fast 320×180; add --full for 1080p)
python3 -m vqc_demo loopback "I live in Oregon"
python3 -m vqc_demo loopback "I live in Oregon" --channel   # blur / gamma / noise

# Render 1080p24 frames and stitch an MP4 for the VPL-HW20A
python3 -m vqc_demo encode "I live in Oregon" -o outputs/tx

# After you film the screen, decode the capture (writes fidelity.json)
python3 -m vqc_demo decode path/to/capture.mp4 --expected "I live in Oregon"
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
