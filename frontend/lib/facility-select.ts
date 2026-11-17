/** Pure selection rule: URL param > stored > first facility (only ids that exist are honoured). */
export function pickFacility(facilities: { id: string }[], fromUrl: string | null, stored: string | null): string | null {
  for (const candidate of [fromUrl, stored]) if (candidate && facilities.some((f) => f.id === candidate)) return candidate;
  return facilities[0]?.id ?? null;
}
