"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AppShell } from "@/components/chrome/AppShell";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <AppShell>{children}</AppShell>
    </QueryClientProvider>
  );
}
