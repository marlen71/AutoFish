# RMFish artwork

- `rmfish-logo-original.png` and `rmfish-icon-original.png` are the supplied logo and icon, retained unchanged.
- `rmfish-logo.png` is the cropped, downscaled logo used by the dark menu. The originally transparent `RM` letters are filled light so they remain legible against the dark background. The rest of the supplied design is retained.
- `rmfish.ico` is generated from the supplied square icon at multiple Windows sizes (16–256 px), using 32-bit DIB frames with transparency masks for reliable Windows and .NET icon loading.

The build embeds the menu logo as `RMFish.BrandLogo.png` and embeds the icon into `RMFish.exe`. The PowerShell source launcher reads these assets from this directory. Missing or damaged artwork falls back to a text logo; it does not disable the stop controls. No network request is used to load artwork.

- `rmacro-city.png` is the historical backdrop for the RMacro beta; Eternal Core no longer embeds it.
- `eternal-core-original.png` is the logo supplied by the owner. `eternal-core-logo.png` is its unchanged copy for the loader and website; `eternal-core-icon.png` is a crop of the mark on a dark square. `eternal-core.ico` contains 32-bit DIB frames at 16–256 px for Windows. The website carries copies of the logo, mark and favicon in its static directory, so neither UI requests external artwork.
- `Build-RMacro.ps1` defines `ETERNAL_CORE` to give the loader and its embedded RMFish window the cyan/violet theme; the standalone RMFish build retains its original palette and art.
