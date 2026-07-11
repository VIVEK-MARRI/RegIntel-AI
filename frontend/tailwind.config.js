/** @type {import('tailwindcss').Config} */
export default {
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                brand: {
                    50: "#eff6ff",
                    100: "#dbeafe",
                    200: "#bfdbfe",
                    300: "#93c5fd",
                    400: "#60a5fa",
                    500: "#3b82f6",
                    600: "#2563eb",
                    700: "#1d4ed8",
                    800: "#1e40af",
                    900: "#1e3a8a",
                    950: "#172554",
                },
                surface: {
                    light: "#ffffff",
                    "light-2": "#f8fafc",
                    "light-3": "#f1f5f9",
                    dark: "#0b1120",
                    "dark-2": "#111827",
                    "dark-3": "#1f2937",
                },
                success: "#10b981",
                warning: "#f59e0b",
                danger: "#ef4444",
                info: "#0ea5e9",
            },
            fontFamily: {
                sans: [
                    "Inter",
                    "ui-sans-serif",
                    "system-ui",
                    "-apple-system",
                    "Segoe UI",
                    "Roboto",
                    "sans-serif",
                ],
                mono: [
                    "JetBrains Mono",
                    "ui-monospace",
                    "SFMono-Regular",
                    "monospace",
                ],
            },
            boxShadow: {
                elevated: "0 1px 2px 0 rgba(0,0,0,0.04), 0 4px 12px -2px rgba(0,0,0,0.08)",
                glow: "0 0 0 1px rgba(59,130,246,0.25), 0 0 24px rgba(59,130,246,0.15)",
            },
            borderRadius: {
                xl: "0.875rem",
                "2xl": "1.125rem",
            },
            animation: {
                "pulse-soft": "pulse 2.4s cubic-bezier(0.4,0,0.6,1) infinite",
                shimmer: "shimmer 2s linear infinite",
            },
            keyframes: {
                shimmer: {
                    "0%": { backgroundPosition: "-200% 0" },
                    "100%": { backgroundPosition: "200% 0" },
                },
            },
        },
    },
    plugins: [],
};
