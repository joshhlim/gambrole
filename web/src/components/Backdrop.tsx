/**
 * Slow-moving colour behind every screen, so the app never looks like a
 * flat sheet of off-white.
 *
 * Mounted once in the root layout, outside the page-transition wrapper: it
 * should sit still while pages slide across it, not travel with them.
 *
 * Three blurred pools in the brand palette, drifting on long offset cycles
 * so they never visibly loop. Transform and opacity only — it stays on the
 * compositor and costs a phone nothing — and it sits behind everything with
 * pointer events off, so it can't interfere with anything tappable.
 */
export default function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        className="blob blob-a"
        style={{
          top: "-12%",
          left: "-18%",
          width: "70vw",
          height: "70vw",
          background: "radial-gradient(circle, rgba(30,107,79,0.30), transparent 68%)",
        }}
      />
      <div
        className="blob blob-b"
        style={{
          bottom: "-20%",
          right: "-16%",
          width: "78vw",
          height: "78vw",
          background: "radial-gradient(circle, rgba(217,180,74,0.32), transparent 68%)",
        }}
      />
      <div
        className="blob blob-c"
        style={{
          top: "32%",
          right: "-28%",
          width: "58vw",
          height: "58vw",
          background: "radial-gradient(circle, rgba(30,58,47,0.22), transparent 70%)",
        }}
      />
    </div>
  );
}
