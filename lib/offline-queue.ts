// Offline invoice queue (IndexedDB). Files picked while offline -- or whose upload fails because
// of the network -- are kept on this device and uploaded automatically when back online.
// Duplicate protection: each file is identified by its SHA-256 hash; the same file can't be
// queued twice, and a file this browser already uploaded asks for confirmation.

export type QueueItem = {
  hash: string; name: string; type: string; size: number; blob: Blob; addedAt: number;
  status: "pending" | "uploading" | "failed" | "done"; attempts: number; lastError?: string; invoiceId?: string; nextTry?: number; optimize?: boolean;
};

const DB = "gstdesk-offline", STORE = "queue", DONE = "uploaded", EVT = "gstdesk-queue-changed";
const MAX_ATTEMPTS = 6;

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore(STORE, { keyPath: "hash" });
      r.result.createObjectStore(DONE, { keyPath: "hash" });
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode); const req = fn(t.objectStore(store));
    req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
  });
}
const changed = () => window.dispatchEvent(new Event(EVT));
export const onQueueChange = (fn: () => void) => { window.addEventListener(EVT, fn); return () => window.removeEventListener(EVT, fn); };

export async function hashFile(f: Blob): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", await f.arrayBuffer());
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
export const listQueue = () => tx<QueueItem[]>(STORE, "readonly", (s) => s.getAll() as IDBRequest<QueueItem[]>);
export const wasUploaded = async (hash: string) => !!(await tx(DONE, "readonly", (s) => s.get(hash)));
export const markUploaded = async (hash: string, invoiceId: string) => { await tx(DONE, "readwrite", (s) => s.put({ hash, invoiceId, at: Date.now() })); };
export const removeItem = async (hash: string) => { await tx(STORE, "readwrite", (s) => s.delete(hash)); changed(); };

/** Adds a file to the queue. Returns false if the very same file is already queued. */
export async function enqueue(file: File, hash?: string, optimize = false): Promise<boolean> {
  const h = hash || (await hashFile(file));
  if (await tx(STORE, "readonly", (s) => s.get(h))) return false;
  await tx(STORE, "readwrite", (s) => s.put({ hash: h, name: file.name, type: file.type, size: file.size, blob: file,
    addedAt: Date.now(), status: "pending", attempts: 0, optimize } as QueueItem));
  changed();
  return true;
}

let running = false;
/** Uploads everything pending, oldest first, with exponential back-off for failures.
 *  Server errors (4xx) are not retried forever: after MAX_ATTEMPTS the item stays "failed" for the user to decide. */
export async function processQueue(onDone?: (item: QueueItem, invoiceNumber?: string) => void): Promise<number> {
  if (running || !navigator.onLine) return 0;
  running = true;
  let uploaded = 0;
  try {
    const items = (await listQueue()).filter((i) => i.status !== "done" && (i.nextTry ?? 0) <= Date.now() && i.attempts < MAX_ATTEMPTS)
      .sort((a, b) => a.addedAt - b.addedAt);
    for (const item of items) {
      await tx(STORE, "readwrite", (s) => s.put({ ...item, status: "uploading" })); changed();
      try {
        const form = new FormData();
        form.append("file", new File([item.blob], item.name, { type: item.type }));
        const res = await fetch(`/api/v1/invoices${item.optimize ? "?optimize=true" : ""}`, { method: "POST", body: form,
          headers: { "Idempotency-Key": `sha256-${item.hash}` } });   // a retry can never create a second invoice
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Server error ${res.status}`);
        await markUploaded(item.hash, data.id);
        await tx(STORE, "readwrite", (s) => s.delete(item.hash));
        uploaded++;
        try { localStorage.setItem("gstdesk-last-sync", new Date().toISOString()); } catch { /* private mode */ }
        onDone?.(item, data.invoice_number);
      } catch (e) {
        const attempts = item.attempts + 1;
        await tx(STORE, "readwrite", (s) => s.put({ ...item, status: "failed", attempts, lastError: e instanceof Error ? e.message : String(e),
          nextTry: Date.now() + Math.min(60_000 * 2 ** attempts, 30 * 60_000) }));
      }
      changed();
    }
  } finally {
    running = false;
  }
  return uploaded;
}

export async function retryNow(hash: string) {
  const item = await tx<QueueItem | undefined>(STORE, "readonly", (s) => s.get(hash) as IDBRequest<QueueItem | undefined>);
  if (item) { await tx(STORE, "readwrite", (s) => s.put({ ...item, status: "pending", nextTry: 0, attempts: Math.min(item.attempts, 5) })); changed(); }
  return processQueue();
}


/** Removes everything GST Desk keeps on this device (queued files, drafts, cached pages). */
export async function clearLocalData(): Promise<void> {
  await new Promise<void>((resolve) => { const r = indexedDB.deleteDatabase(DB); r.onsuccess = r.onerror = r.onblocked = () => resolve(); });
  try {
    Object.keys(localStorage).filter((k) => k.startsWith("gstdesk-")).forEach((k) => localStorage.removeItem(k));
  } catch { /* private mode */ }
  if ("caches" in window) for (const k of await caches.keys()) await caches.delete(k);
  changed();
}
