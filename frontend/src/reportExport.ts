// A4 가로 한 장 보고서(판매 현황 보고서 · AI 주간 브리핑) 저장: PDF(브라우저 인쇄) · PNG
//
// PDF: 보고서만 body 바로 아래(#print-host)로 복사해 인쇄한다. 앱 화면을 숨기기만 하면(visibility) 앱 전체 길이만큼
//      빈 페이지가 생기고 고정 위치 보고서가 페이지마다 반복된다 (예전 7장 문제).
// PNG: html-to-image 는 화면의 계산된 크기(높이 포함)를 그대로 복사하므로 글꼴이 바뀌면 글자가 넘쳐 겹친다.
//      화면과 같은 Pretendard 를 넣어서 그린다 — 보고서에 쓰인 글자가 들어 있는 글꼴 조각(unicode-range)만 골라 넣는다.

export function printReport(node: HTMLElement, title: string) {
  document.getElementById('print-host')?.remove()
  const host = document.createElement('div')
  host.id = 'print-host'
  host.appendChild(node.cloneNode(true))
  document.body.appendChild(host)
  const prev = document.title
  document.title = title
  const done = () => {
    host.remove()
    document.title = prev
    window.removeEventListener('afterprint', done)
  }
  window.addEventListener('afterprint', done)
  window.print()
  window.setTimeout(done, 1000)          // afterprint 를 주지 않는 브라우저 대비 (Chrome 은 인쇄 창이 닫힐 때까지 print() 가 멈춘다)
}

type Range = [number, number]

function parseRanges(s: string): Range[] {
  return s.split(',').map((p) => p.trim().replace(/^U\+/i, '')).filter(Boolean).map((p) => {
    if (p.includes('?')) return [parseInt(p.replace(/\?/g, '0'), 16), parseInt(p.replace(/\?/g, 'F'), 16)] as Range
    const [a, b] = p.split('-')
    return [parseInt(a, 16), parseInt(b ?? a, 16)] as Range
  })
}

const dataUrl = (blob: Blob) => new Promise<string>((ok, fail) => {
  const r = new FileReader()
  r.onload = () => ok(String(r.result))
  r.onerror = () => fail(r.error)
  r.readAsDataURL(blob)
})

const fileCache = new Map<string, Promise<string>>()
let cssCache: Promise<{ href: string; text: string } | null> | null = null

function fontCss(): Promise<{ href: string; text: string } | null> {
  if (!cssCache) {
    const link = document.querySelector<HTMLLinkElement>('link[rel="stylesheet"][href*="pretendard"]')
    cssCache = link
      ? fetch(link.href).then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status))))).then((text) => ({ href: link.href, text }))
        .catch(() => { cssCache = null; return null })
      : Promise.resolve(null)
  }
  return cssCache
}

/** 보고서 글자에 필요한 Pretendard 조각만 data URL 로 넣은 @font-face CSS (실패하면 undefined → 기본 글꼴) */
export async function reportFontCss(node: HTMLElement): Promise<string | undefined> {
  const css = await fontCss()
  if (!css) return undefined
  const used = new Set<number>()
  for (const ch of (node.innerText || node.textContent || '') + '0123456789.,%+-~·') used.add(ch.codePointAt(0)!)
  const codes = [...used]
  const faces = css.text.match(/@font-face\s*{[^}]*}/g) ?? []
  const keep = faces.filter((f) => {
    const m = /unicode-range\s*:\s*([^;}]+)/i.exec(f)
    if (!m) return true
    const rs = parseRanges(m[1])
    return codes.some((c) => rs.some(([a, b]) => c >= a && c <= b))
  })
  const out = await Promise.all(keep.map(async (f) => {
    const m = /url\(\s*['"]?([^'")]+)['"]?\s*\)\s*format\(\s*['"]?woff2['"]?\s*\)/i.exec(f) ?? /url\(\s*['"]?([^'")]+)['"]?\s*\)/i.exec(f)
    if (!m) return null
    const url = new URL(m[1], css.href).href
    if (!fileCache.has(url)) fileCache.set(url, fetch(url).then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status))))).then(dataUrl))
    try {
      const data = await fileCache.get(url)!
      return f.replace(/src\s*:[^;}]+/i, `src: url(${data}) format('woff2')`)
    } catch {
      fileCache.delete(url)
      return null
    }
  }))
  const ok = out.filter((x): x is string => !!x)
  return ok.length ? ok.join('\n') : undefined
}

export async function saveReportPng(node: HTMLElement, fileName: string) {
  const { toPng } = await import('html-to-image')
  await document.fonts?.ready
  const fontEmbedCSS = await reportFontCss(node)
  const url = await toPng(node, { pixelRatio: 2, backgroundColor: '#ffffff', cacheBust: true, style: { boxShadow: 'none', margin: '0' }, ...(fontEmbedCSS ? { fontEmbedCSS } : { skipFonts: true }) })
  const a = document.createElement('a')
  a.href = url
  a.download = `${fileName}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
}
