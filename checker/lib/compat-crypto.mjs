// Vendored from seanime-api-netlify (src/extensions/compat-crypto.js), the Seanime-compatible
// runtime shim for Cloudflare Workers. Dependency-free; adapted only to the .mjs extension
// so the extension checker can reproduce Seanime's Goja semantics in Node.
/**
 * A small CryptoJS-compatible shim.
 *
 * Several Seanime providers call CryptoJS synchronously — `CryptoJS.AES.decrypt`
 * to unwrap an obfuscated player URL, `CryptoJS.enc.Base64.parse` to decode a
 * token — so Web Crypto (which is promise-based) cannot be dropped in. This
 * module implements the subset those payloads actually use, synchronously:
 *
 *   CryptoJS.enc.{Utf8,Hex,Base64,Latin1}.{parse,stringify}
 *   CryptoJS.AES.{encrypt,decrypt}          (CBC, PKCS#7, 128/192/256-bit keys)
 *   CryptoJS.lib.WordArray.create(...)
 *
 * Anything outside that throws a clear error, which the compatibility report
 * turns into a finding rather than a silent wrong answer.
 */

class WordArray {
  constructor(words, sigBytes) {
    this.words = words;
    this.sigBytes = sigBytes;
  }

  toString(encoder) {
    return (encoder ?? HexEncoder).stringify(this);
  }

  concat(other) {
    const bytes = wordArrayToBytes(this).concat(wordArrayToBytes(other));
    return bytesToWordArray(bytes);
  }

  clone() {
    return new WordArray([...this.words], this.sigBytes);
  }
}

function wordArrayToBytes(wordArray) {
  const out = new Uint8Array(wordArray.sigBytes);
  for (let i = 0; i < wordArray.sigBytes; i += 1) {
    out[i] = (wordArray.words[i >>> 2] >>> (24 - (i % 4) * 8)) & 0xff;
  }
  return out;
}

function bytesToWordArray(bytes) {
  const words = [];
  for (let i = 0; i < bytes.length; i += 1) {
    words[i >>> 2] |= bytes[i] << (24 - (i % 4) * 8);
  }
  return new WordArray(words, bytes.length);
}

const Utf8Encoder = {
  parse(text) {
    return bytesToWordArray(new TextEncoder().encode(String(text)));
  },
  stringify(wordArray) {
    return new TextDecoder().decode(wordArrayToBytes(wordArray));
  },
};

const Latin1Encoder = {
  parse(text) {
    const bytes = new Uint8Array(String(text).length);
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = String(text).charCodeAt(i) & 0xff;
    return bytesToWordArray(bytes);
  },
  stringify(wordArray) {
    return Array.from(wordArrayToBytes(wordArray))
      .map((byte) => String.fromCharCode(byte))
      .join("");
  },
};

const HexEncoder = {
  parse(hex) {
    const clean = String(hex).replace(/[^0-9a-fA-F]/g, "");
    const bytes = new Uint8Array(Math.floor(clean.length / 2));
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Number.parseInt(clean.slice(i * 2, i * 2 + 2), 16);
    return bytesToWordArray(bytes);
  },
  stringify(wordArray) {
    return Array.from(wordArrayToBytes(wordArray))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  },
};

const Base64Encoder = {
  parse(base64) {
    const clean = String(base64).replace(/[^A-Za-z0-9+/=]/g, "");
    const binary = atob(clean);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytesToWordArray(bytes);
  },
  stringify(wordArray) {
    const bytes = wordArrayToBytes(wordArray);
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  },
};

/* ------------------------------------------------------------------ AES-CBC */

const SBOX = new Uint8Array(256);
const INV_SBOX = new Uint8Array(256);
(function buildSboxes() {
  let p = 1;
  let q = 1;
  do {
    p = p ^ ((p << 1) & 0xff) ^ (p & 0x80 ? 0x1b : 0);
    q ^= q << 1;
    q ^= q << 2;
    q ^= q << 4;
    q &= 0xff;
    if (q & 0x80) q ^= 0x09;
    const x = q ^ ((q << 1) | (q >>> 7)) ^ ((q << 2) | (q >>> 6)) ^ ((q << 3) | (q >>> 5)) ^ ((q << 4) | (q >>> 4));
    SBOX[p] = (x ^ 0x63) & 0xff;
  } while (p !== 1);
  SBOX[0] = 0x63;
  for (let i = 0; i < 256; i += 1) INV_SBOX[SBOX[i]] = i;
})();

