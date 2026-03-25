"use client";

import dynamic from "next/dynamic";

const Assistant = dynamic(() => import("./assistant").then((m) => m.Assistant), {
  ssr: false,
});

export default function Home() {
  return <Assistant />;
}
