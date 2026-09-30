import { defineConfig } from '@playwright/test'

// 화면 자동 테스트 (npm run test:e2e)
// - 서버 API 는 e2e/mock.ts 의 가짜 응답으로 대신한다: 실제 DB·계정·운영 서버에 접속하지 않는다.
// - PC 에 설치된 Edge 를 쓴다 (브라우저 별도 설치 불필요). Chrome 을 쓰려면 E2E_BROWSER=chrome
// - 개발 서버(vite dev)는 화면 파일을 요청 때마다 변환해 동시 실행 시 느려지므로, 배포와 같은 빌드 결과를
//   별도 폴더(.e2e-dist, git 제외)에 만들어 띄운다. 운영 서버가 쓰는 dist 는 건드리지 않는다.
const PORT = 5199
const OUT = '.e2e-dist'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: 4,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: process.env.E2E_BROWSER || 'msedge',
    headless: true,
    viewport: { width: 1440, height: 900 },
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npx vite build --outDir ${OUT} --emptyOutDir --logLevel warn && npx vite preview --outDir ${OUT} --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
