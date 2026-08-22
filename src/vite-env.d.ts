/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 백엔드 서버 루트 주소 (예: http://127.0.0.1:8765). 끝에 슬래시 없음. */
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
