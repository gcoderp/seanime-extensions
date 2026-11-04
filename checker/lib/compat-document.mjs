// Vendored from seanime-api-netlify (src/extensions/compat-document.js), the Seanime-compatible
// runtime shim for Cloudflare Workers. Dependency-free; adapted only to the .mjs extension
// so the extension checker can reproduce Seanime's Goja semantics in Node.
/**
 * A deliberately small, synchronous DOM + jQuery-like selection adapter.
 *
 * Seanime's LoadDoc() is Goquery-backed: extension code calls
 * LoadDoc(html).find(".selector").text() synchronously. Cloudflare's
 * HTMLRewriter is a streaming transform API and cannot reproduce that, so this
 * module provides the subset of the interface providers actually use and
 * throws a clear error for anything outside it. Unsupported selectors are a
 * compatibility failure, never a silent empty result.
 */

const VOID_ELEMENTS = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr",
]);

const RAW_TEXT_ELEMENTS = new Set(["script", "style", "textarea", "title"]);

const NAMED_ENTITIES = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0",
  ndash: "–", mdash: "—", hellip: "…", rsquo: "’", lsquo: "‘",
  rdquo: "”", ldquo: "“",
};

export function decodeEntities(value) {
  return String(value).replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, entity) => {
    if (entity.startsWith("#x") || entity.startsWith("#X")) {
      const code = Number.parseInt(entity.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    if (entity.startsWith("#")) {
      const code = Number.parseInt(entity.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    const named = NAMED_ENTITIES[entity.toLowerCase()];
    return named === undefined ? match : named;
  });
}

function textNode(text, parent) {
  return { type: "text", text, parent };
}

function elementNode(tagName, attributes, parent) {
  return { type: "element", tagName, attributes, children: [], parent };
}

/**
 * Parses HTML into a lightweight node tree. Tolerant of unclosed tags: an end
 * tag pops to the nearest matching open element.
 */
export function parseHtml(html) {
  const source = String(html ?? "");
  const lower = source.toLowerCase();
  const root = { type: "root", tagName: "#document", attributes: {}, children: [], parent: null };
  const stack = [root];
  let i = 0;

  const appendText = (text) => {
    if (!text) return;
    stack[stack.length - 1].children.push(textNode(decodeEntities(text), stack[stack.length - 1]));
  };

  while (i < source.length) {
    const lt = source.indexOf("<", i);
    if (lt === -1) {
      appendText(source.slice(i));
      break;
    }
    if (lt > i) appendText(source.slice(i, lt));

    if (source.startsWith("<!--", lt)) {
      const end = source.indexOf("-->", lt + 4);
      i = end === -1 ? source.length : end + 3;
      continue;
    }
    if (source[lt + 1] === "!" || source[lt + 1] === "?") {
      const end = source.indexOf(">", lt);
      i = end === -1 ? source.length : end + 1;
      continue;
    }
    if (source[lt + 1] === "/") {
      const end = source.indexOf(">", lt);
      const tag = source.slice(lt + 2, end === -1 ? source.length : end).trim().toLowerCase();
      for (let k = stack.length - 1; k > 0; k -= 1) {
        if (stack[k].tagName === tag) {
          stack.length = k;
          break;
        }
      }
      i = end === -1 ? source.length : end + 1;
      continue;
    }

    let j = lt + 1;
    let tagName = "";
    while (j < source.length && /[A-Za-z0-9:-]/.test(source[j])) {
      tagName += source[j];
      j += 1;
    }
    if (!tagName) {
      appendText("<");
      i = lt + 1;
      continue;
    }
    tagName = tagName.toLowerCase();

    const attributes = {};
    let selfClosing = false;
    while (j < source.length) {
      while (j < source.length && /\s/.test(source[j])) j += 1;
      if (j >= source.length) break;
      if (source[j] === ">") {
        j += 1;
        break;
      }
      if (source[j] === "/" && source[j + 1] === ">") {
        selfClosing = true;
        j += 2;
        break;
      }
      if (source[j] === "/") {
        j += 1;
        continue;
      }
      let name = "";
      while (j < source.length && !/[\s=>/]/.test(source[j])) {
        name += source[j];
        j += 1;
      }
      while (j < source.length && /\s/.test(source[j])) j += 1;
      let value = "";
      if (source[j] === "=") {
        j += 1;
        while (j < source.length && /\s/.test(source[j])) j += 1;
        const quote = source[j];
        if (quote === '"' || quote === "'") {
          j += 1;
          const end = source.indexOf(quote, j);
          value = source.slice(j, end === -1 ? source.length : end);
          j = end === -1 ? source.length : end + 1;
        } else {
          while (j < source.length && !/[\s>]/.test(source[j])) {
            value += source[j];
            j += 1;
          }
        }
      }
      if (name) attributes[name.toLowerCase()] = decodeEntities(value);
    }

    const parent = stack[stack.length - 1];
    const node = elementNode(tagName, attributes, parent);
    parent.children.push(node);

    if (RAW_TEXT_ELEMENTS.has(tagName) && !selfClosing) {
      const closeIndex = lower.indexOf(`</${tagName}`, j);
      const end = closeIndex === -1 ? source.length : closeIndex;
      if (end > j) node.children.push(textNode(source.slice(j, end), node));
      const gt = closeIndex === -1 ? source.length : source.indexOf(">", closeIndex);
      j = gt === -1 ? source.length : gt + 1;
    } else if (!VOID_ELEMENTS.has(tagName) && !selfClosing) {
      stack.push(node);
    }
    i = j;
  }

  return root;
}

/* ------------------------------------------------------------------ selectors */

const SUPPORTED_PSEUDOS = new Set([
  "first-child",
  "last-child",
  "nth-child",
  "first-of-type",
  "last-of-type",
  "only-child",
  "empty",
  "root",
  "not",
  "has",
  "contains",
]);

function parseCompound(raw) {
  const compound = { tag: null, id: null, classes: [], attributes: [], pseudos: [] };
  let i = 0;
  const source = raw;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "*") {
      i += 1;
      continue;
    }
    if (ch === ".") {
      i += 1;
      let value = "";
      while (i < source.length && /[A-Za-z0-9_-]/.test(source[i])) {
        value += source[i];
        i += 1;
      }
      if (!value) throw new Error(`Unsupported selector: empty class in "${raw}"`);
      compound.classes.push(value);
      continue;
    }
    if (ch === "#") {
      i += 1;
      let value = "";
      while (i < source.length && /[A-Za-z0-9_-]/.test(source[i])) {
        value += source[i];
        i += 1;
      }
      if (!value) throw new Error(`Unsupported selector: empty id in "${raw}"`);
      compound.id = value;
      continue;
    }
    if (ch === "[") {
      const end = source.indexOf("]", i);
      if (end === -1) throw new Error(`Unsupported selector: unterminated attribute in "${raw}"`);
      const body = source.slice(i + 1, end).trim();
      const match = body.match(/^([A-Za-z0-9_:-]+)\s*(?:([~^$*|]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]]*)))?$/);
      if (!match) throw new Error(`Unsupported selector: attribute "${body}" in "${raw}"`);
      compound.attributes.push({
        name: match[1].toLowerCase(),
        operator: match[2] ?? null,
        value: match[3] ?? match[4] ?? match[5] ?? null,
      });
      i = end + 1;
      continue;
    }
    if (ch === ":") {
      i += 1;
      let value = "";
      while (i < source.length && /[A-Za-z-]/.test(source[i])) {
        value += source[i];
        i += 1;
      }
      let argument = null;
      if (source[i] === "(") {
        const end = source.indexOf(")", i);
        if (end === -1) throw new Error(`Unsupported selector: unterminated pseudo in "${raw}"`);
        argument = source.slice(i + 1, end).trim();
        i = end + 1;
      }
      if (!SUPPORTED_PSEUDOS.has(value)) {
        throw new Error(`Unsupported selector: pseudo ":${value}" in "${raw}"`);
      }
      compound.pseudos.push({ name: value, argument });
      continue;
    }
    if (/[A-Za-z0-9_-]/.test(ch)) {
      let value = "";
      while (i < source.length && /[A-Za-z0-9_-]/.test(source[i])) {
        value += source[i];
        i += 1;
      }
      compound.tag = value.toLowerCase();
      continue;
    }
    throw new Error(`Unsupported selector: unexpected "${ch}" in "${raw}"`);
  }
  return compound;
}

