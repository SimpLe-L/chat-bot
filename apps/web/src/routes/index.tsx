import { createRoute } from "@tanstack/react-router";

import { ChatShell } from "../components/chat-shell";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: ChatShell,
});

export const Route = indexRoute;
