/** Downscale an image blob so previews load quickly, especially on mobile.
 *
 * Only the in-memory preview is compressed — the original document is never
 * changed, so text used for OCR stays intact.
 */
export async function compressedImageDataUrl(
  blob: Blob,
  maxDimension = 1600,
  quality = 0.82,
): Promise<string> {
  const objectUrl = URL.createObjectURL(blob);
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("Could not decode the image."));
      image.src = objectUrl;
    });

    const scale = Math.min(
      1,
      maxDimension / Math.max(image.naturalWidth || 1, image.naturalHeight || 1),
    );
    const width = Math.max(1, Math.round((image.naturalWidth || 1) * scale));
    const height = Math.max(1, Math.round((image.naturalHeight || 1) * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas is not available.");
    ctx.drawImage(image, 0, 0, width, height);

    // PNG keeps transparency; everything else is stored as a compact JPEG.
    const type = blob.type === "image/png" ? "image/png" : "image/jpeg";
    return canvas.toDataURL(type, quality);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