export function parseSelector(selector) {
  const raw = String(selector ?? "").trim();
  if (!raw) throw new Error("Unsupported selector: empty selector");
  const groups = raw.split(",").map((group) => group.trim()).filter(Boolean);
  if (groups.length === 0) throw new Error("Unsupported selector: empty selector");

  return groups.map((group) => {
    const steps = [];
    let index = 0;
    let pendingCombinator = " ";
    while (index < group.length) {
      while (index < group.length && /\s/.test(group[index])) index += 1;
      if (index >= group.length) break;
      if (group[index] === ">" || group[index] === "+" || group[index] === "~") {
        pendingCombinator = group[index];
        index += 1;
        continue;
      }
      let raw2 = "";
      let depth = 0;
      while (index < group.length) {
        const ch = group[index];
        // Brackets and parentheses both suspend the combinator scan, so
        // `:nth-child(2n+1)` is not split at its plus sign.
        if (ch === "[" || ch === "(") depth += 1;
        if (ch === "]" || ch === ")") depth -= 1;
        if (depth === 0 && /[\s>+~]/.test(ch)) break;
        raw2 += ch;
        index += 1;
      }
      if (!raw2) continue;
      steps.push({ combinator: steps.length === 0 ? null : pendingCombinator, compound: parseCompound(raw2) });
      pendingCombinator = " ";
    }
    if (steps.length === 0) throw new Error(`Unsupported selector: "${selector}"`);
    return steps;
  });
}

