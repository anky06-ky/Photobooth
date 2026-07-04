import { connectLambda, getStore } from "@netlify/blobs";

const DATA_STORE = "photobooth-data";
const IMAGE_STORE = "photobooth-images";
const DATA_URL_RE = /^data:image\/(?<ext>png|jpeg|jpg);base64,(?<data>.+)$/;
const DEVICE_ID_RE = /^[a-zA-Z0-9_-]{12,80}$/;

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
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  return {
    statusCode: 200,
    isBase64Encoded: true,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=31536000, immutable",
    },
    body: buffer.toString("base64"),
  };
}

function notFound() {
  return jsonResponse({ error: "Not found" }, 404);
}

function tailFromPath(path) {
  if (path.startsWith("/saved/")) {
    return path;
  }

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

function headerValue(headers, name) {
  const match = Object.entries(headers || {}).find(([key]) => key.toLowerCase() === name);
  return match ? match[1] : "";
}

function deviceIdFromEvent(event) {
  const fromHeader = headerValue(event.headers, "x-photobooth-device");
  const fromQuery = event.queryStringParameters && event.queryStringParameters.device;
  const deviceId = String(fromHeader || fromQuery || "");
  if (!DEVICE_ID_RE.test(deviceId)) {
    throw new Error("Missing or invalid device id.");
  }
  return deviceId;
}

function imageContentType(filename) {
  return filename.toLowerCase().endsWith(".jpg") || filename.toLowerCase().endsWith(".jpeg")
    ? "image/jpeg"
    : "image/png";
}

function manifestKey(deviceId) {
  return `devices/${deviceId}/photos.json`;
}

function imageKey(deviceId, filename) {
  return `devices/${deviceId}/images/${filename}`;
}

function photoUrl(filename, deviceId) {
  return `/saved/${filename}?device=${encodeURIComponent(deviceId)}`;
}

function sessionResponse(session, deviceId) {
  return {
    id: session.id,
    createdAt: session.createdAt,
    stripUrl: photoUrl(session.stripFilename, deviceId),
    stripFilename: session.stripFilename,
    shots: session.shotFilenames.map((filename) => photoUrl(filename, deviceId)),
    shotFilenames: session.shotFilenames,
  };
}

async function loadManifest(dataStore, deviceId) {
  const manifest = await dataStore.get(manifestKey(deviceId), { type: "json" });
  return manifest || { next_id: 1, sessions: [] };
}

async function saveManifest(dataStore, deviceId, manifest) {
  await dataStore.setJSON(manifestKey(deviceId), manifest);
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

async function listSessions(dataStore, deviceId) {
  const manifest = await loadManifest(dataStore, deviceId);
  return jsonResponse({
    sessions: manifest.sessions.map((session) => sessionResponse(session, deviceId)),
  });
}

async function saveSession(event, dataStore, imageStore, deviceId) {
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
    await imageStore.set(imageKey(deviceId, filename), image.bytes, {
      metadata: { contentType: imageContentType(filename) },
    });
    shotFilenames.push(filename);
  }

  const stripImage = decodeImage(strip);
  const stripFilename = `strip_${unique}.${stripImage.ext}`;
  await imageStore.set(imageKey(deviceId, stripFilename), stripImage.bytes, {
    metadata: { contentType: imageContentType(stripFilename) },
  });

  const manifest = await loadManifest(dataStore, deviceId);
  const sessionId = Number(manifest.next_id || 1);
  const session = {
    id: sessionId,
    createdAt: now.toLocaleString("vi-VN", { hour12: false }),
    stripFilename,
    shotFilenames,
  };
  manifest.next_id = sessionId + 1;
  manifest.sessions.unshift(session);
  await saveManifest(dataStore, deviceId, manifest);

  return jsonResponse(sessionResponse(session, deviceId), 201);
}

async function deleteSession(tail, dataStore, imageStore, deviceId) {
  const sessionId = Number(tail.replace("/", ""));
  if (!Number.isInteger(sessionId)) {
    return jsonResponse({ error: "Invalid id" }, 400);
  }

  const manifest = await loadManifest(dataStore, deviceId);
  const index = manifest.sessions.findIndex((session) => Number(session.id) === sessionId);
  if (index === -1) {
    return notFound();
  }

  const [session] = manifest.sessions.splice(index, 1);
  await saveManifest(dataStore, deviceId, manifest);

  for (const filename of [session.stripFilename, ...session.shotFilenames]) {
    await imageStore.delete(imageKey(deviceId, filename));
  }

  return jsonResponse({ ok: true });
}

async function sendSavedPhoto(tail, imageStore, deviceId) {
  const filename = safeFilename(tail.replace(/^\/saved\//, ""));
  const bytes = await imageStore.get(imageKey(deviceId, filename), { type: "arrayBuffer" });
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

    if (event.blobs) {
      connectLambda(event);
    }

    const dataStore = getStore(DATA_STORE);
    const imageStore = getStore(IMAGE_STORE);
    const tail = tailFromPath(event.path);

    if (event.httpMethod === "GET" && tail.startsWith("/saved/")) {
      return sendSavedPhoto(tail, imageStore, deviceIdFromEvent(event));
    }

    if (event.httpMethod === "GET" && (tail === "" || tail === "/")) {
      return listSessions(dataStore, deviceIdFromEvent(event));
    }

    if (event.httpMethod === "POST" && (tail === "" || tail === "/")) {
      return saveSession(event, dataStore, imageStore, deviceIdFromEvent(event));
    }

    if (event.httpMethod === "DELETE" && tail) {
      return deleteSession(tail, dataStore, imageStore, deviceIdFromEvent(event));
    }

    return notFound();
  } catch (error) {
    const statusCode = error.message === "Missing or invalid device id." ? 400 : 500;
    return jsonResponse({ error: error.message || "Unexpected error" }, statusCode);
  }
};
