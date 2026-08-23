/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 聚合 API 基地址，默认 http://127.0.0.1:8000 */
  readonly VITE_API_BASE_URL?: string;
  /** 开发期默认 ADMIN_TOKEN（生产应通过设置页在浏览器本地配置） */
  readonly VITE_ADMIN_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