function elementChildren(node) {
  return (node?.children ?? []).filter((child) => child.type === "element");
}

function previousElementSibling(node) {
  if (!node?.parent) return null;
  const siblings = elementChildren(node.parent);
  const index = siblings.indexOf(node);
  return index > 0 ? siblings[index - 1] : null;
}

function nextElementSibling(node) {
  if (!node?.parent) return null;
  const siblings = elementChildren(node.parent);
  const index = siblings.indexOf(node);
  return index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : null;
}

function parseNth(argument) {
  const raw = String(argument ?? "").trim().toLowerCase().replace(/\s+/g, "");
  if (raw === "odd") return { a: 2, b: 1 };
  if (raw === "even") return { a: 2, b: 0 };
  const match = raw.match(/^([+-]?\d*)n([+-]\d+)?$/) ?? raw.match(/^([+-]?\d+)$/);
  if (!match) return null;
  if (match[2] === undefined && /^[+-]?\d+$/.test(match[1])) {
    return { a: 0, b: Number(match[1]) };
  }
  const a = match[1] === "" || match[1] === "+" ? 1 : match[1] === "-" ? -1 : Number(match[1]);
  const b = match[2] ? Number(match[2]) : 0;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return { a, b };
}

function matchesNth(position, argument) {
  const nth = parseNth(argument);
  if (!nth) throw new Error(`Unsupported selector: nth-child(${argument})`);
  if (nth.a === 0) return position === nth.b;
  const diff = position - nth.b;
  return diff % nth.a === 0 && diff / nth.a >= 0;
}

function matchesPseudo(node, pseudo) {
  const siblings = elementChildren(node.parent);
  const index = siblings.indexOf(node);
  const sameType = siblings.filter((sibling) => sibling.tagName === node.tagName);
  const typeIndex = sameType.indexOf(node);

  switch (pseudo.name) {
    case "first-child":
      return index === 0;
    case "last-child":
      return index === siblings.length - 1;
    case "nth-child":
      return matchesNth(index + 1, pseudo.argument);
    case "first-of-type":
      return typeIndex === 0;
    case "last-of-type":
      return typeIndex === sameType.length - 1;
    case "only-child":
      return siblings.length === 1;
    case "empty":
      return elementChildren(node).length === 0 && node.children.every((child) => child.type !== "text" || !child.text.trim());
    case "root":
      return node.parent?.type === "root";
    case "not":
      return !matchesAnyGroup(node, parseSelector(pseudo.argument));
    case "has":
      return descendants(node).some((child) => matchesAnyGroup(child, parseSelector(pseudo.argument)));
    case "contains":
      return nodeText(node).includes(String(pseudo.argument ?? ""));
    default:
      return false;
  }
}

