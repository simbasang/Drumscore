import type { Stave } from "vexflow";

// The width available to Formatter.format() for a stave's notes: the
// stave's own declared width, minus whatever a clef/time-signature actually
// consumed before stave.getNoteStartX() (measured from the real Stave, not
// assumed), minus a trailing safety margin so the last note's glyph doesn't
// touch the stave's right edge. Using the stave's real noteStartX (rather
// than only subtracting a flat padding constant) matters because notes are
// positioned starting at noteStartX - a format width that ignores that
// prefix pushes the last note's rendered x past the stave's own width, which
// gets silently clipped by the SVG's default overflow:hidden (see V1-022).
export function computeNoteJustifyWidth(stave: Stave, staveWidth: number, trailingPadding: number): number {
  const prefixWidth = stave.getNoteStartX() - stave.getX();
  return Math.max(staveWidth - prefixWidth - trailingPadding, 0);
}
