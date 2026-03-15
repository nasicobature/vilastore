(() => {
  const MAX_DIMENSION = 1600;
  const JPEG_QUALITY = 0.8;
  const PNG_QUALITY = 0.9;

  const isImageFile = (file) => file && file.type && file.type.startsWith("image/");

  const loadImage = (file) =>
    new Promise((resolve, reject) => {
      if ("createImageBitmap" in window) {
        createImageBitmap(file)
          .then(resolve)
          .catch(reject);
        return;
      }
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error);
      reader.onload = () => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });

  const canvasToFile = (canvas, fileName, mimeType, quality) =>
    new Promise((resolve) => {
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            resolve(null);
            return;
          }
          resolve(new File([blob], fileName, { type: mimeType }));
        },
        mimeType,
        quality
      );
    });

  const compressImage = async (file) => {
    const image = await loadImage(file);
    const width = image.width;
    const height = image.height;
    const scale = Math.min(1, MAX_DIMENSION / Math.max(width, height));
    const targetWidth = Math.max(1, Math.round(width * scale));
    const targetHeight = Math.max(1, Math.round(height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(image, 0, 0, targetWidth, targetHeight);

    const isPng = file.type === "image/png";
    const mimeType = isPng ? "image/png" : "image/jpeg";
    const quality = isPng ? PNG_QUALITY : JPEG_QUALITY;
    const baseName = file.name.replace(/\.[^.]+$/, "");
    const newName = `${baseName}-compressed.${isPng ? "png" : "jpg"}`;

    return canvasToFile(canvas, newName, mimeType, quality);
  };

  const setInputFiles = (input, file) => {
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    input.files = dataTransfer.files;
  };

  const handleChange = async (event) => {
    const input = event.target;
    if (!input || input.dataset.processing === "true") {
      return;
    }

    const file = input.files && input.files[0];
    if (!isImageFile(file)) {
      return;
    }

    const fingerprint = `${file.name}:${file.size}`;
    if (input.dataset.lastProcessed === fingerprint) {
      return;
    }

    input.dataset.processing = "true";
    try {
      const compressed = await compressImage(file);
      if (compressed && compressed.size < file.size) {
        setInputFiles(input, compressed);
        input.dataset.lastProcessed = `${compressed.name}:${compressed.size}`;
      } else {
        input.dataset.lastProcessed = fingerprint;
      }
    } catch (err) {
      input.dataset.lastProcessed = fingerprint;
    } finally {
      input.dataset.processing = "false";
    }
  };

  const attachListeners = () => {
    document.querySelectorAll('input[type="file"]').forEach((input) => {
      input.addEventListener("change", handleChange);
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", attachListeners);
  } else {
    attachListeners();
  }
})();