function nodeText(node) {
  let out = "";
  const walk = (current) => {
    if (current.type === "text") {
      out += current.text;
      return;
    }
    for (const child of current.children ?? []) walk(child);
  };
  walk(node);
  return out;
}

function matchesCompound(node, compound) {
  if (node?.type !== "element") return false;
  if (compound.tag && node.tagName !== compound.tag) return false;
  if (compound.id && node.attributes.id !== compound.id) return false;
  if (compound.classes.length > 0) {
    const classes = (node.attributes.class ?? "").split(/\s+/).filter(Boolean);
    for (const cls of compound.classes) if (!classes.includes(cls)) return false;
  }
  for (const attr of compound.attributes) {
    const value = node.attributes[attr.name];
    if (value === undefined) return false;
    if (!attr.operator) continue;
    const target = attr.value ?? "";
    switch (attr.operator) {
      case "=":
        if (value !== target) return false;
        break;
      case "^=":
        if (!value.startsWith(target)) return false;
        break;
      case "$=":
        if (!value.endsWith(target)) return false;
        break;
      case "*=":
        if (!value.includes(target)) return false;
        break;
      case "~=":
        if (!value.split(/\s+/).includes(target)) return false;
        break;
      case "|=":
        if (value !== target && !value.startsWith(`${target}-`)) return false;
        break;
      default:
        return false;
    }
  }
  for (const pseudo of compound.pseudos) if (!matchesPseudo(node, pseudo)) return false;
  return true;
}

function matchesSteps(node, steps, index) {
  const step = steps[index];
  if (!matchesCompound(node, step.compound)) return false;
  if (index === 0) return true;
  const combinator = step.combinator ?? " ";
  if (combinator === ">") {
    return node.parent?.type === "element" && matchesSteps(node.parent, steps, index - 1);
  }
  if (combinator === "+") {
    const previous = previousElementSibling(node);
    return !!previous && matchesSteps(previous, steps, index - 1);
  }
  if (combinator === "~") {
    let previous = previousElementSibling(node);
    while (previous) {
      if (matchesSteps(previous, steps, index - 1)) return true;
      previous = previousElementSibling(previous);
    }
    return false;
  }
  let ancestor = node.parent;
  while (ancestor && ancestor.type === "element") {
    if (matchesSteps(ancestor, steps, index - 1)) return true;
    ancestor = ancestor.parent;
  }
  return false;
}

function matchesAnyGroup(node, groups) {
  return groups.some((steps) => matchesSteps(node, steps, steps.length - 1));
}

function descendants(node) {
  const out = [];
  const walk = (current) => {
    for (const child of current.children ?? []) {
      if (child.type === "element") {
        out.push(child);
        walk(child);
      }
    }
  };
  walk(node);
  return out;
}

/* ------------------------------------------------------------------ selection */

export class Selection {
  constructor(nodes, doc) {
    this.nodes = Array.isArray(nodes) ? nodes : [];
    this.doc = doc ?? this;
  }

  get length() {
    return this.nodes.length;
  }

  [Symbol.iterator]() {
    return this.nodes[Symbol.iterator]();
  }

  find(selector) {
    const groups = parseSelector(selector);
    const out = [];
    for (const node of this.nodes) {
      for (const candidate of descendants(node)) {
        if (matchesAnyGroup(candidate, groups)) out.push(candidate);
      }
    }
    return new Selection(out, this.doc);
  }

  filter(selector) {
    const groups = parseSelector(selector);
    return new Selection(this.nodes.filter((node) => matchesAnyGroup(node, groups)), this.doc);
  }

  not(selector) {
    const groups = parseSelector(selector);
    return new Selection(this.nodes.filter((node) => !matchesAnyGroup(node, groups)), this.doc);
  }

  is(selector) {
    const groups = parseSelector(selector);
    return this.nodes.some((node) => matchesAnyGroup(node, groups));
  }

  has(selector) {
    const groups = parseSelector(selector);
    return new Selection(
      this.nodes.filter((node) => descendants(node).some((child) => matchesAnyGroup(child, groups))),
      this.doc,
    );
  }

