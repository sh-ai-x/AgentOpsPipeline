"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

// The whole wiki UI is fully client-interactive — it requires
// window.showDirectoryPicker (File System Access API) and a runtime
// JWT. SSR adds nothing useful here and the SSR pass renders an
// empty page (no bearer, no corpus), which can mismatch hydration
// if a browser extension (e.g. cz-shortcut-listen) injects attributes
// into the static HTML before React hydrates. dynamic({ ssr: false })
// short-circuits that entirely.
const HomePage = dynamic(() => import("./HomePageImpl"), {
  ssr: false,
  loading: () => <main><p className="subtitle">Loading wiki UI…</p></main>,
});

export default function Page() {
  // A single useState so the dynamic import's default export sees
  // a stable component instance; nothing stateful lives here.
  const [, setTick] = useState(0);
  return <HomePage />;
}