function xtime(a) {
  return ((a << 1) ^ (a & 0x80 ? 0x1b : 0)) & 0xff;
}

function mul(a, b) {
  let result = 0;
  let x = a;
  let y = b;
  while (y) {
    if (y & 1) result ^= x;
    x = xtime(x);
    y >>= 1;
  }
  return result & 0xff;
}

function expandKey(key) {
  const nk = key.length / 4;
  if (![4, 6, 8].includes(nk)) throw new Error("CryptoJS shim: AES key must be 16, 24 or 32 bytes");
  const nr = nk + 6;
  const w = new Uint8Array(16 * (nr + 1));
  w.set(key);
  let rcon = 1;
  for (let i = nk; i < 4 * (nr + 1); i += 1) {
    let temp = w.slice((i - 1) * 4, i * 4);
    if (i % nk === 0) {
      temp = new Uint8Array([SBOX[temp[1]] ^ rcon, SBOX[temp[2]], SBOX[temp[3]], SBOX[temp[0]]]);
      rcon = xtime(rcon);
    } else if (nk > 6 && i % nk === 4) {
      temp = new Uint8Array([SBOX[temp[0]], SBOX[temp[1]], SBOX[temp[2]], SBOX[temp[3]]]);
    }
    for (let j = 0; j < 4; j += 1) w[i * 4 + j] = w[(i - nk) * 4 + j] ^ temp[j];
  }
  return { roundKeys: w, rounds: nr };
}

function addRoundKey(state, roundKeys, round) {
  for (let i = 0; i < 16; i += 1) state[i] ^= roundKeys[round * 16 + i];
}

function encryptBlock(block, roundKeys, rounds) {
  const state = Uint8Array.from(block);
  addRoundKey(state, roundKeys, 0);
  for (let round = 1; round <= rounds; round += 1) {
    for (let i = 0; i < 16; i += 1) state[i] = SBOX[state[i]];
    // ShiftRows (column-major state)
    const shifted = Uint8Array.from(state);
    for (let r = 1; r < 4; r += 1) {
      for (let c = 0; c < 4; c += 1) shifted[r + 4 * c] = state[r + 4 * ((c + r) % 4)];
    }
    state.set(shifted);
    if (round !== rounds) {
      for (let c = 0; c < 4; c += 1) {
        const a0 = state[4 * c];
        const a1 = state[4 * c + 1];
        const a2 = state[4 * c + 2];
        const a3 = state[4 * c + 3];
        state[4 * c] = mul(a0, 2) ^ mul(a1, 3) ^ a2 ^ a3;
        state[4 * c + 1] = a0 ^ mul(a1, 2) ^ mul(a2, 3) ^ a3;
        state[4 * c + 2] = a0 ^ a1 ^ mul(a2, 2) ^ mul(a3, 3);
        state[4 * c + 3] = mul(a0, 3) ^ a1 ^ a2 ^ mul(a3, 2);
      }
    }
    addRoundKey(state, roundKeys, round);
  }
  return state;
}

