"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { readStoredRun } from "./format";

export function useRunId(): string | null {
  const params = useSearchParams();
  const [stored, setStored] = useState<string | null>(null);
  useEffect(() => {
    setStored(readStoredRun());
  }, []);
  return params.get("run") || stored;
}