  text() {
    let out = "";
    const walk = (node) => {
      if (node.type === "text") {
        out += node.text;
        return;
      }
      for (const child of node.children ?? []) walk(child);
    };
    for (const node of this.nodes) walk(node);
    return out;
  }

  html() {
    const node = this.nodes[0];
    if (!node) return "";
    return serialiseChildren(node);
  }

  attr(name, value) {
    if (value === undefined) {
      const node = this.nodes[0];
      if (!node || node.type !== "element") return undefined;
      return node.attributes[name];
    }
    for (const node of this.nodes) {
      if (node.type === "element") node.attributes[String(name).toLowerCase()] = String(value);
    }
    return this;
  }

  attrs() {
    const node = this.nodes[0];
    if (!node || node.type !== "element") return {};
    return { ...node.attributes };
  }

  data(name) {
    const node = this.nodes[0];
    if (!node || node.type !== "element") return undefined;
    return node.attributes[`data-${name}`];
  }

  children(selector) {
    const out = [];
    for (const node of this.nodes) out.push(...elementChildren(node));
    if (!selector) return new Selection(out, this.doc);
    return new Selection(out, this.doc).filter(selector);
  }

  contents() {
    const out = [];
    for (const node of this.nodes) out.push(...(node.children ?? []));
    return new Selection(out, this.doc);
  }

  parent() {
    const out = [];
    for (const node of this.nodes) {
      if (node.parent?.type === "element" && !out.includes(node.parent)) out.push(node.parent);
    }
    return new Selection(out, this.doc);
  }

  parents(selector) {
    const out = [];
    for (const node of this.nodes) {
      let ancestor = node.parent;
      while (ancestor && ancestor.type === "element") {
        if (!out.includes(ancestor)) out.push(ancestor);
        ancestor = ancestor.parent;
      }
    }
    return selector ? new Selection(out, this.doc).filter(selector) : new Selection(out, this.doc);
  }

  parentsUntil(selector) {
    const groups = parseSelector(selector);
    const out = [];
    for (const node of this.nodes) {
      let ancestor = node.parent;
      while (ancestor && ancestor.type === "element" && !matchesAnyGroup(ancestor, groups)) {
        if (!out.includes(ancestor)) out.push(ancestor);
        ancestor = ancestor.parent;
      }
    }
    return new Selection(out, this.doc);
  }

  closest(selector) {
    const groups = parseSelector(selector);
    const out = [];
    for (const node of this.nodes) {
      let current = node;
      while (current && current.type === "element") {
        if (matchesAnyGroup(current, groups)) {
          out.push(current);
          break;
        }
        current = current.parent;
      }
    }
    return new Selection(out, this.doc);
  }

  next(selector) {
    const out = this.nodes.map(nextElementSibling).filter(Boolean);
    return selector ? new Selection(out, this.doc).filter(selector) : new Selection(out, this.doc);
  }

  nextAll(selector) {
    const out = [];
    for (const node of this.nodes) {
      let sibling = nextElementSibling(node);
      while (sibling) {
        out.push(sibling);
        sibling = nextElementSibling(sibling);
      }
    }
    return selector ? new Selection(out, this.doc).filter(selector) : new Selection(out, this.doc);
  }

  prev(selector) {
    const out = this.nodes.map(previousElementSibling).filter(Boolean);
    return selector ? new Selection(out, this.doc).filter(selector) : new Selection(out, this.doc);
  }

  prevAll(selector) {
    const out = [];
    for (const node of this.nodes) {
      let sibling = previousElementSibling(node);
      while (sibling) {
        out.push(sibling);
        sibling = previousElementSibling(sibling);
      }
    }
    return selector ? new Selection(out, this.doc).filter(selector) : new Selection(out, this.doc);
  }

  siblings(selector) {
    const out = [];
    for (const node of this.nodes) {
      for (const sibling of elementChildren(node.parent)) {
        if (sibling !== node && !out.includes(sibling)) out.push(sibling);
      }
    }
    return selector ? new Selection(out, this.doc).filter(selector) : new Selection(out, this.doc);
  }

  eq(index) {
    const position = index < 0 ? this.nodes.length + index : index;
    const node = this.nodes[position];
    return new Selection(node ? [node] : [], this.doc);
  }

  first() {
    return this.eq(0);
  }

  last() {
    return this.eq(-1);
  }

