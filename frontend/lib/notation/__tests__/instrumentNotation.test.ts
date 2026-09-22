import { INSTRUMENT_NOTATION } from "../instrumentNotation";

describe("INSTRUMENT_NOTATION", () => {
  it("should map every instrument to its documented staff position and notehead", () => {
    expect(INSTRUMENT_NOTATION).toEqual({
      kick: { key: "f/4" },
      snare: { key: "c/5" },
      hihat_closed: { key: "g/5/x2" },
      hihat_open: { key: "g/5/x3" },
      crash: { key: "a/5/x3" },
      ride: { key: "f/5/x2" },
      tom_low: { key: "e/4" },
      tom_mid: { key: "a/4" },
      tom_high: { key: "d/5" },
    });
  });

  it("should give closed and open hi-hat the same pitch but a different notehead", () => {
    const closedPitch = INSTRUMENT_NOTATION.hihat_closed.key.split("/").slice(0, 2).join("/");
    const openPitch = INSTRUMENT_NOTATION.hihat_open.key.split("/").slice(0, 2).join("/");

    expect(closedPitch).toBe(openPitch);
    expect(INSTRUMENT_NOTATION.hihat_closed.key).not.toBe(INSTRUMENT_NOTATION.hihat_open.key);
  });

  it("should give crash and ride distinct noteheads or staff positions", () => {
    expect(INSTRUMENT_NOTATION.crash.key).not.toBe(INSTRUMENT_NOTATION.ride.key);
  });
});
