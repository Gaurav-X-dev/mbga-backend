import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

import { AuthProvider } from "../auth/AuthProvider";
import { ToastProvider } from "../components/feedback/ToastProvider";
import { ThemeProvider } from "../theme/ThemeProvider";
import { queryClient as defaultQueryClient } from "./query-client";

export function AppProviders({ children, client = defaultQueryClient }: PropsWithChildren<{ client?: QueryClient }>) {
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
