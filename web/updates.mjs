// Only public build identifiers are checked; decrypted data is never cached.
const VERSION = /^[a-f0-9]{64}$/;

export function updateChecker({
  current,
  safe,
  reload,
  waiting = () => {},
  fetcher = fetch,
  now = Date.now,
  storage,
}) {
  let busy = false,
    notified = null,
    attempted = null,
    attemptedAt = 0;
  return async function check() {
    if (!VERSION.test(current) || busy) return;
    busy = true;
    try {
      const response = await fetcher("./release.json", {
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
      if (!response.ok) return;
      const reader = response.body.getReader();
      let bytes = 0,
        chunks = [];
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          bytes += value.length;
          if (bytes > 1024) {
            await reader.cancel();
            return;
          }
          chunks.push(value);
        }
      } finally {
        reader.releaseLock();
      }
      const data = new Uint8Array(bytes);
      let offset = 0;
      for (const chunk of chunks) {
        data.set(chunk, offset);
        offset += chunk.length;
      }
      const release = JSON.parse(new TextDecoder().decode(data));
      if (
        release.schema_version !== 1 ||
        !VERSION.test(release.version) ||
        release.version === current
      )
        return;
      if (!safe()) {
        if (notified !== release.version) {
          waiting();
          notified = release.version;
        }
        return;
      }
      let last = { version: attempted, time: attemptedAt };
      try {
        last =
          JSON.parse(storage?.getItem("atlas-update-attempt") || "null") ||
          last;
      } catch {}
      // A CDN may expose release.json before index.html; avoid a reload loop.
      if (last.version === release.version && now() - last.time < 60000) return;
      attempted = release.version;
      attemptedAt = now();
      try {
        storage?.setItem(
          "atlas-update-attempt",
          JSON.stringify({ version: attempted, time: attemptedAt }),
        );
      } catch {}
      reload(release.version);
    } catch {
      // Offline and transient publication failures leave the current app intact.
    } finally {
      busy = false;
    }
  };
}

export function watchUpdates(options) {
  const check = updateChecker(options);
  const visible = () => {
    if (document.visibilityState === "visible") void check();
  };
  const timer = setInterval(visible, 5 * 60000);
  document.addEventListener("visibilitychange", visible);
  window.addEventListener("online", visible);
  window.addEventListener("focus", visible);
  void check();
  return () => {
    clearInterval(timer);
    document.removeEventListener("visibilitychange", visible);
    window.removeEventListener("online", visible);
    window.removeEventListener("focus", visible);
  };
}
