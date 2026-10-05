# libbluray diagnostic patches

Not applied by the build (only `../patches/` is). Kept for investigations.

To use one, copy it into `../patches/` (the `99` prefix keeps it last in the
stack), build, and remove it again before a release build.

- `libbluray-99-DIAG-bdj-background-plane-logging.patch`: logs every HAVi
  background path (configuration set, colour, displayImage, image decode
  result, render/close, native push) with the prefix `background:`. Used to
  show that John Wick 3 asks for a `background.jpg` that is not on the disc.
- `libbluray-99-DIAG-markdiag.patch`: logs each held BD-J item at delivery
  (`MARKDIAG deliver`) with its own clip time and the player's presented
  position (`bd_bdj_diag_presented()`, which the Kodi side must call), and
  each mark as the reader reaches it. Applies on top of patch 19. Used for
  design §15.50 (marks released at their picture). The Kodi half is not kept
  in the tree.
