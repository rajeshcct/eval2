interface ErrorBannerProps {
  errors: { stage: string; message: string }[];
}

/**
 * Phase IV requirement 4 — on an `error` event: an inline, non-crashing
 * banner with the message and stage. Renders every error seen so far
 * (most recent first) rather than just the last one, since a request-level
 * failure and a later session-level failure are both worth keeping visible.
 */
export default function ErrorBanner({ errors }: ErrorBannerProps) {
  if (errors.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {[...errors].reverse().map((e, i) => (
        <div
          key={i}
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-red-500/40 border-l-4 border-l-red-500 bg-red-500/10 px-4 py-3 text-sm text-red-300"
        >
          <span aria-hidden className="text-base leading-5">
            ⛔
          </span>
          <p>
            <span className="font-semibold text-red-200">{e.stage}:</span> {e.message}
          </p>
        </div>
      ))}
    </div>
  );
}
