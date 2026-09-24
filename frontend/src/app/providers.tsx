import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

import { AuthProvider } from "../auth/AuthProvider";
import { ToastProvider } from "../components/feedback/ToastProvider";
import { queryClient as defaultQueryClient } from "./query-client";

export function AppProviders({ children, client = defaultQueryClient }: PropsWithChildren<{ client?: QueryClient }>) {
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AuthProvider>{children}</AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
