"use client";
import { useEffect, useState } from "react";

const STORAGE_KEY = "moonshot_admin";

/**
 * Read-only gate.
 * - If NEXT_PUBLIC_ADMIN_KEY is unset/empty → everyone gets full access (dev mode).
 * - If set → visitor must arrive with ?admin=<key> (persisted in localStorage).
 * - Without the key → read-only: all data visible, action buttons hidden.
 */
export function useReadOnly(): boolean {
  const [readOnly, setReadOnly] = useState(true);

  useEffect(() => {
    const requiredKey = process.env.NEXT_PUBLIC_ADMIN_KEY ?? "";

    // No admin key configured → full access for everyone (local dev)
    if (!requiredKey) {
      setReadOnly(false);
      return;
    }

    // Check URL param first
    const params = new URLSearchParams(window.location.search);
    const urlKey = params.get("admin");

    if (urlKey === requiredKey) {
      localStorage.setItem(STORAGE_KEY, urlKey);
      // Remove ?admin= from URL so it's not shared accidentally
      params.delete("admin");
      const clean = params.toString();
      const newUrl = window.location.pathname + (clean ? `?${clean}` : "");
      window.history.replaceState({}, "", newUrl);
      setReadOnly(false);
      return;
    }

    // Check localStorage
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === requiredKey) {
      setReadOnly(false);
      return;
    }

    // No valid key → read-only
    setReadOnly(true);
  }, []);

  return readOnly;
}
