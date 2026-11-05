// Vẽ mã QR cho mọi phần tử .qrbox[data-code]
document.querySelectorAll(".qrbox").forEach(el => {
  new QRCode(el, { text: el.dataset.code, width: parseInt(el.dataset.size || 128), height: parseInt(el.dataset.size || 128), correctLevel: QRCode.CorrectLevel.M });
});
