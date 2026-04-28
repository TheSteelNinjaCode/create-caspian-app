const isWatchMode = process.env.PP_POSTCSS_MODE === "watch";

export default {
  plugins: {
    "@tailwindcss/postcss": {},
    ...(isWatchMode ? {} : { cssnano: {} }),
  },
};
