/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTH_ENABLED?: string;
  readonly VITE_BASENAME?: string;
  readonly VITE_LLM_PROVIDER?: string;
  readonly VITE_RERANKER_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
