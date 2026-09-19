/** Day/night tint from the local clock, as plain numbers. Every value is a continuous
 * function of the fractional hour, so nothing flickers or jumps at any minute. */
export type Rgb = readonly [number, number, number];

export interface SceneTint {
  /** 0 at night, 1 at midday. */
  daylight: number;
  sky: Rgb;
  keyColor: Rgb;
  keyIntensity: number;
  hemiSky: Rgb;
  hemiGround: Rgb;
  hemiIntensity: number;
  /** Emissive strength of lamps and monitors; brighter after dark. */
  lampGlow: number;
  windowColor: Rgb;
}

const SUNRISE_START = 5.5;
const SUNRISE_END = 8;
const SUNSET_START = 17;
const SUNSET_END = 19.5;

const SKY_DAY: Rgb = [0.72, 0.84, 0.95];
const SKY_NIGHT: Rgb = [0.06, 0.09, 0.2];
const SKY_GOLDEN: Rgb = [0.97, 0.7, 0.55];
const KEY_DAY: Rgb = [1, 0.96, 0.88];
const KEY_NIGHT: Rgb = [0.5, 0.6, 0.95];
const KEY_GOLDEN: Rgb = [1, 0.72, 0.47];
const HEMI_SKY_DAY: Rgb = [0.86, 0.92, 1];
const HEMI_SKY_NIGHT: Rgb = [0.4, 0.48, 0.8];
const HEMI_GROUND_DAY: Rgb = [0.6, 0.55, 0.5];
const HEMI_GROUND_NIGHT: Rgb = [0.2, 0.22, 0.32];
const WINDOW_DAY: Rgb = [0.78, 0.9, 1];
const WINDOW_NIGHT: Rgb = [0.08, 0.12, 0.28];

export function localHourFraction(date: Date): number {
  return date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600 + date.getMilliseconds() / 3_600_000;
}

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
  return t * t * (3 - 2 * t);
}

export function mix(a: Rgb, b: Rgb, t: number): Rgb {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

export function daylightAt(hour: number): number {
  return smoothstep(SUNRISE_START, SUNRISE_END, hour) * (1 - smoothstep(SUNSET_START, SUNSET_END, hour));
}

/** Warmth peaks while the sun is rising or setting, i.e. when daylight is halfway. */
function goldenAmount(daylight: number): number {
  return 4 * daylight * (1 - daylight);
}

export function tintAt(hour: number): SceneTint {
  const daylight = daylightAt(hour);
  const golden = goldenAmount(daylight);
  const warm = (day: Rgb, night: Rgb, glow: Rgb, amount: number): Rgb =>
    mix(mix(night, day, daylight), glow, golden * amount);

  return {
    daylight,
    sky: warm(SKY_DAY, SKY_NIGHT, SKY_GOLDEN, 0.55),
    keyColor: warm(KEY_DAY, KEY_NIGHT, KEY_GOLDEN, 0.6),
    keyIntensity: 1.4 + 1.6 * daylight,
    hemiSky: mix(HEMI_SKY_NIGHT, HEMI_SKY_DAY, daylight),
    hemiGround: mix(HEMI_GROUND_NIGHT, HEMI_GROUND_DAY, daylight),
    hemiIntensity: 1 + 0.35 * daylight,
    lampGlow: 2 - 1.6 * daylight,
    windowColor: mix(WINDOW_NIGHT, WINDOW_DAY, daylight),
  };
}
