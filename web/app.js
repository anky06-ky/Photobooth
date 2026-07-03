const SHOT_COUNT = 3;
const PHOTO_SIZE = 720;
const BOARD_SIZE = 540;
const GRID = 3;

const camera = document.getElementById("camera");
const previewCanvas = document.getElementById("previewCanvas");
const puzzleCanvas = document.getElementById("puzzleCanvas");
const startCameraBtn = document.getElementById("startCameraBtn");
const captureBtn = document.getElementById("captureBtn");
const captureIndex = document.getElementById("captureIndex");
const retakeBtn = document.getElementById("retakeBtn");
const shuffleBtn = document.getElementById("shuffleBtn");
const acceptBtn = document.getElementById("acceptBtn");
const saveBtn = document.getElementById("saveBtn");
const refreshBtn = document.getElementById("refreshBtn");
const statusText = document.getElementById("statusText");
const progressText = document.getElementById("progressText");
const shotList = document.getElementById("shotList");
const gallery = document.getElementById("gallery");

const previewCtx = previewCanvas.getContext("2d");
const puzzleCtx = puzzleCanvas.getContext("2d");

let stream = null;
let currentPhoto = null;
let puzzleImage = null;
let pieces = [];
let dragPiece = null;
let dragOffset = { x: 0, y: 0 };
let solved = false;
let acceptedShots = [];

function setStatus(text) {
  statusText.textContent = text;
}

function updateProgress() {
  progressText.textContent = `${acceptedShots.length}/${SHOT_COUNT}`;
  captureIndex.textContent = Math.min(acceptedShots.length + 1, SHOT_COUNT);
  saveBtn.disabled = acceptedShots.length !== SHOT_COUNT;
  renderShotSlots();
}

function renderShotSlots() {
  shotList.innerHTML = "";
  for (let index = 0; index < SHOT_COUNT; index += 1) {
    const slot = document.createElement("div");
    slot.className = "shot-slot";
    if (acceptedShots[index]) {
      const img = document.createElement("img");
      img.src = acceptedShots[index].dataUrl;
      img.alt = `Shot ${index + 1}`;
      slot.appendChild(img);
    }
    const label = document.createElement("span");
    label.textContent = `${index + 1}`;
    slot.appendChild(label);
    shotList.appendChild(slot);
  }
}

function drawEmptyPuzzle(message = "Chup anh de bat dau ghep") {
  puzzleCtx.fillStyle = "#0b0e0f";
  puzzleCtx.fillRect(0, 0, BOARD_SIZE, BOARD_SIZE);
  puzzleCtx.strokeStyle = "#303838";
  puzzleCtx.lineWidth = 2;
  for (let i = 1; i < GRID; i += 1) {
    const pos = (BOARD_SIZE / GRID) * i;
    puzzleCtx.beginPath();
    puzzleCtx.moveTo(pos, 0);
    puzzleCtx.lineTo(pos, BOARD_SIZE);
    puzzleCtx.moveTo(0, pos);
    puzzleCtx.lineTo(BOARD_SIZE, pos);
    puzzleCtx.stroke();
  }
  puzzleCtx.fillStyle = "#aeb9b7";
  puzzleCtx.font = "700 20px system-ui, sans-serif";
  puzzleCtx.textAlign = "center";
  puzzleCtx.fillText(message, BOARD_SIZE / 2, BOARD_SIZE / 2);
}

async function startCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: "user",
      },
      audio: false,
    });
    camera.srcObject = stream;
    captureBtn.disabled = false;
    startCameraBtn.disabled = true;
    setStatus(`San sang chup tam ${acceptedShots.length + 1}/3`);
  } catch (error) {
    setStatus("Khong mo duoc camera");
    console.error(error);
  }
}

