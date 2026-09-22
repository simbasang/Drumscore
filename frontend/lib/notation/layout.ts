export interface RowLayoutOptions {
  minMeasureWidth?: number;
  clefWidth?: number;
  timeSignatureWidth?: number;
  startX?: number;
}

export interface PlacedMeasure {
  index: number;
  row: number;
  col: number;
  x: number;
  width: number;
}

const DEFAULT_MIN_MEASURE_WIDTH = 120;
const DEFAULT_CLEF_WIDTH = 40;
const DEFAULT_TIME_SIGNATURE_WIDTH = 30;
const DEFAULT_START_X = 10;

// Greedy line-breaking (like word wrap): walk measures in source order,
// accumulating width into the current row, and start a new row whenever the
// next measure wouldn't fit. A measure is always placed even if it alone
// exceeds availableWidth (it just gets a row to itself), so this never loops
// or drops a measure regardless of how narrow the viewport is.
export function computeRowLayout(
  minWidths: number[],
  availableWidth: number,
  options: RowLayoutOptions = {},
): PlacedMeasure[] {
  const {
    minMeasureWidth = DEFAULT_MIN_MEASURE_WIDTH,
    clefWidth = DEFAULT_CLEF_WIDTH,
    timeSignatureWidth = DEFAULT_TIME_SIGNATURE_WIDTH,
    startX = DEFAULT_START_X,
  } = options;

  const placed: PlacedMeasure[] = [];
  let row = 0;
  let col = 0;
  let rowWidthUsed = 0;

  minWidths.forEach((minWidth, index) => {
    const isVeryFirst = index === 0;
    let isFirstInRow = col === 0;
    let width = Math.max(minWidth, minMeasureWidth) + (isFirstInRow ? clefWidth : 0) + (isVeryFirst ? timeSignatureWidth : 0);

    if (!isFirstInRow && rowWidthUsed + width > availableWidth) {
      row += 1;
      col = 0;
      rowWidthUsed = 0;
      isFirstInRow = true;
      width = Math.max(minWidth, minMeasureWidth) + clefWidth;
    }

    placed.push({ index, row, col, x: startX + rowWidthUsed, width });
    rowWidthUsed += width;
    col += 1;
  });

  return placed;
}
