# 짧은 주소 `https://mctaki23-glitch.github.io/` 설정

이 폴더는 계정 대표 사이트 저장소 **`mctaki23-glitch.github.io`** 에 그대로 올릴 파일입니다.
저장소 생성은 계정 소유자만 할 수 있습니다(GitHub 연동 토큰으로는 403).

1. https://github.com/new 에서 Repository name 을 정확히 `mctaki23-glitch.github.io` 로, **Public** 으로 만든다(README 추가 불필요).
2. Claude GitHub 앱이 "선택한 저장소만" 접근하도록 설정되어 있으면 이 저장소도 허용 목록에 추가한다.
3. 이 폴더의 파일(`index.html`, `404.html`, `README.md`, `.nojekyll`, `.github/workflows/pages.yml`)을 그 저장소의 `main` 루트에 푸시한다.
   - Claude 세션에 "저장소 만들었어" 라고 알리면 자동으로 푸시·배포 확인까지 진행한다.
   - 직접 할 경우: 웹 UI 의 "Add file → Upload files" 로 올려도 된다(`.github/workflows/pages.yml` 은 폴더 경로 그대로).
4. 첫 푸시 시 `Deploy user site` 워크플로가 Pages 를 자동 활성화하고 배포한다(약 1분).
5. 확인: `https://mctaki23-glitch.github.io/` → 최신 브리핑, `https://mctaki23-glitch.github.io/2026-09-11` → 그날 브리핑.
