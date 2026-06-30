import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#151719",
        panel: "#F5F6F3",
        line: "#D7DDD6",
        accent: "#2C7A64",
        warn: "#9A5A21",
      },
      boxShadow: {
        soft: "0 18px 50px rgba(21, 23, 25, 0.10)",
      },
    },
  },
  plugins: [],
} satisfies Config;