function capturePhoto() {
  if (!stream || acceptedShots.length >= SHOT_COUNT) {
    return;
  }

  const videoWidth = camera.videoWidth || 1280;
  const videoHeight = camera.videoHeight || 720;
  const side = Math.min(videoWidth, videoHeight);
  const sx = Math.floor((videoWidth - side) / 2);
  const sy = Math.floor((videoHeight - side) / 2);

  previewCtx.save();
  previewCtx.clearRect(0, 0, PHOTO_SIZE, PHOTO_SIZE);
  previewCtx.translate(PHOTO_SIZE, 0);
  previewCtx.scale(-1, 1);
  previewCtx.drawImage(camera, sx, sy, side, side, 0, 0, PHOTO_SIZE, PHOTO_SIZE);
  previewCtx.restore();

  currentPhoto = previewCanvas.toDataURL("image/png");
  createPuzzle(currentPhoto);
  captureBtn.disabled = true;
  retakeBtn.disabled = false;
  setStatus(`Dang ghep tam ${acceptedShots.length + 1}/3`);
}

function retakePhoto() {
  currentPhoto = null;
  puzzleImage = null;
  pieces = [];
  dragPiece = null;
  solved = false;
  captureBtn.disabled = !stream || acceptedShots.length >= SHOT_COUNT;
  retakeBtn.disabled = true;
  shuffleBtn.disabled = true;
  acceptBtn.disabled = true;
  drawEmptyPuzzle("Chup lai tam nay");
  setStatus(`San sang chup tam ${acceptedShots.length + 1}/3`);
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = dataUrl;
  });
}

async function createPuzzle(dataUrl) {
  puzzleImage = await loadImage(dataUrl);
  solved = false;
  pieces = [];
  buildPieces();
  shufflePieces();
  shuffleBtn.disabled = false;
  acceptBtn.disabled = true;
  drawPuzzle();
}

function buildPieces() {
  const tile = BOARD_SIZE / GRID;
  for (let slot = 0; slot < GRID * GRID; slot += 1) {
    const col = slot % GRID;
    const row = Math.floor(slot / GRID);
    pieces.push({
      correctSlot: slot,
      slot,
      sx: col * (PHOTO_SIZE / GRID),
      sy: row * (PHOTO_SIZE / GRID),
      x: col * tile,
      y: row * tile,
    });
  }
}

function shufflePieces() {
  if (!pieces.length) {
    return;
  }
  const slots = pieces.map((piece) => piece.correctSlot);
  do {
    for (let i = slots.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [slots[i], slots[j]] = [slots[j], slots[i]];
    }
  } while (slots.every((slot, index) => slot === index));

  pieces.forEach((piece, index) => {
    movePieceToSlot(piece, slots[index]);
  });
  solved = false;
  acceptBtn.disabled = true;
  setStatus(`Dang ghep tam ${acceptedShots.length + 1}/3`);
  drawPuzzle();
}

function movePieceToSlot(piece, slot) {
  const tile = BOARD_SIZE / GRID;
  piece.slot = slot;
  piece.x = (slot % GRID) * tile;
  piece.y = Math.floor(slot / GRID) * tile;
}

function drawPuzzle() {
  if (!puzzleImage) {
    drawEmptyPuzzle();
    return;
  }

  const tile = BOARD_SIZE / GRID;
  const sourceTile = PHOTO_SIZE / GRID;
  puzzleCtx.fillStyle = "#0b0e0f";
  puzzleCtx.fillRect(0, 0, BOARD_SIZE, BOARD_SIZE);

  const orderedPieces = pieces.filter((piece) => piece !== dragPiece);
  if (dragPiece) {
    orderedPieces.push(dragPiece);
  }

  for (const piece of orderedPieces) {
    puzzleCtx.drawImage(
      puzzleImage,
      piece.sx,
      piece.sy,
      sourceTile,
      sourceTile,
      piece.x,
      piece.y,
      tile,
      tile
    );
    puzzleCtx.strokeStyle = piece.slot === piece.correctSlot ? "#7cc96f" : "#f4f0e8";
    puzzleCtx.lineWidth = 3;
    puzzleCtx.strokeRect(piece.x + 1, piece.y + 1, tile - 2, tile - 2);
  }

  if (solved) {
    puzzleCtx.fillStyle = "rgba(124, 201, 111, 0.9)";
    puzzleCtx.fillRect(0, 0, BOARD_SIZE, 44);
    puzzleCtx.fillStyle = "#07150d";
    puzzleCtx.font = "800 18px system-ui, sans-serif";
    puzzleCtx.textAlign = "center";
    puzzleCtx.fillText("Da ghep xong - nhan tam nay", BOARD_SIZE / 2, 29);
  }
}

