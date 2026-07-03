import { getStore } from "@netlify/blobs";

const DATA_STORE = "photobooth-data";
const IMAGE_STORE = "photobooth-images";
const MANIFEST_KEY = "photos.json";
const DATA_URL_RE = /^data:image\/(?<ext>png|jpeg|jpg);base64,(?<data>.+)$/;

function jsonResponse(payload, statusCode = 200) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
    body: JSON.stringify(payload),
  };
}

function fileResponse(bytes, contentType) {
  return {
    statusCode: 200,
    isBase64Encoded: true,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=31536000, immutable",
    },
    body: Buffer.from(bytes).toString("base64"),
  };
}

function notFound() {
  return jsonResponse({ error: "Not found" }, 404);
}

function tailFromPath(path) {
  for (const marker of ["/.netlify/functions/photos", "/api/photos"]) {
    if (path.startsWith(marker)) {
      return path.slice(marker.length);
    }
  }
  return "";
}

function safeFilename(filename) {
  const clean = decodeURIComponent(filename || "").split("/").pop();
  if (!clean || !/^[a-zA-Z0-9_.-]+$/.test(clean)) {
    throw new Error("Invalid filename.");
  }
  return clean;
}

function imageContentType(filename) {
  return filename.toLowerCase().endsWith(".jpg") || filename.toLowerCase().endsWith(".jpeg")
    ? "image/jpeg"
    : "image/png";
}

function photoUrl(filename) {
  return `/saved/${filename}`;
}

function sessionResponse(session) {
  return {
    id: session.id,
    createdAt: session.createdAt,
    stripUrl: photoUrl(session.stripFilename),
    stripFilename: session.stripFilename,
    shots: session.shotFilenames.map(photoUrl),
    shotFilenames: session.shotFilenames,
  };
}

async function loadManifest(dataStore) {
  const manifest = await dataStore.get(MANIFEST_KEY, { type: "json" });
  return manifest || { next_id: 1, sessions: [] };
}

async function saveManifest(dataStore, manifest) {
  await dataStore.setJSON(MANIFEST_KEY, manifest);
}

function decodeImage(dataUrl) {
  const match = DATA_URL_RE.exec(dataUrl || "");
  if (!match) {
    throw new Error("Expected a PNG or JPG data URL.");
  }
  const ext = match.groups.ext === "jpeg" ? "jpg" : match.groups.ext;
  return {
    ext,
    bytes: Buffer.from(match.groups.data, "base64"),
  };
}

async function listSessions(dataStore) {
  const manifest = await loadManifest(dataStore);
  return jsonResponse({
    sessions: manifest.sessions.map(sessionResponse),
  });
}

async function saveSession(event, dataStore, imageStore) {
  const body = JSON.parse(event.body || "{}");
  const shots = body.shots || [];
  const strip = body.strip;

  if (shots.length !== 3) {
    return jsonResponse({ error: "A session must include exactly 3 different shots." }, 400);
  }

  const now = new Date();
  const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\..+$/, "").replace("T", "_");
  const unique = `${timestamp}_${String(now.getMilliseconds()).padStart(3, "0")}`;
  const shotFilenames = [];

  for (let index = 0; index < shots.length; index += 1) {
    const image = decodeImage(shots[index]);
    const filename = `shot_${unique}_${index + 1}.${image.ext}`;
    await imageStore.set(`images/${filename}`, image.bytes, {
      metadata: { contentType: imageContentType(filename) },
    });
    shotFilenames.push(filename);
  }

  const stripImage = decodeImage(strip);
  const stripFilename = `strip_${unique}.${stripImage.ext}`;
  await imageStore.set(`images/${stripFilename}`, stripImage.bytes, {
    metadata: { contentType: imageContentType(stripFilename) },
  });

  const manifest = await loadManifest(dataStore);
  const sessionId = Number(manifest.next_id || 1);
  const session = {
    id: sessionId,
    createdAt: now.toLocaleString("vi-VN", { hour12: false }),
    stripFilename,
    shotFilenames,
  };
  manifest.next_id = sessionId + 1;
  manifest.sessions.unshift(session);
  await saveManifest(dataStore, manifest);

  return jsonResponse(sessionResponse(session), 201);
}

async function deleteSession(tail, dataStore, imageStore) {
  const sessionId = Number(tail.replace("/", ""));
  if (!Number.isInteger(sessionId)) {
    return jsonResponse({ error: "Invalid id" }, 400);
  }

  const manifest = await loadManifest(dataStore);
  const index = manifest.sessions.findIndex((session) => Number(session.id) === sessionId);
  if (index === -1) {
    return notFound();
  }

  const [session] = manifest.sessions.splice(index, 1);
  await saveManifest(dataStore, manifest);

  for (const filename of [session.stripFilename, ...session.shotFilenames]) {
    await imageStore.delete(`images/${filename}`);
  }

  return jsonResponse({ ok: true });
}

async function sendSavedPhoto(tail, imageStore) {
  const filename = safeFilename(tail.replace(/^\/saved\//, ""));
  const bytes = await imageStore.get(`images/${filename}`, { type: "arrayBuffer" });
  if (bytes === null) {
    return notFound();
  }
  return fileResponse(bytes, imageContentType(filename));
}

export const handler = async (event) => {
  try {
    if (event.httpMethod === "OPTIONS") {
      return jsonResponse({ ok: true });
    }

    const dataStore = getStore(DATA_STORE);
    const imageStore = getStore(IMAGE_STORE);
    const tail = tailFromPath(event.path);

    if (event.httpMethod === "GET" && tail.startsWith("/saved/")) {
      return sendSavedPhoto(tail, imageStore);
    }

    if (event.httpMethod === "GET" && (tail === "" || tail === "/")) {
      return listSessions(dataStore);
    }

    if (event.httpMethod === "POST" && (tail === "" || tail === "/")) {
      return saveSession(event, dataStore, imageStore);
    }

    if (event.httpMethod === "DELETE" && tail) {
      return deleteSession(tail, dataStore, imageStore);
    }

    return notFound();
  } catch (error) {
    return jsonResponse({ error: error.message || "Unexpected error" }, 500);
  }
};
