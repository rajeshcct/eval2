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
          className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300"
        >
          <span className="font-medium text-red-200">{e.stage}:</span> {e.message}
        </div>
      ))}
    </div>
  );
}