function canvasPoint(event) {
  const rect = puzzleCanvas.getBoundingClientRect();
  const scaleX = BOARD_SIZE / rect.width;
  const scaleY = BOARD_SIZE / rect.height;
  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  };
}

function pieceAt(point) {
  const tile = BOARD_SIZE / GRID;
  for (let i = pieces.length - 1; i >= 0; i -= 1) {
    const piece = pieces[i];
    if (point.x >= piece.x && point.x <= piece.x + tile && point.y >= piece.y && point.y <= piece.y + tile) {
      return piece;
    }
  }
  return null;
}

function startDrag(event) {
  if (!pieces.length || solved) {
    return;
  }
  const point = canvasPoint(event);
  const piece = pieceAt(point);
  if (!piece) {
    return;
  }
  dragPiece = piece;
  dragOffset = { x: point.x - piece.x, y: point.y - piece.y };
  puzzleCanvas.setPointerCapture(event.pointerId);
}

function moveDrag(event) {
  if (!dragPiece) {
    return;
  }
  const tile = BOARD_SIZE / GRID;
  const point = canvasPoint(event);
  dragPiece.x = Math.max(0, Math.min(BOARD_SIZE - tile, point.x - dragOffset.x));
  dragPiece.y = Math.max(0, Math.min(BOARD_SIZE - tile, point.y - dragOffset.y));
  drawPuzzle();
}

function endDrag(event) {
  if (!dragPiece) {
    return;
  }
  const tile = BOARD_SIZE / GRID;
  const center = { x: dragPiece.x + tile / 2, y: dragPiece.y + tile / 2 };
  const col = Math.max(0, Math.min(GRID - 1, Math.floor(center.x / tile)));
  const row = Math.max(0, Math.min(GRID - 1, Math.floor(center.y / tile)));
  const targetSlot = row * GRID + col;
  const occupant = pieces.find((piece) => piece !== dragPiece && piece.slot === targetSlot);
  const previousSlot = dragPiece.slot;
  if (occupant) {
    movePieceToSlot(occupant, previousSlot);
  }
  movePieceToSlot(dragPiece, targetSlot);
  dragPiece = null;
  puzzleCanvas.releasePointerCapture(event.pointerId);
  checkSolved();
  drawPuzzle();
}

function checkSolved() {
  solved = pieces.length > 0 && pieces.every((piece) => piece.slot === piece.correctSlot);
  acceptBtn.disabled = !solved;
  if (solved) {
    setStatus(`Tam ${acceptedShots.length + 1}/3 da ghep xong`);
  }
}

function makePhotoCard(dataUrl, shotNumber) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = 270;
  canvas.height = 360;
  ctx.fillStyle = "#f2eadc";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  return loadImage(dataUrl).then((image) => {
    ctx.drawImage(image, 20, 20, 230, 230);
    ctx.fillStyle = "#181513";
    ctx.font = "700 22px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("PUZZLE-CAM", canvas.width / 2, 305);
    ctx.font = "600 15px system-ui, sans-serif";
    ctx.fillText(`Tam ${shotNumber}/3 - ${new Date().toLocaleTimeString()}`, canvas.width / 2, 332);
    return canvas.toDataURL("image/png");
  });
}

