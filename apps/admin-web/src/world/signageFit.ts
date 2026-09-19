/** Fits sign text into a fixed width (pure, no DOM, so it is unit-testable). Shrinks the font
 * from `maxPx` down to a readable `minPx`; if it still does not fit, truncates with an
 * ellipsis at `minPx`. `measure` is the canvas `measureText` width for a font size. */
export interface SignFit {
  text: string;
  fontPx: number;
}

const STEP_PX = 2;
const ELLIPSIS = "…";

export function fitSignText(
  text: string,
  availablePx: number,
  maxPx: number,
  minPx: number,
  measure: (text: string, fontPx: number) => number,
): SignFit {
  for (let size = maxPx; size >= minPx; size -= STEP_PX) {
    if (measure(text, size) <= availablePx) return { text, fontPx: size };
  }
  let cut = text;
  while (cut.length > 1 && measure(cut + ELLIPSIS, minPx) > availablePx) cut = cut.slice(0, -1);
  return { text: cut + ELLIPSIS, fontPx: minPx };
}
