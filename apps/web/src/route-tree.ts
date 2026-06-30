import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes";

export const routeTree = rootRoute.addChildren([indexRoute]);
