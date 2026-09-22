import { Stave } from "vexflow";

import { computeNoteJustifyWidth } from "../staveFormatting";

describe("computeNoteJustifyWidth", () => {
  it("should keep the justified note area within the stave's own declared width, after a clef and time signature", () => {
    const staveWidth = 190;
    const stave = new Stave(10, 20, staveWidth);
    stave.addClef("percussion");
    stave.setTimeSignature("4/4");

    const justifyWidth = computeNoteJustifyWidth(stave, staveWidth, 20);

    const prefixWidth = stave.getNoteStartX() - stave.getX();
    expect(prefixWidth + justifyWidth).toBeLessThanOrEqual(staveWidth);
  });

  it("should return less width than the trailing-padding-only calculation once a clef takes real space", () => {
    const staveWidth = 190;
    const trailingPadding = 20;
    const stave = new Stave(10, 20, staveWidth);
    stave.addClef("percussion");
    stave.setTimeSignature("4/4");

    const justifyWidth = computeNoteJustifyWidth(stave, staveWidth, trailingPadding);

    expect(justifyWidth).toBeLessThan(staveWidth - trailingPadding);
  });

  it("should never return a negative width even for a very narrow stave", () => {
    const staveWidth = 10;
    const stave = new Stave(10, 20, staveWidth);
    stave.addClef("percussion");

    const justifyWidth = computeNoteJustifyWidth(stave, staveWidth, 20);

    expect(justifyWidth).toBeGreaterThanOrEqual(0);
  });
});
