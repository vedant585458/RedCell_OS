/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
  readonly VITE_APP_VERSION?: string;
  readonly VITE_ENVIRONMENT?: "development" | "staging" | "production" | "test";
  readonly VITE_ENABLE_2D_CANVAS?: string;
  readonly VITE_ENABLE_MOCK_TARGET?: string;
  readonly VITE_ENABLE_TERMINAL_LOGS?: string;
  readonly VITE_ENABLE_POC_VERIFICATION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
