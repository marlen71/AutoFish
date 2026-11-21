# RMFish artwork

- `rmfish-logo-original.png` and `rmfish-icon-original.png` are the supplied logo and icon, retained unchanged.
- `rmfish-logo.png` is the cropped, downscaled logo used by the dark menu. The originally transparent `RM` letters are filled light so they remain legible against the dark background. The rest of the supplied design is retained.
- `rmfish.ico` is generated from the supplied square icon at multiple Windows sizes (16–256 px).

The build embeds the menu logo as `RMFish.BrandLogo.png` and embeds the icon into `RMFish.exe`. The PowerShell source launcher reads these assets from this directory. Missing or damaged artwork falls back to a text logo; it does not disable the stop controls. No network request is used to load artwork.
