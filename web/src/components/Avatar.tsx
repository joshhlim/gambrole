import { API_URL } from "@/lib/config";
import { ACCENTS } from "@/lib/friendsTypes";

/** Up to two letters: first and last word, so "Mary Jane Lee" is "ML". */
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0][0];
  const last = words.length > 1 ? words[words.length - 1][0] : "";
  return (first + last).toUpperCase();
}

/** The accent's colour token, or null for none (or one this build doesn't
 * know, from a newer API). */
export function accentColor(accent?: string | null): string | null {
  return accent && (ACCENTS as readonly string[]).includes(accent) ? `var(--accent-${accent})` : null;
}

/**
 * A player's photo, or their initials when there isn't one. With an accent
 * the initials sit on it in white and a photo gets a thin ring of it;
 * without one, initials are brand-on-tint and a photo just a hairline.
 */
export default function Avatar({
  name,
  url,
  src,
  accent,
  size = 32,
  className = "",
}: {
  name: string;
  /** As the API returns it: relative to API_URL. */
  url?: string | null;
  /** An absolute URL that wins over `url` — a local preview of a photo
   * still uploading. */
  src?: string | null;
  accent?: string | null;
  size?: number;
  className?: string;
}) {
  const color = accentColor(accent);
  const ring = size >= 64 ? 3 : 2;
  const base = { width: size, height: size, fontSize: Math.round(size * 0.38) };
  const href = src ?? (url && API_URL ? `${API_URL}${url}` : null);
  if (href) {
    return (
      // A plain img: these are tiny, already sized server-side, and served
      // from the API's origin, which next/image would need configuring for.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={href}
        alt=""
        data-testid="avatar-photo"
        style={{
          ...base,
          // A gap of the surface between photo and ring keeps a dark photo
          // from merging into a dark accent.
          boxShadow: color ? `0 0 0 1.5px var(--surface), 0 0 0 ${ring + 1.5}px ${color}` : undefined,
        }}
        className={`shrink-0 rounded-full object-cover ${color ? "" : "border border-border"} ${className}`}
      />
    );
  }
  return (
    <span
      aria-hidden
      data-testid="avatar-initials"
      data-accent={color ? accent : undefined}
      style={color ? { ...base, background: color } : base}
      className={`flex shrink-0 select-none items-center justify-center rounded-full font-semibold ${
        color ? "text-white" : "bg-brand/10 text-brand"
      } ${className}`}
    >
      {initials(name)}
    </span>
  );
}