function decryptBlock(block, roundKeys, rounds) {
  const state = Uint8Array.from(block);
  addRoundKey(state, roundKeys, rounds);
  for (let round = rounds - 1; round >= 0; round -= 1) {
    const shifted = Uint8Array.from(state);
    for (let r = 1; r < 4; r += 1) {
      for (let c = 0; c < 4; c += 1) shifted[r + 4 * ((c + r) % 4)] = state[r + 4 * c];
    }
    state.set(shifted);
    for (let i = 0; i < 16; i += 1) state[i] = INV_SBOX[state[i]];
    addRoundKey(state, roundKeys, round);
    if (round !== 0) {
      for (let c = 0; c < 4; c += 1) {
        const a0 = state[4 * c];
        const a1 = state[4 * c + 1];
        const a2 = state[4 * c + 2];
        const a3 = state[4 * c + 3];
        state[4 * c] = mul(a0, 14) ^ mul(a1, 11) ^ mul(a2, 13) ^ mul(a3, 9);
        state[4 * c + 1] = mul(a0, 9) ^ mul(a1, 14) ^ mul(a2, 11) ^ mul(a3, 13);
        state[4 * c + 2] = mul(a0, 13) ^ mul(a1, 9) ^ mul(a2, 14) ^ mul(a3, 11);
        state[4 * c + 3] = mul(a0, 11) ^ mul(a1, 13) ^ mul(a2, 9) ^ mul(a3, 14);
      }
    }
  }
  return state;
}

function toKeyBytes(value) {
  if (value instanceof WordArray) return wordArrayToBytes(value);
  if (typeof value === "string") return new TextEncoder().encode(value);
  if (value && value.sigBytes !== undefined) return wordArrayToBytes(new WordArray(value.words ?? [], value.sigBytes));
  throw new Error("CryptoJS shim: unsupported key/iv type");
}

function pkcs7Pad(bytes) {
  const pad = 16 - (bytes.length % 16);
  const out = new Uint8Array(bytes.length + pad);
  out.set(bytes);
  out.fill(pad, bytes.length);
  return out;
}

function pkcs7Unpad(bytes) {
  if (bytes.length === 0) return bytes;
  const pad = bytes[bytes.length - 1];
  if (pad < 1 || pad > 16 || pad > bytes.length) return bytes;
  return bytes.subarray(0, bytes.length - pad);
}

function aesCbcEncrypt(plainBytes, keyBytes, ivBytes) {
  const { roundKeys, rounds } = expandKey(keyBytes);
  const padded = pkcs7Pad(plainBytes);
  const out = new Uint8Array(padded.length);
  let previous = ivBytes;
  for (let offset = 0; offset < padded.length; offset += 16) {
    const block = new Uint8Array(16);
    for (let i = 0; i < 16; i += 1) block[i] = padded[offset + i] ^ previous[i];
    const encrypted = encryptBlock(block, roundKeys, rounds);
    out.set(encrypted, offset);
    previous = encrypted;
  }
  return out;
}

function aesCbcDecrypt(cipherBytes, keyBytes, ivBytes) {
  const { roundKeys, rounds } = expandKey(keyBytes);
  const out = new Uint8Array(cipherBytes.length);
  let previous = ivBytes;
  for (let offset = 0; offset < cipherBytes.length; offset += 16) {
    const block = cipherBytes.subarray(offset, offset + 16);
    const decrypted = decryptBlock(block, roundKeys, rounds);
    for (let i = 0; i < 16; i += 1) out[offset + i] = decrypted[i] ^ previous[i];
    previous = block;
  }
  return pkcs7Unpad(out);
}

const AES = {
  encrypt(message, key, cfg = {}) {
    const iv = toKeyBytes(cfg.iv ?? new WordArray([0, 0, 0, 0], 16));
    return bytesToWordArray(aesCbcEncrypt(toKeyBytes(message), toKeyBytes(key), iv));
  },
  decrypt(ciphertext, key, cfg = {}) {
    const iv = toKeyBytes(cfg.iv ?? new WordArray([0, 0, 0, 0], 16));
    return bytesToWordArray(aesCbcDecrypt(toKeyBytes(ciphertext), toKeyBytes(key), iv));
  },
};

const CryptoJS = {
  lib: { WordArray: { create: (words, sigBytes) => new WordArray(words ?? [], sigBytes ?? (words?.length ?? 0) * 4) } },
  enc: {
    Utf8: Utf8Encoder,
    Latin1: Latin1Encoder,
    Hex: HexEncoder,
    Base64: Base64Encoder,
  },
  AES,
  mode: { CBC: "CBC" },
  pad: { Pkcs7: "Pkcs7" },
};

export { CryptoJS, WordArray, wordArrayToBytes, bytesToWordArray };
