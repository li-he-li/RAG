# RAG Legal Similarity Search

娉曞緥鏂囦功鐩镐技妫€绱笌璇佹嵁婧簮绯荤粺銆傞」鐩寘鍚?FastAPI 鍚庣銆佸師鐢熼潤鎬佸墠绔紝浠ュ強鐢ㄤ簬璇勪及妫€绱㈣川閲忕殑绂荤嚎鑴氭湰銆?
## Structure

- `backend/`: FastAPI 鏈嶅姟銆佸悜閲忔绱€佹枃妗ｅ叆搴撱€佽瘎浼拌剼鏈?- `frontend/`: 鑱婂ぉ寮忔绱㈠墠绔?- `openspec/`: 闇€姹傘€佽璁°€佷换鍔℃媶瑙?- `鍚姩璇存槑.md`: 鏈湴涓枃鍚姩璇存槑
- `椤圭洰鏋舵瀯鍥?html`: 鏋舵瀯鎬昏鍥?
## Current Frontend

- 涓昏亰澶╃獥鍙ｆ敮鎸佹暟鎹簱璇佹嵁鏀拺鐨勬祦寮忓洖绛斻€?- 鍥炵瓟涓殑鈥滃紩鐢ㄦ潵婧愨€濅細鍦ㄨ亰澶╁尯鍙充晶灞曞紑鐙珛渚ф爮锛屾敮鎸佸叧闂拰妗岄潰绔嫋鎷借皟瀹姐€?- 宸︿晶鏍忓寘鍚€滃悎鍚屽鏌モ€濆叆鍙ｏ紝褰撳墠鐢ㄤ簬鏍囧噯妯℃澘鐩稿叧鑳藉姏鐨勫墠绔叆鍙ｉ鐣欍€?
## Environment

- Python 3.12
- Docker Desktop
- PostgreSQL 瀹瑰櫒 `legal-search-postgres`
- Qdrant 瀹瑰櫒 `legal-search-qdrant`

妯″瀷缂撳瓨鐩綍鏄?`backend/data/models_cache/`锛屽睘浜庤繍琛屼骇鐗╋紝涓嶇撼鍏ョ増鏈帶鍒躲€?
## Setup

1. 瀹夎鍚庣渚濊禆锛?
```powershell
cd backend
pip install -r requirements.txt
```

2. 澶嶅埗鐜鍙橀噺妯℃澘锛?
```powershell
Copy-Item .env.example .env
```

3. 鍚姩 Docker Desktop锛屽苟纭繚 PostgreSQL 涓?Qdrant 鍙闂€?
4. 鍚姩鍚庣锛?
```powershell
cd backend
D:\Anaconda\envs\legal-search\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

5. 鍚姩鍓嶇闈欐€侀〉锛?
```powershell
D:\Anaconda\python.exe -m http.server 3000 --bind 127.0.0.1 --directory frontend
```

## Local / Public Run Modes

- Existing command `python -m http.server 3000` still works.
- Frontend API base is now resolved from the current page host (`http://<current-host>:8000/api`) and can be overridden via `localStorage.apiBaseOverride`.

Use these scripts to switch by command:

```powershell
# Local debug (127.0.0.1 only)
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1

# Public/LAN mode (bind 0.0.0.0)
powershell -ExecutionPolicy Bypass -File scripts/start-public.ps1
```

For teacher access over Internet:
- Forward TCP `3000` and `8000` from router to this machine.
- Allow inbound firewall rules for `3000` and `8000`.
- Share `http://<your-public-ip>:3000/index.html`.
## Git Hooks

浠撳簱鍐呮彁渚?`.githooks/`锛屽寘鍚?`pre-commit`銆乣pre-push`銆乣commit-msg`銆?
鍚敤鏂瑰紡锛?
```powershell
git config core.hooksPath .githooks
```

