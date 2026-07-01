import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes";
import { loginRoute } from "./routes/login";

export const routeTree = rootRoute.addChildren([indexRoute, loginRoute]);
