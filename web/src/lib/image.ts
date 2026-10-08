"use client";

/** What the API stores: 256px square, under its 256KB cap. */
const SIZE = 256;
const MAX_BYTES = 256 * 1024;

function encode(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

async function decode(file: Blob): Promise<CanvasImageSource & { width: number; height: number }> {
  // createImageBitmap honours EXIF orientation, so a phone photo isn't
  // sideways; the <img> path is the fallback for browsers without it.
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      /* fall through */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Any photo the browser can open, centre-cropped to a square and shrunk to
 * 256px. WebP where the browser can encode it (Safari can't, and quietly
 * hands back a PNG instead — so the type is checked), JPEG otherwise.
 */
export async function squareAvatar(file: Blob): Promise<Blob> {
  let source;
  try {
    source = await decode(file);
  } catch {
    throw new Error("That file isn't an image this browser can open.");
  }
  const side = Math.min(source.width, source.height);
  const canvas = document.createElement("canvas");
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Couldn't process that photo.");
  // JPEG has no transparency: a transparent PNG would otherwise go black.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, SIZE, SIZE);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(
    source,
    (source.width - side) / 2,
    (source.height - side) / 2,
    side,
    side,
    0,
    0,
    SIZE,
    SIZE,
  );
  if ("close" in source && typeof source.close === "function") source.close();

  const webp = await encode(canvas, "image/webp", 0.85);
  if (webp && webp.type === "image/webp" && webp.size <= MAX_BYTES) return webp;
  for (const quality of [0.85, 0.7]) {
    const jpeg = await encode(canvas, "image/jpeg", quality);
    if (jpeg && jpeg.size <= MAX_BYTES) return jpeg;
  }
  throw new Error("Couldn't shrink that photo enough.");
}