async function acceptCurrentShot() {
  if (!solved || !currentPhoto || acceptedShots.length >= SHOT_COUNT) {
    return;
  }

  const shotNumber = acceptedShots.length + 1;
  const dataUrl = await makePhotoCard(currentPhoto, shotNumber);
  acceptedShots.push({ dataUrl, capturedAt: new Date().toISOString() });
  updateProgress();

  currentPhoto = null;
  puzzleImage = null;
  pieces = [];
  dragPiece = null;
  solved = false;
  retakeBtn.disabled = true;
  shuffleBtn.disabled = true;
  acceptBtn.disabled = true;

  if (acceptedShots.length < SHOT_COUNT) {
    captureBtn.disabled = !stream;
    drawEmptyPuzzle(`Chup tam ${acceptedShots.length + 1}/3`);
    setStatus(`San sang chup tam ${acceptedShots.length + 1}/3`);
    return;
  }

  captureBtn.disabled = true;
  drawEmptyPuzzle("Du 3 tam - bam luu strip");
  setStatus("Du 3 tam, san sang luu");
}

async function makeStrip() {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = 300;
  canvas.height = SHOT_COUNT * 380 + 20;
  ctx.fillStyle = "#f2eadc";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (let i = 0; i < acceptedShots.length; i += 1) {
    const image = await loadImage(acceptedShots[i].dataUrl);
    ctx.drawImage(image, 15, 10 + i * 380, 270, 360);
  }
  return canvas.toDataURL("image/png");
}

async function saveSession() {
  if (acceptedShots.length !== SHOT_COUNT) {
    return;
  }

  saveBtn.disabled = true;
  setStatus("Dang luu vao database");
  try {
    const strip = await makeStrip();
    const response = await fetch("/api/photos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        shots: acceptedShots.map((shot) => shot.dataUrl),
        strip,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Save failed");
    }

    acceptedShots = [];
    updateProgress();
    captureBtn.disabled = !stream;
    drawEmptyPuzzle("Da luu - chup bo moi");
    setStatus("Da luu strip vao database");
    await loadGallery();
  } catch (error) {
    console.error(error);
    setStatus("Luu that bai");
    saveBtn.disabled = false;
  }
}

async function loadGallery() {
  const response = await fetch("/api/photos");
  const payload = await response.json();
  const sessions = payload.sessions || [];
  gallery.innerHTML = "";
  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Chua co strip nao duoc luu.";
    gallery.appendChild(empty);
    return;
  }

  for (const session of sessions) {
    const item = document.createElement("article");
    item.className = "gallery-item";

    const img = document.createElement("img");
    img.src = session.stripUrl;
    img.alt = `Strip ${session.id}`;
    item.appendChild(img);

    const meta = document.createElement("div");
    meta.className = "gallery-meta";

    const time = document.createElement("time");
    time.textContent = session.createdAt;
    meta.appendChild(time);

    const actions = document.createElement("div");
    actions.className = "gallery-actions";

    const download = document.createElement("a");
    download.href = session.stripUrl;
    download.download = session.stripFilename;
    download.textContent = "Tai PNG";
    actions.appendChild(download);

    const del = document.createElement("button");
    del.type = "button";
    del.className = "delete-btn";
    del.textContent = "Xoa";
    del.addEventListener("click", () => deleteSession(session.id));
    actions.appendChild(del);

    meta.appendChild(actions);
    item.appendChild(meta);
    gallery.appendChild(item);
  }
}

async function deleteSession(id) {
  const response = await fetch(`/api/photos/${id}`, { method: "DELETE" });
  if (response.ok) {
    await loadGallery();
    setStatus("Da xoa strip");
  } else {
    setStatus("Xoa that bai");
  }
}

startCameraBtn.addEventListener("click", startCamera);
captureBtn.addEventListener("click", capturePhoto);
retakeBtn.addEventListener("click", retakePhoto);
shuffleBtn.addEventListener("click", shufflePieces);
acceptBtn.addEventListener("click", acceptCurrentShot);
saveBtn.addEventListener("click", saveSession);
refreshBtn.addEventListener("click", loadGallery);
puzzleCanvas.addEventListener("pointerdown", startDrag);
puzzleCanvas.addEventListener("pointermove", moveDrag);
puzzleCanvas.addEventListener("pointerup", endDrag);
puzzleCanvas.addEventListener("pointercancel", endDrag);

drawEmptyPuzzle();
updateProgress();
loadGallery();
