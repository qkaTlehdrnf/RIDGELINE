# Ridgeline 그래픽: 녹화, WebGL 뷰어, 동영상

엔진과 분리된 그래픽 계층이다. 엔진 코드는 바꾸지 않고, 경기를 돌리면서 매 시간(틱)의 상태를 파일로 떠 두고, 그 파일을 GPU로 그린다.

```
경기 ──(tools/record_replay.py)──> replay.rlr ──> tools/viewer_gl.html (브라우저, WebGL2, 마우스 조작)
                                              └─> tools/make_video.mjs (헤드리스 Chromium + ffmpeg → MP4)
```

## 1. 녹화

```bash
# 30진영 세계 지도, 리그 정책(진영마다 가장 최신 genN.py), 3,000시간. 모델 호출 없음
python tools/record_replay.py --world --seed 1 --hours 3000 --pol-dir runs/league_world --out runs/replays/world_s1.rlr
# 3진영 큰 지도, basic 정책
python tools/record_replay.py --seed 7 --hours 1500 --out runs/replays/s7.rlr
```

- 한 시간이 한 프레임이고, 프레임마다 **모든 유닛**의 위치, 종류, 병력, 경험, 사기, 제압, 준비도, 상태 단어, 신형/구형(mark), 편제, 목적지와 누가 누구를 쏘는지, 지역 소유, 요새, 비축 물자, 진영별 수치, 진영별 시야(지금 보이는 곳, 한 번이라도 본 곳), 이벤트(점령, 연구 결과, 항복, 조약 등)를 담는다.
- 앞 프레임과의 차이만 적고(24프레임마다 키 프레임) zlib으로 압축한다. 2만 유닛 세계전이 1,000시간에 약 45MB다.
- 녹화기는 `g.step()` 뒤에 공개 속성을 읽기만 한다. 엔진은 표적 목록을 남기지 않으므로 사격선은 "사거리 안 가장 가까운 적"(엔진의 첫 표적과 같은 규칙)으로 복원한다.
- 속도: 순수 파이썬 엔진 그대로라 세계전 한 시간에 약 0.5초가 든다. 3,000시간이 약 25~30분이다.

## 2. 뷰어 (실시간 1배속, 마우스로 자세히 보기)

```bash
python tools/view.py runs/replays/world_s1.rlr        # 로컬 서버를 띄우고 브라우저를 연다
```
또는 `tools/viewer_gl.html`을 브라우저로 열고 `.rlr` 파일을 끌어다 놓는다. Chrome이나 Edge 최신판(WebGL2)이 필요하다.

- **1배속 = 게임 2시간/초** (실시간 서버의 기본 속도). 0.5x~48x. 프레임 사이 유닛 위치를 보간해 60fps로 부드럽게 움직인다.
- **마우스**: 끌기 = 이동, 휠 = 확대/축소(커서 기준), 클릭 = 유닛 또는 지역 상세, 마우스를 올리면 요약.
  - 유닛 상세: 종류, 진영, 신형/구형(재정비 가능 여부), 상태, 병력, 경험(등급), 사기, 준비도, 제압, 보급, 사거리, 위치, 목적지(점선), 지금 쏘는 표적, 편제와 편제 경험.
  - 지역 상세: 소유, 지형, 고도, 요새 단계, 비축 물자, 산출(자원, 인력, 강철, 석유, 희귀), 그 지역의 유닛 구성, 진행 중인 돌격.
- 키: Space 재생/정지, ←/→ 하루 앞뒤, F 선택한 유닛 따라가기, Esc 선택 해제, Home 전체 지도.
- 오른쪽 패널: 진영 목록(영토 순), 영토 변화 그래프(클릭하면 그 시점으로), 진영을 누르면 그 진영만 강조. **Fog**를 켜면 그 진영이 실제로 보는 것만 보인다(탐사 안 한 땅은 검게, 지금 안 보이는 곳의 적 유닛은 숨김).
- 지도 모드: 정치(진영 색), 지형(기복 음영), 보급(비축 물자), 요새.
- 그리는 것: 지형 기복 음영, 해안선, 지역 경계와 진영 국경(빛나는 띠), 유닛 NATO식 부호(보병 X, 기갑 타원, 포병 점, 공병, 정찰, 대전차 등 14종), 병력 막대, 사격 예광선과 포구 섬광, 착탄, 돌격 화살표와 돌격 지점의 붉은 맥동, 수도 별, 도시 이름, 진영 이름, 사건 자막.
- 성능: 유닛은 인스턴싱 한 번, 지도는 전체 화면 셰이더 한 번이다. 4090이면 4K에서도 2만 유닛을 60fps로 그리는 데 여유가 크다. 무거운 부분은 프레임 압축 해제(프레임당 수 ms)인데 미리 풀어 둔다.

## 3. 동영상

```bash
npm i playwright && npx playwright install chromium      # 한 번만. ffmpeg가 PATH에 있어야 한다
node tools/make_video.mjs runs/replays/world_s1.rlr world.mp4 --speed 96 --size 1920x1080 --gpu           # 전체 전쟁 타임랩스
node tools/make_video.mjs runs/replays/world_s1.rlr front.mp4 --from 600 --to 680 --speed 2 --cam follow --gpu   # 1배속, 가장 큰 전투를 따라감
node tools/make_video.mjs runs/replays/world_s1.rlr de.mp4 --focus germania --fog --cam 600,90,14 --speed 8 --gpu # 한 진영의 시야로
```

- `--speed`는 영상 1초당 게임 시간이다(2 = 1배속). `--cam world | follow | X,Y,S`, `--zoom`, `--focus`, `--fog`, `--mode`, `--no-labels`, `--no-fire`.
- `--gpu`는 실제 그래픽 카드를 쓴다. 빼면 소프트웨어 렌더링이라 클라우드에서도 돌지만 720p에서 초당 1~2프레임 정도로 느리다.

## 4. 기타

```bash
python tools/rlr_tools.py info  world_s1.rlr
python tools/rlr_tools.py cut   world_s1.rlr part.rlr 600 900      # 일부 구간만 (첫 프레임을 키 프레임으로)
python tools/rlr_tools.py split part.rlr part 14                   # 14MB 조각으로. 뷰어는 ?src=part.000.bin,part.001.bin,... 로 이어 붙인다
```

파일 형식은 `tools/record_replay.py` 맨 위 설명에 있다. 다른 그래픽 엔진(Unity, Unreal, three.js 3D 등)도 같은 `.rlr`을 읽으면 된다.

한계: 경기를 실시간으로 녹화하며 동시에 보는 기능(라이브 스트리밍)은 아직 없다. 지금은 녹화가 끝난 파일을 본다. 엔진 자체가 2만 유닛에서 한 시간에 약 0.5초라, 2시간/초 실시간 진행에는 엔진의 numpy화가 먼저 필요하다.
