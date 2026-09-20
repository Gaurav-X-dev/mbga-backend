import { QueryClient } from "@tanstack/react-query";

import { isRetryableError } from "../api/errors";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        // Validation, authentication and permission failures are never retried.
        retry: (failureCount, error) => failureCount < 2 && isRetryableError(error),
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 5000)
      },
      mutations: {
        retry: false
      }
    }
  });
}

export const queryClient = createQueryClient();
