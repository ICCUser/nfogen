import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// Sans les globals vitest, @testing-library/react ne s'auto-nettoie pas
// entre les tests (composants precedents restant montes dans le DOM).
afterEach(() => cleanup());

// jsdom's localStorage is unreliable across Node versions (Node's own
// experimental global `localStorage` can shadow it, ending up undefined) :
// deterministic in-memory polyfill instead of depending on that.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const storage = new MemoryStorage();
for (const target of [globalThis, window]) {
  Object.defineProperty(target, "localStorage", { value: storage, configurable: true });
}
