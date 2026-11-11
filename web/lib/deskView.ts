import type { DeskClaim } from "./api";

const ALLOWED_HOSTS = new Set(["groww.in", "www.groww.in"]);

export function allowListedUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && ALLOWED_HOSTS.has(parsed.hostname);
  } catch {
    return false;
  }
}

export function lastCheckedLabel(value: string | null | undefined): string {
  if (value && value.trim()) return value;
  return "date unavailable";
}

export function claimIsVerified(claim: DeskClaim): boolean {
  return Boolean(claim.claim.trim()) && allowListedUrl(claim.source_url);
}
