import { useEffect, useState } from "react";
import { createRoute } from "@tanstack/react-router";

import { LoginPage } from "../components/login-page";
import { getCurrentUser, type AuthUser } from "../lib/auth";
import { rootRoute } from "./__root";

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginRoute,
});

export const Route = loginRoute;

function LoginRoute() {
  const [user, setUser] = useState<AuthUser | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then((currentUser) => {
        if (!cancelled) {
          setUser(currentUser);
          if (currentUser) {
            window.location.replace("/");
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (user === undefined) {
    return (
      <main className="grid h-screen place-items-center bg-[#F5F6F1] text-sm text-ink/55">
        正在检查登录状态...
      </main>
    );
  }

  if (user) {
    return null;
  }

  return (
    <LoginPage
      onLogin={(nextUser) => {
        setUser(nextUser);
        window.location.assign("/");
      }}
    />
  );
}
