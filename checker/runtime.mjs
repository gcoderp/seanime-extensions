// Seanime-compatible provider runtime for the extension checker.
//
// The globals a Seanime extension sees are defined by Seanime's Goja bindings
// (internal/goja/goja_bindings) and consumed through the same parameter list the API
// wrapper uses:
//
//   fetch, LoadDoc, Doc, console, $sleep, $getUserPreference,
//   $isOffline, $toString, CryptoJS, $scannerUtils, Buffer
//
// This module reproduces that surface in Node so a provider behaves the way it would inside
// Seanime. It is deliberately a plain function-body scope, exactly like Seanime's own
// payloadFactory, so `class Provider { ... }` at the top of code.js stays visible.

import { loadDoc, Doc } from "./lib/compat-document.mjs";
import { CryptoJS } from "./lib/compat-crypto.mjs";
import { Buffer as CompatBuffer } from "./lib/compat-buffer.mjs";
import { scannerUtils } from "./lib/compat-scanner-utils.mjs";

export const RUNTIME_VERSION = "seanime-goja-compat/1";

const GLOBALS = [
    "fetch", "LoadDoc", "Doc", "console", "$sleep", "$getUserPreference",
    "$isOffline", "$toString", "CryptoJS", "$scannerUtils", "Buffer",
];

const DEFAULT_USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

/**
 * Builds the runtime context handed to one provider.
 * Every network call is bounded by `timeoutMs`; nothing is shared between providers.
 */
export function createRuntime({ providerId, manifest, timeoutMs = 12000, log = () => {} }) {
    const logs = [];
    // Every outbound request, so the checker can tell "the site refused us" apart from
    // "the site answered but our selectors matched nothing".
    const requests = [];

    const record = (level, args) => {
        const line = args.map((a) => {
            if (typeof a === "string") return a;
            try {
                return JSON.stringify(a);
            } catch {
                return String(a);
            }
        }).join(" ");
        logs.push({ level, line });
        log(level, line);
    };

    const providerConsole = {
        log: (...a) => record("log", a),
        info: (...a) => record("info", a),
        debug: (...a) => record("debug", a),
        warn: (...a) => record("warn", a),
        error: (...a) => record("error", a),
    };

    const fetchImpl = async (input, init = {}) => {
        const url = typeof input === "string" ? input : String(input && input.url);
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        const startedAt = Date.now();
        try {
            const res = await fetch(url, {
                ...init,
                redirect: "follow",
                signal: controller.signal,
                headers: { "User-Agent": DEFAULT_USER_AGENT, ...(init.headers || {}) },
            });
            requests.push({ url, status: res.status, ms: Date.now() - startedAt });
            // Goja's fetch lets a provider read the body more than once; Node's Response does not.
            const body = await res.text();
            return {
                status: res.status,
                ok: res.ok,
                url: res.url || url,
                redirected: res.redirected,
                headers: {
                    get: (name) => res.headers.get(name),
                    has: (name) => res.headers.has(name),
                    forEach: (cb) => res.headers.forEach(cb),
                },
                text: async () => body,
                json: async () => JSON.parse(body),
                arrayBuffer: async () => new TextEncoder().encode(body).buffer,
            };
        } catch (err) {
            requests.push({
                url,
                status: 0,
                ms: Date.now() - startedAt,
                error: String(err && err.name === "AbortError" ? `timeout after ${timeoutMs}ms` : (err && err.message) || err).slice(0, 160),
            });
            throw err;
        } finally {
            clearTimeout(timer);
        }
    };

    const runtime = {
        fetch: fetchImpl,
        // Seanime binds LoadDoc(html) to a *function* only
        // (internal/goja/goja_bindings/document.go: vm.ToValue(docSelectionFunction)), so
        // providers must call it as `const $ = LoadDoc(html); $(selector)`. Returning a
        // selection object here would make the checker more permissive than Seanime.
        LoadDoc: (html) => {
            const root = loadDoc(String(html ?? ""));
            return (selector) => root.find(String(selector));
        },
        Doc,
        console: providerConsole,
        $sleep: (ms) => new Promise((resolve) => setTimeout(resolve, Math.min(Number(ms) || 0, 10000))),
        $getUserPreference: (_key, fallback) => fallback,
        $isOffline: () => false,
        $toString: (value) => (value === null || value === undefined ? "" : String(value)),
        CryptoJS,
        $scannerUtils: scannerUtils,
        Buffer: CompatBuffer,
        metadata: {
            id: providerId,
            name: manifest?.name ?? providerId,
            version: manifest?.version ?? "0.0.0",
            language: manifest?.language ?? "javascript",
        },
    };

    return { runtime, logs, requests, values: GLOBALS.map((name) => runtime[name]) };
}

/**
 * Evaluates code.js the way Seanime does and returns the Provider class.
 * The body is wrapped in a function scope whose parameters shadow the globals, so a
 * provider can never reach process, require, fs or the environment.
 */
export function loadProvider(code, runtimeValues) {
    const factory = new Function(
        ...GLOBALS,
        `"use strict";\n${code}\n;return typeof Provider === "undefined" ? null : Provider;`
    );
    const ProviderClass = factory(...runtimeValues);
    if (!ProviderClass) {
        throw new Error("payload did not define a Provider class");
    }
    return ProviderClass;
}

export const ONLINESTREAM_METHODS = ["getSettings", "search", "findEpisodes", "findEpisodeServer"];
export const TORRENT_METHODS = ["getSettings", "search", "smartSearch", "getTorrentInfoHash", "getTorrentMagnetLink"];

/** Checks the instance exposes the methods Seanime will call, and validates getSettings(). */
export function assertContract(provider, type) {
    const required = type === "anime-torrent-provider" ? TORRENT_METHODS : ONLINESTREAM_METHODS;
    const missing = required.filter((m) => typeof provider[m] !== "function");
    if (missing.length > 0) {
        throw new Error(`provider is missing ${missing.join(", ")}()`);
    }

    const settings = provider.getSettings();
    if (!settings || typeof settings !== "object") {
        throw new Error("getSettings() did not return an object");
    }
    if (type === "anime-torrent-provider") {
        if (!Array.isArray(settings.smartSearchFilters)) {
            throw new Error("getSettings().smartSearchFilters must be an array");
        }
        if (settings.type !== "main" && settings.type !== "special") {
            throw new Error(`getSettings().type must be "main" or "special", got ${JSON.stringify(settings.type)}`);
        }
    } else {
        if (!Array.isArray(settings.episodeServers)) {
            throw new Error("getSettings().episodeServers must be an array");
        }
        if (typeof settings.supportsDub !== "boolean") {
            throw new Error("getSettings().supportsDub must be a boolean");
        }
    }
    return settings;
}
