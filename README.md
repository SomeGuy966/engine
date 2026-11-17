# Engine

A private image enhancer for your Mac. It enlarges blurry or small images and
makes them sharper using AI models that run **entirely locally**.

---

## Quick start

1. **Double-click `Engine.app`** (in `Documents/Engine`). Your browser opens the
   Engine page. The address is `127.0.0.1`, which means "this Mac". The page
   is not on the internet.
2. **Add an image** in any of these ways:
   - drag it onto the box,
   - click the box and choose a file,
   - press **⌘V** to paste (handy right after taking a screenshot with ⌃⇧⌘4, which copies it),
   - or paste a file path (like `~/Desktop/shot.png`) and press **Use path**.
3. **Pick one or more models** and **how much bigger** (2×, 3×, 4×). The page shows the final size.
4. Press **Run** (or **⌘↩**).
5. When it's done, drag across the picture to compare **before / after**. The
   result is saved in `Engine/output/`. Use **Open in Preview**, **Show in
   Finder**, or **Copy path**. With several models, see
   [Comparing models side by side](#comparing-models-side-by-side).
6. **Quitting:** press **Quit Engine**, or just close the tab (Engine shuts
   itself down about 15 minutes later).

> Tip: drag `Engine.app` into your Dock so it's one click away.
> (Keep the app inside the `Engine` folder; the Dock icon is just a shortcut.)

---

## Which model should I use?

Times measured on this MacBook Air (M5, 16 GB), with other apps open, for a
**1440×1080 image enlarged 2×** (to 2880×2160):

| Model | Use it for | Time | Notes |
|---|---|---|---|
| **UltraSharp V2 Lite** *(default)* | Almost everything: photos, art, UI | **~10 s** | Sharp and faithful. Doesn't invent detail. |
| **UltraSharp V2** | When you want a touch more fine detail | ~2.5 min | Nearly identical to Lite, about 12× slower. |
| **SeedVR2 3B** | Photos where you want the most realistic texture | ~4 min (up to ~9 with many apps open) | A diffusion model: rebuilds texture, but **can invent details**. In testing it turned a blurry license plate into crisp, made-up digits. Laptop gets warm. |
| **UltraSharp** | Screenshots of text or UI, line art | ~25 s | Very crisp edges. Can over-sharpen blurry backgrounds. |
| **Real-ESRGAN** | Noisy or JPEG-damaged photos | ~25 s | Smoother; same model Upscayl and many free sites use. |
| **Plain resize (no AI)** | Comparison, or tiny dense text | instant | Adds nothing, invents nothing. |

Rules of thumb:

- **Not sure?** Use the default (UltraSharp V2 Lite).
- **A photo you really care about?** Try SeedVR2, then compare it with V2 Lite.
  Don't trust SeedVR2 for text, numbers, or faces you need to identify.
- **Mostly small text?** No AI can recover letters that were never captured.
  The AI models can draw *wrong* letters. Compare with "Plain resize".
- **2× is usually enough.** 4× makes huge files (a 1440×1080 image becomes 25 megapixels).
- **Can't decide?** Tick several models and compare them side by side (below).

---

## Comparing models side by side

Tick as many models as you like (at least one) and press **Run N models**.
Engine runs them one after another on the same image, then shows:

- **One panel per model, with a single shared before/after line.** Drag
  across any panel and the line moves on all of them together, so you can
  compare the same spot in every result at once. **Zoom 100%** shows real
  pixels.
- **A comparison image** saved in `Engine/output/` as
  `<name>__compare_2x.png`: the original plus every model's result in one
  labeled grid, handy to keep or share.
- **Each model's full-size result** as its own file, with Open / Show buttons.

If one model fails (for example SeedVR2 running out of memory), the others
still finish and the failure is listed under the results. With only one model
ticked, Engine works exactly as before. Total time is roughly the sum of the
models' times, so leave SeedVR2 out for quick comparisons.

---

## Using it from Terminal (optional)

```bash
cd ~/Documents/Engine
./enhance ~/Desktop/shot.png                        # default model (V2 Lite), 2x
./enhance ~/Desktop/shot.png -m seedvr2 -s 2 --open # pick model + scale, open result
./enhance ~/Desktop/*.png -m ultrasharp             # several images, one after another
./enhance ~/Desktop/shot.png -m ultrasharp-v2-lite,realesrgan,plain-resize   # compare models
./enhance --list                                    # show all models
```

It prints the path of each result (and of the comparison image when you give
several models). `-o FOLDER` saves somewhere other than `Engine/output`.

---

## Switching and adding models ("changing outfits")

Engine is split in two:

- **The body (never changes):** the `engine/` folder. It opens the image,
  hands it to a model, resizes to the exact size you asked for, and saves it.
- **The outfits (swap freely):** one small **card** file per model in
  `models/`, e.g. `models/ultrasharp.toml`. The card says which model file to
  use and which **backend** runs it.

There are three backends ("body types"), and between them they cover hundreds of models:

| Backend | Runs |
|---|---|
| `spandrel` | Almost any classic upscale model: ESRGAN, Real-ESRGAN, UltraSharp, SwinIR, HAT, DAT, RealPLKSR, SPAN, and more. Thousands are on [OpenModelDB](https://openmodeldb.info). |
| `seedvr2` | SeedVR2 diffusion models (3B and 7B, all precisions). |
| `resize` | Plain Lanczos / bicubic / nearest resizing. |

**Switch models:** pick one in the app, or pass `-m <id>` in Terminal. Nothing else changes.

**Add a model, the 10-second way:** download a `.pth` or `.safetensors` file
(e.g. from OpenModelDB) into `models/weights/`. It shows up in the app
automatically (refresh the page).

**Add a model, the tidy way:** copy a card and edit it. For example,
`models/my-model.toml`:

```toml
name = "My Model"                     # name shown in the app
backend = "spandrel"                  # spandrel | seedvr2 | resize
weights = "4x-MyModel.safetensors"    # file inside models/weights/
best_for = "What it's good at"        # one line shown under the name
speed = "fast"                        # little tag next to the name
default_scale = 2
max_scale = 4
order = 50                            # position in the list (lower = higher)

[options]
tile = 512      # spandrel: tile size in pixels (lower it if you run out of memory)
overlap = 32
half = false    # spandrel: half precision (faster on some models)

[[files]]       # optional: lets ./setup.sh download and verify it for you
path = "4x-MyModel.safetensors"
url = "https://.../4x-MyModel.safetensors"
sha256 = "..."
```

**Change the default model:** put `default = true` in exactly one card (and remove it from the others).

**Remove a model:** delete its card (and its file in `models/weights/` to free space).

**Download missing files later:** `./setup.sh` (or `.venv/bin/python -m engine.download <id>`).
Every download is checked against the `sha256` in its card.

**Add a whole new kind of model (rare):** write a backend in
`engine/backends/` with three methods: `load`, `upscale`, `unload` (see
`engine/backends/base.py`). Then add one line to `engine/backends/__init__.py`.
The rest of Engine doesn't change.

---

## Privacy

- **Nothing leaves your computer.** Images are processed by models stored in `models/weights/`.
- The app's server only listens on `127.0.0.1`: other computers, even on the
  same Wi-Fi, can't reach it. Each session also uses a secret key, so other
  websites open in your browser can't talk to it.
- No analytics or tracking. The page loads no outside fonts or scripts, and
  the models run in offline mode.
- **Your images live in two folders:** `uploads/` (copies of images you
  dragged or pasted in) and `output/` (results). Delete their contents any
  time. Neither folder is ever put on GitHub (see `.gitignore`).
- Only `./setup.sh` uses the internet, to download the code and model files.

---

## Performance, memory, and heat

Measured on this Mac (M5 MacBook Air, 16 GB):

- **Classic models** (V2 Lite, UltraSharp, Real-ESRGAN) use about 1-2 GB of
  memory and finish in seconds. The laptop barely warms up.
- **UltraSharp V2** uses about 2 GB and takes a couple of minutes. It processes
  the image in 256-pixel tiles: bigger tiles made it run out of memory and
  crawl.
- **SeedVR2 3B** uses about 9 GB and keeps the GPU busy for several minutes.
  It works, but close memory-hungry apps first. With lots of apps open, macOS
  has to swap and it gets slower.

- Only one image runs at a time. Only one model stays in memory, and it's
  released after 5 idle minutes.
- SeedVR2 runs as a separate process, so all of its memory goes back to macOS the moment it finishes.
- A fanless MacBook Air slows itself down when hot. It can't overheat or damage
  itself. For SeedVR2, close heavy apps (lots of browser tabs) and don't run it
  on a blanket.

---

## Install on another Mac / reinstall

```bash
git clone https://github.com/SomeGuy966/engine.git ~/Documents/Engine
cd ~/Documents/Engine
./setup.sh                      # Python env + SeedVR2 runner + ~7.6 GB of models
./setup.sh --skip seedvr2-3b    # same, without the big SeedVR2 download
```

Needs macOS on Apple Silicon and Python 3.12 or 3.13 (`brew install python@3.12`).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Double-clicking Engine.app does nothing | Open `http://127.0.0.1:7861` in your browser. If that fails, read `logs/engine.log`. |
| "Model is missing" | Run `./setup.sh`. |
| SeedVR2 fails or the Mac gets very slow | Use 2×, close other apps, or lower `max_output_megapixels` in `models/seedvr2-3b.toml` (e.g. to 6). |
| A classic model runs out of memory | Lower `tile` in its card (e.g. 256). |
| Engine seems stuck | In Terminal: `pkill -f engine.server`, then open Engine.app again. |
| A card has a typo | The app shows "Model card problems" at the top. Fix the file and refresh. |

---

## What's in this folder

```
Engine/
├── Engine.app            double-click to start
├── enhance               Terminal version
├── setup.sh              installs / repairs everything
├── README.md             this file
├── requirements.txt      exact Python library versions
├── engine/               the core (the "body")
│   ├── core.py           open → upscale → resize → save (one model or several)
│   ├── compare.py        builds the side-by-side comparison image
│   ├── cards.py          reads the model cards
│   ├── server.py         the local app
│   ├── cli.py            the Terminal command
│   ├── download.py       downloads + verifies model files
│   ├── web/index.html    the app page
│   └── backends/         spandrel_backend.py, seedvr2.py, resize.py
├── models/               the cards (the "outfits")
│   └── weights/          the model files themselves (big; not in git)
├── vendor/SeedVR2/       SeedVR2's official runner (installed by setup.sh)
├── output/               your results
└── uploads/              copies of images you dropped in
```

## Credits and licenses

- **UltraSharp / UltraSharp V2** by Kim2091: CC BY-NC-SA 4.0 (personal, non-commercial use).
- **Real-ESRGAN** by Xintao Wang et al.: BSD-3-Clause.
- **SeedVR2** by ByteDance Seed; runner by numz / AInVFX: Apache-2.0.
- **Spandrel** by chaiNNer-org: MIT.
