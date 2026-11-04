// Vendored from seanime-api-netlify (src/extensions/compat-buffer.js), the Seanime-compatible
// runtime shim for Cloudflare Workers. Dependency-free; adapted only to the .mjs extension
// so the extension checker can reproduce Seanime's Goja semantics in Node.
/**
 * A small `Buffer` shim.
 *
 * Several providers use Node's Buffer purely as a base64/hex codec — RareAnime
 * decodes its "JuicyCodes" payload with `Buffer.from(body, "base64")`, and its
 * own source notes that Seanime's Goja Buffer is already a limited
 * implementation. Workers have no Buffer, so this covers the surface those
 * payloads touch: from/alloc/concat/isBuffer, toString with the common
 * encodings, slice/subarray, equals, indexOf.
 */

const ENCODINGS = new Set(["utf8", "utf-8", "base64", "hex", "latin1", "binary", "ascii"]);

function normaliseEncoding(encoding) {
  const value = String(encoding ?? "utf8").toLowerCase();
  if (!ENCODINGS.has(value)) throw new Error(`Buffer shim: unsupported encoding "${encoding}"`);
  return value === "utf-8" ? "utf8" : value;
}

function bytesFromString(text, encoding) {
  switch (normaliseEncoding(encoding)) {
    case "base64": {
      const clean = String(text).replace(/[^A-Za-z0-9+/=]/g, "");
      const binary = atob(clean);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      return bytes;
    }
    case "hex": {
      const clean = String(text).replace(/[^0-9a-fA-F]/g, "");
      const bytes = new Uint8Array(Math.floor(clean.length / 2));
      for (let i = 0; i < bytes.length; i += 1) bytes[i] = Number.parseInt(clean.slice(i * 2, i * 2 + 2), 16);
      return bytes;
    }
    case "latin1":
    case "binary":
    case "ascii": {
      const bytes = new Uint8Array(String(text).length);
      for (let i = 0; i < bytes.length; i += 1) bytes[i] = String(text).charCodeAt(i) & 0xff;
      return bytes;
    }
    default:
      return new TextEncoder().encode(String(text));
  }
}

function stringFromBytes(bytes, encoding) {
  switch (normaliseEncoding(encoding)) {
    case "base64": {
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      return btoa(binary);
    }
    case "hex":
      return Array.from(bytes)
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("");
    case "latin1":
    case "binary":
    case "ascii":
      return Array.from(bytes)
        .map((byte) => String.fromCharCode(byte))
        .join("");
    default:
      return new TextDecoder().decode(bytes);
  }
}

class Buffer extends Uint8Array {
  static from(input, encoding) {
    if (typeof input === "string") return new Buffer(bytesFromString(input, encoding));
    if (input instanceof Uint8Array) return new Buffer(input);
    if (input instanceof ArrayBuffer) return new Buffer(new Uint8Array(input));
    if (Array.isArray(input)) return new Buffer(Uint8Array.from(input));
    if (input && typeof input === "object" && typeof input.length === "number") return new Buffer(Uint8Array.from(input));
    throw new Error("Buffer shim: unsupported input for Buffer.from");
  }

  static alloc(size, fill = 0) {
    const bytes = new Uint8Array(Math.max(0, Math.trunc(size) || 0));
    if (fill) bytes.fill(typeof fill === "number" ? fill : 0);
    return new Buffer(bytes);
  }

  static concat(list, totalLength) {
    const chunks = Array.from(list ?? []).map((chunk) => Buffer.from(chunk));
    const length = totalLength ?? chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const out = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      out.set(chunk, offset);
      offset += chunk.length;
    }
    return new Buffer(out);
  }

  static isBuffer(value) {
    return value instanceof Buffer || value instanceof Uint8Array;
  }

  toString(encoding, start = 0, end = this.length) {
    return stringFromBytes(this.subarray(start, end), encoding);
  }

  slice(start, end) {
    return new Buffer(this.subarray(start, end));
  }

  subarray(start, end) {
    return new Buffer(Uint8Array.prototype.subarray.call(this, start, end));
  }

  equals(other) {
    const target = Buffer.from(other);
    if (target.length !== this.length) return false;
    for (let i = 0; i < this.length; i += 1) if (this[i] !== target[i]) return false;
    return true;
  }

  indexOf(value, byteOffset = 0) {
    const needle = typeof value === "string" ? Buffer.from(value) : Buffer.from(value);
    outer: for (let i = Math.max(0, byteOffset); i <= this.length - needle.length; i += 1) {
      for (let j = 0; j < needle.length; j += 1) if (this[i + j] !== needle[j]) continue outer;
      return i;
    }
    return -1;
  }

  toJSON() {
    return { type: "Buffer", data: Array.from(this) };
  }
}

export { Buffer };
