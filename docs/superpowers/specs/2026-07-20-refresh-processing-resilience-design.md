# Refresh and Processing Resilience Design

## Objective

Prevent one stalled podcast host from disabling all background feed refreshes, retry transient episode-download failures, make scheduler stalls visible to Docker health monitoring, and correct the production `user_download.post_id` nullability mismatch.

## Confirmed production failures

- The 17 July scheduled refresh blocked indefinitely inside `feedparser.parse(url)` while reading the LINUX Unplugged feed. Because APScheduler permits one `refresh_all_feeds` instance, at least 401 later executions were skipped while the container continued reporting healthy.
- A feed-token trigger for Joe Rogan episode `#2524 - Rupert Lowe` queued correctly, but the first audio download timed out after 60 seconds. A manual retry 22 seconds later succeeded. The downloader has no transient retry policy.
- Production is stamped at migration head `p2q3r4s5t6u7`, but `user_download.post_id` remains `NOT NULL`. Combined-feed `RSS_READ` audit events therefore fail with an integrity error.

## Design

### Bounded RSS retrieval

`fetch_feed()` will retrieve RSS bytes with `requests.get()` using a 10-second connect timeout and 30-second read timeout, require a successful HTTP status, and pass the response bytes to `feedparser.parse()`. RSS retrieval will not retry inside a cycle: network or HTTP failures remain per-feed exceptions, and `start_refresh_all_feeds()` already catches those exceptions and continues with later feeds. This bounds a normally failing feed well below the 15-minute stale-cycle threshold.

This preserves the current sequential refresh architecture and prevents an upstream feed from occupying the sole APScheduler job instance indefinitely. It deliberately avoids parallel feed fetching because the observed failure only requires a bounded component boundary, and parallelism would increase SQLite and upstream-host concurrency.

### Retry-safe episode downloads

`PodcastDownloader` will make at most three attempts for transient failures:

- request timeouts and connection errors;
- HTTP 429 responses;
- HTTP 5xx responses.

Each attempt uses a 10-second connect timeout and 60-second read timeout. Retries wait one second after the first failure and two seconds after the second failure. Non-transient 4xx responses fail immediately, retaining the existing Podtrac-specific error. Each attempt writes to a sibling `.part` file. A successful response atomically replaces the destination; failed attempts remove the partial file so subsequent processing never mistakes incomplete audio for a valid download. Three fully timed-out attempts plus backoff remain well below the scheduler's 15-minute stale threshold, although episode processing itself is not performed by the scheduler executor.

### Scheduler liveness health

A process-wide non-blocking refresh lock will prevent scheduled and manual refresh-all calls from overlapping. A call made while another cycle owns the lock will return an `already_running` result without clearing or replacing the active cycle's health state.

A small thread-safe refresh-health state will record:

- whether a refresh-all cycle is running;
- its start time;
- the current feed ID;
- the most recent completed cycle;
- the most recent error.

`start_refresh_all_feeds()` will mark cycle start after acquiring the lock and update the current feed before each fetch. Caught per-feed failures update `last_error` but do not make the health endpoint unhealthy because a cycle is expected to continue past individual upstream failures. After the loop and pending-job enqueueing finish, `last_completed_at` updates even when individual feeds failed. A `finally` block always clears the running fields and releases the lock, but it does not update `last_completed_at` when an uncaught cycle-level exception aborts the cycle.

A public internal-health endpoint will return HTTP 503 when a cycle has run longer than 15 minutes. Its JSON fields will be `status`, `refresh_running`, `refresh_started_at`, `current_feed_id`, `last_completed_at`, `last_error`, and `stale_after_seconds`; timestamps use UTC ISO 8601. The public `last_error` value is limited to a sanitized error-class code and feed ID and must never contain raw exception text, URLs, query strings, credentials, or tokens. Full exception details remain in private application logs. The endpoint will otherwise return HTTP 200, including during startup before the first cycle. The first stale health check for a cycle emits one error log; later Docker probes for the same stale cycle do not repeat that log.

Docker's healthcheck will call this endpoint instead of `/`. This does not automatically restart unhealthy containers; it makes the failure visible to Docker, Portainer, cAdvisor, and existing monitoring. The application will also emit an error log when health becomes stale.

### Corrective migration

A new migration after `p2q3r4s5t6u7` will use Alembic batch mode to make `user_download.post_id` nullable while preserving rows and indexes. The downgrade will restore `NOT NULL` only when no null `post_id` rows exist; otherwise it will stop with an explicit error rather than destroy audit data.

No model change is required because `UserDownload.post_id` is already declared nullable.

## Testing

Tests will be written before implementation and observed failing for the intended reasons:

- RSS fetching passes explicit timeouts, parses response bytes, raises on failed HTTP responses, and never calls URL-based `feedparser.parse()`.
- A transient audio timeout retries and succeeds; exhausted retries raise; non-transient responses do not retry; partial files are removed; successful files are atomically promoted.
- Overlapping refresh-all calls are rejected without altering the active cycle's health state.
- Refresh-health state becomes stale after 15 minutes, the health endpoint changes from 200 to 503, and repeated probes log only once for that stale cycle.
- The corrective migration upgrades a representative SQLite schema to nullable, safely downgrades a schema without null rows, and refuses downgrade without deleting data when null feed-level audit rows exist.

Targeted tests, Ruff, and Ty will be run. The full suite will also run with the seven known FFmpeg-dependent failures excluded because this Mac's Homebrew FFmpeg currently cannot load `libx265.215.dylib`.

## Deployment and verification

1. Build the updated Podly image on `big` using the existing Compose configuration.
2. Back up the SQLite database before migration.
3. Apply the corrective migration through the container's Python/Alembic environment.
4. Restart Podly and wait for Docker health to become healthy.
5. Confirm a complete 23-feed scheduled cycle finishes, including feed 13.
6. Confirm `user_download.post_id` is nullable and a combined-feed `RSS_READ` event can be recorded.
7. Confirm no new APScheduler `max_instances` skips or refresh errors appear.

Rollback uses the database backup plus the previous image. The migration downgrade is available when no null feed-level audit rows have been created.
