// What a draft changes against the saved trainer.yaml: the sections (and the models and generators inside)
// added, removed and changed, and the lines that differ. Pure functions (the line diff is the Assist Router
// editor's, taken over from the wake word studio).

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
// sections whose entries are parts of their own: models/e4b, generate/router …
const NESTED = new Set(["models", "generate"]);

/** The parts of the settings by key: a section, or section/entry for the nested ones. */
function parts(data) {
  const out = new Map();
  for (const [key, value] of Object.entries(data || {})) {
    if (NESTED.has(key) && value && typeof value === "object" && !Array.isArray(value)) {
      for (const [name, entry] of Object.entries(value)) out.set(`${key}/${name}`, entry);
    } else {
      out.set(key, value);
    }
  }
  return out;
}

export function describeChanges(before, after) {
  const result = { added: [], removed: [], changed: [], order: false };
  const a = parts(before);
  const b = parts(after);
  for (const [key, value] of b) {
    if (!a.has(key)) result.added.push(key);
    else if (!same(a.get(key), value)) result.changed.push(key);
  }
  for (const key of a.keys()) if (!b.has(key)) result.removed.push(key);
  return result;
}

/** The lines of two texts as kept, removed and added; past `limit` cells of the table, a plain swap of the middle. */
export function diffLines(before, after, limit = 4_000_000) {
  const a = before ? before.split("\n") : [];
  const b = after ? after.split("\n") : [];
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1;
    endB -= 1;
  }
  const head = a.slice(0, start).map((text, index) => ({ kind: "same", text, line: index + 1 }));
  const shift = endB - endA;
  const tail = a.slice(endA).map((text, index) => ({ kind: "same", text, line: endA + index + 1 + shift }));
  const middleA = a.slice(start, endA);
  const middleB = b.slice(start, endB);
  if (middleA.length * middleB.length > limit) {
    return [
      ...head,
      ...middleA.map((text) => ({ kind: "removed", text })),
      ...middleB.map((text, index) => ({ kind: "added", text, line: start + index + 1 })),
      ...tail,
    ];
  }
  const cols = middleB.length + 1;
  const table = new Uint32Array((middleA.length + 1) * cols);
  for (let i = middleA.length - 1; i >= 0; i -= 1) {
    for (let j = middleB.length - 1; j >= 0; j -= 1) {
      table[i * cols + j] =
        middleA[i] === middleB[j] ? table[(i + 1) * cols + j + 1] + 1 : Math.max(table[(i + 1) * cols + j], table[i * cols + j + 1]);
    }
  }
  const middle = [];
  let i = 0;
  let j = 0;
  const line = () => start + j + 1;
  while (i < middleA.length && j < middleB.length) {
    if (middleA[i] === middleB[j]) {
      middle.push({ kind: "same", text: middleA[i], line: line() });
      i += 1;
      j += 1;
    } else if (table[(i + 1) * cols + j] >= table[i * cols + j + 1]) {
      middle.push({ kind: "removed", text: middleA[i] });
      i += 1;
    } else {
      middle.push({ kind: "added", text: middleB[j], line: line() });
      j += 1;
    }
  }
  for (; i < middleA.length; i += 1) middle.push({ kind: "removed", text: middleA[i] });
  for (; j < middleB.length; j += 1) middle.push({ kind: "added", text: middleB[j], line: line() });
  return [...head, ...middle, ...tail];
}

/** Only the changed lines with a few around them, and the number of lines left out between them. */
export function diffHunks(lines, context = 3) {
  const keep = new Set();
  lines.forEach((line, index) => {
    if (line.kind === "same") return;
    for (let near = index - context; near <= index + context; near += 1) keep.add(near);
  });
  const out = [];
  let skipped = 0;
  lines.forEach((line, index) => {
    if (keep.has(index)) {
      if (skipped) out.push({ kind: "skip", count: skipped });
      skipped = 0;
      out.push(line);
    } else skipped += 1;
  });
  if (skipped && out.length) out.push({ kind: "skip", count: skipped });
  return out;
}