Hook 璇存槑锛?
- `pre-commit`: 浠呮鏌ュ凡鏆傚瓨鏂囦欢锛岄樆姝㈡彁浜?`.env`銆佹ā鍨嬬紦瀛樸€佹棩蹇椼€乣__pycache__` 绛夊瀮鍦炬枃浠讹紝骞跺鏆傚瓨鐨?Python/JSON 鏂囦欢鍋氳娉曟牎楠屻€?- `pre-push`: 瀵逛粨搴撳唴 Python 鏂囦欢鍋氬叏閲忚娉曟牎楠岋紝鏍￠獙 JSON/JSONL 鏂囦欢缁撴瀯锛屽苟纭 README 涓寘鍚?hook 浣跨敤璇存槑銆?- `commit-msg`: 鏍￠獙 conventional commit锛屽厑璁哥殑绫诲瀷涓?`feat`銆乣fix`銆乣docs`銆乣style`銆乣refactor`銆乣test`銆乣chore`銆乣perf`銆乣ci`銆乣build`銆乣revert`銆?
蹇呰鏃跺彲鐢?`--no-verify` 璺宠繃 hook锛屼絾浠呴€傚悎绱ф€ユ儏鍐碉紝姝ｅ父寮€鍙戜笉搴斾緷璧栥€?
## Validation

鏈粨搴撶洰鍓嶆病鏈夊畬鏁磋嚜鍔ㄥ寲娴嬭瘯濂椾欢銆傛彁浜ゅ墠鑷冲皯鎵ц锛?
```powershell
python scripts/hook_checks.py pre-push
```

濡傛灉浣犻渶瑕侀獙璇佽繍琛岄摼璺紝鍐嶉澶栨鏌ワ細

- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:3000/index.html`

## Notes

- `backend/.env` 涓嶇撼鍏ョ増鏈帶鍒躲€?- `backend/data/models_cache/`銆佹棩蹇楁枃浠躲€佽В閲婂櫒缂撳瓨灞炰簬鏈湴杩愯浜х墿銆?- 褰撳墠鍓嶇渚濊禆鍚庣 `http://<current-host>:8000/api`銆?
## Recent Updates (2026-04)

- Chat composer now supports a shared upload entry that routes by mode:
  - `chat` mode uploads session attachments for normal conversation.
  - `contract-review` mode uploads review-target contracts.
- The left `鍚堝悓瀹℃煡` panel is now a standard template library:
  - Templates are uploaded, listed, and deleted through the dedicated left-side panel.
  - Template management is separate from session attachments and review-target files.
- The right sidebar is now tabbed (`Attachments` / `Citations`) and remains hidden by default.
  - It opens when attachments are uploaded or when citation sources are clicked.
  - Users can close the sidebar manually at any time.
- Contract review behavior is updated in OpenSpec:
  - Review requests are allowed even without uploaded contracts.
  - Backend should return an explicit "no contract available for review" result.

## Latest Behavior (2026-04-05)

- Contract review now waits for the user to send a review request before template matching starts.
- Template matching runs first through `GET /contract-review/template-recommendation`.
- The matched template options are rendered in the main chat stream instead of a separate area below the composer.
- Review generation starts only after the user clicks a template option, then streams through `POST /contract-review/stream`.
- The attachment tray now sits above the composer and shows removable session files across normal chat and contract-review mode.
- The right attachment sidebar now renders extracted text previews for current-session files, including PDF text when extraction succeeds.
- Session temp uploads use `/session-files/upload`, `/session-files`, and `/session-files/{file_id}` and stay outside the persistent template/document library.
- In normal chat mode, session `chat_attachment` files can now drive similar-case retrieval and are also passed into answer generation context for case-to-case similarity reasoning.
- Similar-case retrieval now selects query-relevant attachment chunks from the latest uploaded chat attachment instead of relying on a fixed leading text slice.
- All upload entries accept `.txt`, `.md`, `.pdf`, `.doc`, `.docx`, `.xls`, and `.xlsx`, subject to backend extraction availability.

## Opponent Prediction Mode (2026-04-06)

- A dedicated `opponent-prediction` mode is now available alongside normal chat and contract review.
- The left `观点预测` panel now acts as a case-template manager:
  - `案件名称` is required.
  - `案情材料` is required and persisted in the prediction domain tables.
  - `对方语料` is optional and persisted separately from the main document library.
- Prediction templates are stored outside the main `documents / paragraphs` search corpus.
- In chat, users first send a natural-language request, then choose a case template from the main chat stream.
- The backend prediction flow is independent from normal chat:
  - question understanding
  - case-profile reconstruction
  - opponent-oriented retrieval
  - opponent-viewpoint generation
  - opponent-style wording generation
- Prediction reports distinguish evidence-supported viewpoints from inference-only viewpoints and now include:
  - dynamic answer titles based on the user question
  - opponent-style statements (`对方可能会这样表述`)
  - priority labels such as `主打 / 次打 / 补充`

