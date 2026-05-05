function stripQuotedText(text) {
  const lines = text.split("\n");
  const result = [];
  for (const line of lines) {
    if (line.trim().startsWith(">")) continue;
    if (/^-{5,}\s*(Forwarded|Original|転送)/.test(line)) break;
    if (/^\d{4}年\d{1,2}月\d{1,2}日.*[:：]$/.test(line.trim())) break;
    if (/^On .+ wrote:$/.test(line.trim())) break;
    if (/^(送信者|From|差出人)\s*[:：]/.test(line.trim())) break;
    result.push(line);
  }
  return result.join("\n");
}

function cleanBodyForReading(body) {
  let text = body.replace(/<[^>]+>/g, "");
  text = stripQuotedText(text);
  text = text.replace(/https?:\/\/\S+/g, "");
  text = text.replace(/[ \t]+/g, " ");
  text = text.replace(/\n{3,}/g, "\n\n");
  text = text.split("\n").map(l => l.trim()).join("\n").trim();
  return text.slice(0, 500);
}

function splitIntoSentences(text) {
  return text.split(/(?<=[。．！？\n])/).map(s => s.trim()).filter(s => s.length > 0);
}

function parseSenderName(from) {
  const match = from.match(/^"?(.+?)"?\s*<.+>$/);
  return match ? match[1].trim() : from;
}

function formatDate(dateStr) {
  try {
    const d = new Date(dateStr);
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${y}年${mo}月${day}日 ${h}:${mi}`;
  } catch {
    return dateStr;
  }
}

function decodeBase64Url(data) {
  const base64 = data.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder("utf-8").decode(bytes);
}

function extractBody(payload) {
  if (payload.body && payload.body.data) {
    return decodeBase64Url(payload.body.data);
  }
  const parts = payload.parts || [];
  for (const part of parts) {
    if (part.mimeType === "text/plain" && part.body && part.body.data) {
      return decodeBase64Url(part.body.data);
    }
  }
  for (const part of parts) {
    const result = extractBody(part);
    if (result) return result;
  }
  return "";
}

function checkAttachments(payload) {
  if (payload.filename) return true;
  for (const part of payload.parts || []) {
    if (part.filename) return true;
    if (checkAttachments(part)) return true;
  }
  return false;
}
