# SLM Quickstart — coherent handoff from the projector POC

The VPL-HW20A loop is an **intensity RGB-proxy**. It validates framing, ring sampling, colour demix, spoke recovery, and QEC. It is **not** a free-space OAM transmitter.

This package is what you load on a **phase-only SLM** once you have a laser and a Fourier lens. You do not need to reverse-engineer `vqc_proto`.

```bash
cd ~/Projects/vqc_demo
python3 -m vqc_demo slm "I live in Oregon" -o outputs/slm/generic_512
python3 -m vqc_demo slm "I live in Oregon" --preset holoeye_pluto_2 -o outputs/slm/pluto
```

## Bundle

| File | Purpose |
|---|---|
| `frames/phase_0000.png` … | 8-bit (or 16-bit TIFF) phase maps — **upload these** |
| `frames/phase_0000.raw` | Little-endian gray levels for custom drivers |
| `phase_stack.npy` | Float radians `[N, H, W]` |
| `manifest.json` | Payload, 24-vertex quaternion atlas index, PWM duties, device |
| `LUT_calibration.txt` | Linear 0…2π → gray |
| `preview_montage.png` | Visual check before the bench |
| `README.txt` | Same content, lives inside the zip-able folder |

## Device presets

| Preset | Resolution | Pitch | Bits |
|---|---|---|---|
| `generic_512` | 512×512 | 8 µm | 8 |
| `holoeye_pluto_2` | 1920×1080 | 8 µm | 8 |
| `thorlabs_1080p` | 1920×1080 | 6.4 µm | 8 (633 nm default) |

`--gs` turns on Gerchberg–Saxton refinement (slower, sharper far-field).

## Bench

```
laser → expander → phase-only SLM (load phase_XXXX.png)
                 → Fourier lens (f ~ 100–300 mm)
                 → camera
                 → optional helical grating / ℓ-sorter
```

**Look for:** nested donut (LG carrier) with 2–4 PWM-gated lobes that evolve across the sequence.

Do **not** upload the projector MP4 frames to the SLM. Those are incoherent RGB.

For the full Orbital Braille typehead (FastICA, Fisher–Rao fonts, HF Space) see [`vqc_proto`](https://github.com/kinaar8340/vqc_proto) `proto/SLM_QUICKSTART.md`.
