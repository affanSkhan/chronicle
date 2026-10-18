import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172033",
        muted: "#65718A",
        line: "#E5E9F1",
        paper: "#F7F8FC",
        accent: "#4965E8",
        "accent-soft": "#EDEFFF",
        teal: "#168C82",
        amber: "#A96914"
      },
      boxShadow: {
        soft: "0 10px 35px rgba(24, 39, 75, 0.06)"
      }
    }
  },
  plugins: []
};
export default config;
