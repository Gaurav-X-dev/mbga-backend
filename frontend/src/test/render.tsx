import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, RouterProvider, createMemoryRouter } from "react-router-dom";

import { AppProviders } from "../app/providers";
import { createQueryClient } from "../app/query-client";
import { routes } from "../app/router";

/** Full application (real routes, guards and providers) at a given address. */
export function renderApp(initialPath: string) {
  const router = createMemoryRouter(routes, {
    initialEntries: [initialPath],
    future: { v7_relativeSplatPath: true }
  });
  const client = createQueryClient();
  const result = render(
    <AppProviders client={client}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </AppProviders>
  );
  return { ...result, router, client };
}

/** A single component with providers and a simple router. */
export function renderWithProviders(ui: ReactElement, initialPath = "/") {
  const client = createQueryClient();
  return {
    client,
    ...render(
      <AppProviders client={client}>
        <MemoryRouter initialEntries={[initialPath]} future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
          {ui}
        </MemoryRouter>
      </AppProviders>
    )
  };
}
