/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Orbitron", "system-ui", "sans-serif"],
        body: ["DM Sans", "system-ui", "sans-serif"],
      },
      colors: {
        void: "#070b14",
        ember: "#ff9f1c",
        cyan: "#2ec4b6",
        plasma: "#7b5cff",
      },
      keyframes: {
        scorePop: {
          "0%": { opacity: "0", transform: "translateY(12px) scale(0.9)" },
          "20%": { opacity: "1", transform: "translateY(0) scale(1.05)" },
          "100%": { opacity: "0", transform: "translateY(-28px) scale(1)" },
        },
        pulseRing: {
          "0%,100%": { boxShadow: "0 0 0 0 rgba(46,196,182,0.45)" },
          "50%": { boxShadow: "0 0 0 12px rgba(46,196,182,0)" },
        },
        /** Phase 6.3 修订：深海式呼吸光核（无具象五官） */
        haloDeepBreath: {
          "0%,100%": { opacity: "0.34", transform: "scale(0.98)" },
          "50%": { opacity: "0.62", transform: "scale(1.04)" },
        },
        orbitDrift: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
        hudTick: {
          "0%,100%": { opacity: "0.055" },
          "50%": { opacity: "0.14" },
        },
        /** proactive：柔和琥珀双脉冲，避免廉价频闪 */
        emberSoft: {
          "0%,100%": { boxShadow: "0 0 0 0 rgba(255,159,28,0)" },
          "18%": { boxShadow: "0 0 18px 1px rgba(255,159,28,0.16)" },
          "32%": { boxShadow: "0 0 0 0 rgba(255,159,28,0)" },
          "48%": { boxShadow: "0 0 22px 2px rgba(255,159,28,0.2)" },
          "62%": { boxShadow: "0 0 0 0 rgba(255,159,28,0)" },
        },
      },
      animation: {
        scorePop: "scorePop 2.4s ease-out forwards",
        pulseRing: "pulseRing 2.2s ease-out infinite",
        haloDeepBreath: "haloDeepBreath 2.45s ease-in-out infinite",
        orbitDrift: "orbitDrift 14s linear infinite",
        orbitDriftSlow: "orbitDrift 22s linear infinite reverse",
        hudTick: "hudTick 3.4s ease-in-out infinite",
        emberSoft: "emberSoft 2.5s ease-out 1",
      },
    },
  },
  plugins: [],
};
