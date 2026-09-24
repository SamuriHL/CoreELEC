# libbluray diagnostic patches

Not applied by the build (only `../patches/` is). Kept for investigations.

To use one, copy it into `../patches/` (the `99` prefix keeps it last in the
stack), build, and remove it again before a release build.

- `libbluray-99-DIAG-bdj-background-plane-logging.patch`: logs every HAVi
  background path (configuration set, colour, displayImage, image decode
  result, render/close, native push) with the prefix `background:`. Used to
  show that John Wick 3 asks for a `background.jpg` that is not on the disc.
