import {
  defineRailway,
  github,
  preserve,
  project,
  service,
  volume,
} from "railway/iac";

// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "mini-ai";

export default defineRailway(() => {
  const miniAi = service("mini-ai", {
    source: github("getkcoin-alt/mini-ai", {
      branch: "feat/mini-ai-vault-service",
    }),
    env: {
      APP_ENV: preserve(),
      LLM_API_KEY: preserve(),
      LLM_BASE_URL: preserve(),
      LLM_MODEL: preserve(),
      LLM_REQUIRED: preserve(),
      LOG_LEVEL: preserve(),
      MINI_ADMIN_API_KEY: preserve(),
      MINI_DATA_DIR: preserve(),
      VAULT_API_KEY: preserve(),
      VAULT_MCP_REQUIRED: preserve(),
      VAULT_MCP_URL: preserve(),
      VAULT_TIMEOUT_SECONDS: preserve(),
    },
    healthcheck: "/health/live",
    healthcheckTimeout: 30,
    replicas: 1,
    volumeMounts: {
      "/data": volume("mini-ai-data", { sizeMB: 1024 }),
    },
  });
  return project("vault-zeta", {
    resources: [miniAi],
  });
});