  each(callback) {
    if (typeof callback !== "function") throw new TypeError("each() requires a function");
    this.nodes.forEach((node, index) => {
      callback(index, new Selection([node], this.doc));
    });
    return undefined;
  }

  map(callback) {
    if (typeof callback !== "function") throw new TypeError("map() requires a function");
    return this.nodes.map((node, index) => callback(index, new Selection([node], this.doc)));
  }

  get(index) {
    if (index === undefined) return this.nodes.slice();
    const position = index < 0 ? this.nodes.length + index : index;
    return this.nodes[position];
  }

  remove() {
    for (const node of this.nodes) {
      const siblings = node.parent?.children;
      if (!Array.isArray(siblings)) continue;
      const at = siblings.indexOf(node);
      if (at >= 0) siblings.splice(at, 1);
    }
    return this;
  }

  val() {
    const node = this.nodes[0];
    if (!node || node.type !== "element") return "";
    if (node.tagName === "textarea") return nodeText(node);
    if (node.attributes.value !== undefined) return node.attributes.value;
    if (node.attributes.content !== undefined) return node.attributes.content;
    return "";
  }

  prop(name) {
    const node = this.nodes[0];
    if (!node || node.type !== "element") return undefined;
    if (name === "tagName") return node.tagName;
    if (name === "innerHTML") return serialiseChildren(node);
    if (name === "textContent") return nodeText(node);
    return node.attributes[String(name).toLowerCase()];
  }

  append(html) {
    const fragment = parseHtml(String(html ?? "")).children;
    for (const node of this.nodes) {
      if (node.type !== "element") continue;
      for (const child of fragment) {
        const copy = structuredCloneNode(child);
        copy.parent = node;
        node.children.push(copy);
      }
    }
    return this;
  }

  nextUntil(selector) {
    const groups = parseSelector(selector);
    const out = [];
    for (const node of this.nodes) {
      let sibling = nextElementSibling(node);
      while (sibling && !matchesAnyGroup(sibling, groups)) {
        out.push(sibling);
        sibling = nextElementSibling(sibling);
      }
    }
    return new Selection(out, this.doc);
  }

  prevUntil(selector) {
    const groups = parseSelector(selector);
    const out = [];
    for (const node of this.nodes) {
      let sibling = previousElementSibling(node);
      while (sibling && !matchesAnyGroup(sibling, groups)) {
        out.push(sibling);
        sibling = previousElementSibling(sibling);
      }
    }
    return new Selection(out, this.doc);
  }

  clone() {
    return new Selection(this.nodes.map(structuredCloneNode), this.doc);
  }

  end() {
    return new Selection([], this.doc);
  }

  toArray() {
    return this.nodes.slice();
  }
}

function structuredCloneNode(node) {
  if (node.type === "text") return { type: "text", text: node.text, parent: null };
  const copy = {
    type: "element",
    tagName: node.tagName,
    attributes: { ...node.attributes },
    children: [],
    parent: null,
  };
  copy.children = (node.children ?? []).map((child) => {
    const cloned = structuredCloneNode(child);
    cloned.parent = copy;
    return cloned;
  });
  return copy;
}

function serialiseChildren(node) {
  const escapeText = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const serialise = (child) => {
    if (child.type === "text") return escapeText(child.text);
    const attrs = Object.entries(child.attributes ?? {})
      .map(([key, value]) => ` ${key}="${String(value).replace(/"/g, "&quot;")}"`)
      .join("");
    const inner = (child.children ?? []).map(serialise).join("");
    if (VOID_ELEMENTS.has(child.tagName)) return `<${child.tagName}${attrs}>`;
    return `<${child.tagName}${attrs}>${inner}</${child.tagName}>`;
  };
  return (node.children ?? []).map(serialise).join("");
}

/** LoadDoc(html) equivalent. */
export function loadDoc(html) {
  const root = parseHtml(html);
  return new Selection([root], null);
}

/** `new Doc(html)` equivalent: a selection whose first node is the document. */
/** Older imports in this tree use the name `DocSelection`. */
export { Selection as DocSelection };

export class Doc extends Selection {
  constructor(html) {
    const selection = loadDoc(html);
    super(selection.nodes, null);
    this.doc = this;
  }
}
