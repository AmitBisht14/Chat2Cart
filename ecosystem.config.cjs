const RESTART_BACKOFF_MS = 1000;

function app(name, settings) {
  return {
    name,
    autorestart: true,
    exp_backoff_restart_delay: RESTART_BACKOFF_MS,
    out_file: `logs/${name}.out.log`,
    error_file: `logs/${name}.err.log`,
    merge_logs: true,
    time: true,
    ...settings,
  };
}

module.exports = {
  apps: [
    app("chat2cart-listener", { script: "listener/dist/index.js" }),
    app("chat2cart-agent", {
      script: "uv",
      args: "run --directory agent python -m chat2cart.app",
      interpreter: "none",
    }),
  ],
};
