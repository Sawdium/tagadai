# LeekWars API Reference

**Base URL**: `https://leekwars.com/api`

**Source**: Extracted from [leek-wars frontend](https://github.com/leek-wars/leek-wars) source code, then re-probed against the live 2026 API.

---

## Verification status (2026)

The LeekWars API migrated AI files from integer IDs to path strings at some
point before April 2026. During that migration **every AI-related endpoint
in this doc was renamed or retyped**. Every AI/AI-folder/garden/fight/leek-
equipment/test-scenario/test-leek endpoint we call from `src/common/api.py`
has now been round-trip verified against a live account (tagadai).

Each section below and each method in `src/common/api.py` carries a tag:

| Tag | Meaning |
|---|---|
| **[VERIFIED]** | Exercised with a successful round-trip against the live 2026 API. |
| **[UNVERIFIED]** | Never re-tested — deliberately skipped because the call irreversibly consumes a resource (potion, capital, habs). Payload shape is pre-2026 best-effort. |
| **[SUSPECT]** | Historical doc and live code disagree about payload; neither side has been exercised. |

### Verified (safe to rely on)

Authentication / farmer:
- `POST /farmer/login-token` · `GET /farmer/get-from-token` · `GET /farmer/get/{id}`

Garden / fight:
- `GET /garden/get` · `GET /garden/get-leek-opponents/{id}` · `GET /garden/get-farmer-opponents`
- `POST /garden/start-solo-fight` (body `{leek_id, target_id}`) · `POST /garden/start-farmer-fight` (body `{target_id}`)
- `GET /fight/get/{id}` · `GET /fight/get-logs/{id}`

AI files (path-based):
- `POST /ai/read` · `POST /ai/write` · `POST /ai/create`
- `POST /ai/rename` · `POST /ai/move`
- `DELETE /ai/delete` · `POST /ai/restore` · `DELETE /ai/bin` (empty-bin)

AI folders (path-based):
- `POST /ai-folder/create` · `POST /ai-folder/rename` · `DELETE /ai-folder/delete`

Test scenarios / test leeks:
- `GET /test-scenario/get-all`
- `POST /test-scenario/new` · `POST /test-scenario/update` (body `{id, data:<json>}`) · `DELETE /test-scenario/delete` (body `{id}`)
- `POST /test-scenario/add-leek` · `DELETE /test-scenario/delete-leek`
- `POST /test-leek/new` · `POST /test-leek/update` (full blob) · `DELETE /test-leek/delete` (body `{id}`)
- `POST /ai/test-scenario` (ai_id accepts paths)

Leek:
- `GET /leek/get/{id}` — full leek data incl. equipment and characteristic values

Loadouts (équipements — native build presets; see `src/tools/loadout.py`):
- `GET /loadout/get-all` → `{loadouts:[{id,name,icon,weapons[],forgotten_weapons[],chips[],components[],stats{},order}], owned_weapons[], owned_chips[]}`
- `POST /loadout/create` (body `{name, icon, weapons:<json>, chips:<json>, components:<json>, stats:<json>}`) → `{set:{...}}`
- `PUT /loadout/update` (body `{set_id, name, icon, weapons, chips, components, stats}`) → `{set:{...}}`
- `DELETE /loadout/delete` (body `{set_id}`)
- `POST /loadout/apply` (body `{set_id, leek_id, use_restat}`) — equips the whole build onto a leek; `use_restat=true` also reallocates capital (consumes a restat potion). Native replacement for the old manual strip/restat/re-equip flow.

Loadout payload notes (verified by round-trip):
- `weapons`/`chips` are template-id arrays. Send all weapons in `weapons`; the server moves non-storable ones (illicit 115-119, reward 175/225/506) to `forgotten_weapons`.
- `components` are `{index, template}` objects (slot 0-7). `apply` reinstalls them on the leek, so they must be present or the leek loses its cores/ram/stat hardware.
- `stats` values are **capital points** per characteristic, not the characteristic value. `loadout.py` converts value→capital via the LeekWars COSTS table (validated: every level-301 leek totals 2113 capital).

All **team / ranking / chat / forum / message / tournament / trophy / moderation / settings** endpoints below are also **[UNVERIFIED]** — they are not called from `src/common/api.py`, so no verification has been attempted.

### Suspect (live code disagrees with historical doc)

- `POST /market/buy-habs` (historical) vs `POST /market/buy-habs-quantity` (`api.py`) — at least one is stale.
- `POST /leek/set-ai` — body has `ai_id` per pre-2026 doc; since AI is now path-keyed and `POST /ai/test-scenario` accepts paths via `ai_id`, this probably also takes a path. Not probed.

### Known-gone (returned `no_such_service` during probing)

- `GET /ai/get-farmer-ais` — replaced by `farmer.ai_tree` embedded in login
- `GET /ai/get/{ai_id}` (path variant) — only numeric `ai_id` is accepted; no path resolution
- `POST /ai/save` — replaced by `POST /ai/write`
- `POST /ai/new-name` · `POST /ai/new/{folder_id}/false` — replaced by `POST /ai/create`
- `POST /ai/change-folder` — replaced by `POST /ai/move`
- `POST /ai-folder/new` · `POST /ai-folder/new-name` · `POST /ai-folder/rename/{id}/{name}` — replaced by path-based `ai-folder/create` + `rename`
- `GET /farmer/get` (no id) — now requires a farmer_id path segment; use `GET /farmer/get-from-token` for auth-based refresh
- `GET /farmer/get-ai-tree` — never existed; ai_tree is embedded in login response
- `POST /ai/empty-bin` · `DELETE /ai/empty-bin` · `DELETE /ai/delete-from-bin` — replaced by `DELETE /ai/bin` (no body)

---

## Authentication

### Login — [VERIFIED]
```
POST /farmer/login-token
Body: {"login": "username", "password": "password"}
Response: {"token": "jwt_token", "farmer": {...}}
```

All authenticated requests require:
```
Headers: {"Authorization": "Bearer <token>"}
```

The login response embeds `farmer.ai_tree` — there is no separate list-AI endpoint.

### Logout — [UNVERIFIED]
```
POST /farmer/disconnect
```

---

## Farmer Endpoints — [mixed — see per-endpoint tags]

> All sub-endpoints below that lack an explicit tag are **[UNVERIFIED]** —
> inherited from pre-2026 extraction of the leek-wars frontend source and
> never re-tested since the API migration.

### Get Farmer Info — [VERIFIED]
```
GET /farmer/get/{farmer_id}
GET /farmer/get-from-token          # refresh via bearer token
```
Note: `GET /farmer/get` without an id returns `wrong_parameter_count` in the 2026 API.

### Update Farmer — [UNVERIFIED]
```
POST /farmer/update
```
Probing this with GET returned `service_not_implemented`. Method/shape unverified.

### Set Avatar (Upload Profile Picture)
```
POST /farmer/set-avatar
Content-Type: multipart/form-data
Body: FormData with 'avatar' field containing image file
Response: {"avatar_changed": timestamp}

Accepted formats: PNG, JPEG, JPG, BMP, GIF, WEBP
Max size: 10 MB
```

### Set Language
```
PUT /farmer/set-language
```

### Set Website
```
POST /farmer/set-website
Body: {"website": "https://..."}
```

### Set GitHub
```
POST /farmer/set-github
Body: {"github": "username"}
```

### Change Country
```
POST /farmer/change-country
Body: {"country": "FR"}
```

### Set In Garden (Online Status)
```
POST /farmer/set-in-garden
Body: {"in_garden": true/false}
```

### Change Password
```
POST /farmer/change-password
Body: {"password": "current", "new_password": "new"}
```

### Change Email
```
POST /farmer/change-email1
```

### Register for Farmer Tournament
```
POST /farmer/register-tournament
```

### Unregister from Farmer Tournament
```
POST /farmer/unregister-tournament
```

### Delete Account
```
POST /farmer/unregister
Body: {"password": "...", "delete_forum_messages": true/false}

POST /farmer/unregister-fast  # Quick delete
```

### Verify Account
```
POST /farmer/verify
POST /farmer/verify-github
```

### Login with GitHub
```
GET /farmer/login-github
```

### Login Comeback
```
POST /farmer/login-comeback
```

---

## Leek Endpoints — [mixed — see per-endpoint tags]

> All sub-endpoints below that lack an explicit tag are **[UNVERIFIED]**.

### Get Leek Info — [VERIFIED]
```
GET /leek/get/{leek_id}
```

### Get Leek Count — [UNVERIFIED]
```
GET /leek/get-count
```

### Get Level Popup — [UNVERIFIED]
```
GET /leek/get-level-popup/{leek_id}
```

### Set Leek AI — [SUSPECT]
```
POST /leek/set-ai
Body: {"leek_id": id, "ai_id": id}
```
The `ai_id` field name is inherited from the pre-migration API. Since AI files are now path-keyed, this body most likely now expects `{"leek_id": id, "ai": "path/to/ai"}` — or maybe `ai_id` still accepts a path string (as `POST /ai/test-scenario` does). Not probed.

### Set Leek Hat — [UNVERIFIED]
```
POST /leek/set-hat
Body: {"leek_id": id, "hat_id": id}
```

### Set In Garden — [UNVERIFIED]
```
POST /leek/set-in-garden
Body: {"leek_id": id, "in_garden": true/false}
```

### Equipment & Stat Changes — use Loadouts

Per-item equipping (`add/remove-weapon|chip|component`), `use-potion` and
`spend-capital` are no longer used — a whole build (gear + restat) is applied in
one call via the **Loadout** endpoints documented above (`loadout/apply`). See
`src/tools/loadout.py`.

### Leek Registers (Persistent Storage) — [UNVERIFIED]
```
GET /leek/get-registers/{leek_id}
POST /leek/set-register/{leek_id}/{key}/{value}
DELETE /leek/delete-register/{leek_id}/{key}
```

### Tournament Registration — [UNVERIFIED]
```
POST /leek/register-tournament
Body: {"leek_id": id}

POST /leek/unregister-tournament
Body: {"leek_id": id}
```

### Battle Royale Registration — [UNVERIFIED]
```
POST /leek/register-auto-br
Body: {"leek_id": id}

POST /leek/unregister-auto-br
Body: {"leek_id": id}
```

### Test Leek — [VERIFIED]
```
POST /test-leek/new
Body: {"name": "..."}
Response: {"id": <negative_int>, "data": {skin, level, life, strength, ...}}

POST /test-leek/update
Body: {"id": <negative_int>, "data": <JSON blob with ALL fields>}
Response: []
# IMPORTANT: partial updates fail with {error: missing_field}. Start from
# the create response's `data`, merge changes, send the whole thing.

DELETE /test-leek/delete
JSON body: {"id": <negative_int>}
Response: []
```

---

## Garden (Fight) Endpoints

### Get Garden State — [VERIFIED]
```
GET /garden/get
```

### Get Opponents — [VERIFIED for leek/farmer variants]
```
GET /garden/get-leek-opponents/{leek_id}
GET /garden/get-farmer-opponents
GET /garden/get-composition-opponents/{composition_id}   # [UNVERIFIED]
```

### Start Fights — [VERIFIED for solo & farmer; team untested]
```
POST /garden/start-solo-fight
Body: {"leek_id": <id>, "target_id": <enemy_id>}
Response: {"fight": <fight_id>}
# Consumes 1 fight from the daily pool.

POST /garden/start-farmer-fight
Body: {"target_id": <enemy_id>}
Response: {"fight": <fight_id>}
# Consumes 1 fight from the daily pool.

POST /garden/start-team-fight      # [UNVERIFIED]
```
Old doc listed URL path segments for these — that shape is stale.
Body-form shape above is verified.

### Challenge Endpoints — [UNVERIFIED]
```
GET /garden/get-solo-challenge/{leek_id}
GET /garden/get-farmer-challenge/{farmer_id}
GET /garden/get-team-challenge/{team_id}

POST /garden/start-solo-challenge
POST /garden/start-farmer-challenge
POST /garden/start-team-challenge
```

---

## Fight Endpoints

### Get Fight Results — [VERIFIED]
```
GET /fight/get/{fight_id}
GET /fight/get/{fight_id}?logs=true  # Include debug output

Response when pending: {"winner": -1, ...}
Response when complete: {"winner": 0|1|2, "actions": [...], ...}
```

### Comment on Fight — [UNVERIFIED]
```
POST /fight/comment
Body: {"fight_id": id, "comment": "..."}
```

---

## AI Code Endpoints (path-based, 2026 API)

AI files and folders are identified by their full path string (e.g. `main`,
`Model/Combos/Action`). Integer IDs are no longer used.

### Get AI Tree — [VERIFIED]
The full AI tree is embedded in the login response under `farmer.ai_tree`:
```
ai_tree = {
    "files":   [{path, mtime, valid, version, strict, entrypoint,
                 total_lines, total_chars, scenario}, ...],
    "folders": ["AI", "AI/Algorithms", "Model/Combos", ...],
    "bin":     [{path, valid, version}, ...],
    "leek_ais": {"<leek_id>": "<ai_path>", ...}
}
```
To refresh after mutations call `GET /farmer/get-from-token` (auth-only, no id).
`GET /farmer/get` without an id responds `wrong_parameter_count`.

### Read AI Code — [VERIFIED]
```
POST /ai/read
Body: {"path": "main"}
Response: {"code": "..."}
```

### Write AI Code — [VERIFIED]
```
POST /ai/write
Body: {"path": "main", "code": "..."}
Response: {"result": {...compile diagnostics...}, "modified": <ms_epoch>}
```

### Create New AI — [VERIFIED]
```
POST /ai/create
Body: {"folder": "Model/Combos", "name": "NewFile", "version": "4"}
Response: {"path": "Model/Combos/NewFile", "code": "<default template>"}
```
Use `folder: ""` to create at root. `folder: "/"` responds `invalid_path`.

### Rename AI — [VERIFIED]
```
POST /ai/rename
Body: {"path": "main", "new_name": "mainBackup"}
Response: {"path": "mainBackup"}
```
`new_name` is a bare filename (no slash); the parent folder is preserved.
Renaming to the same name fails with `name_conflict`.

### Move AI — [VERIFIED]
```
POST /ai/move
Body: {"path": "main", "dest": "Archive"}
Response: {"path": "Archive/main"}
```
Use `dest: ""` to move to root. `dest: "/"` responds `invalid_path`.

### Delete AI (to bin) — [VERIFIED]
```
DELETE /ai/delete
JSON body: {"path": "main"}
Response: {"trash_name": "main"}
```

### Restore from bin — [VERIFIED]
```
POST /ai/restore
Body: {"trash_name": "main"}
Response: {"path": "main"}
```
List bin contents via `ai_tree.bin`.

### Empty bin — [VERIFIED]
```
DELETE /ai/bin
(no body)
Response: []
```
Permanent — every item in the bin is purged irretrievably.

### AI Folder Management — [VERIFIED]
```
POST /ai-folder/create
Body: {"path": "Model/NewFolder"}
Response: []
# Creates a single level; the parent path must already exist.

POST /ai-folder/rename
Body: {"path": "Model/NewFolder", "new_name": "Renamed"}
Response: {"path": "Model/Renamed"}

DELETE /ai-folder/delete
JSON body: {"path": "Model/NewFolder"}
Response: {"trash_name": "Model/NewFolder"}
# Folder must be empty; if a file was just moved out, wait ~1s before
# calling to avoid sporadic `internal_error` from server-side race.
```

### Test Fights — [VERIFIED]
```
POST /ai/test-scenario
Body: {"ai_id": "main", "scenario_id": 0}
Response: {"fight": <fight_id>}
```
The `ai_id` key name is legacy — it now accepts path strings
(tested with `ai_id="main"` → fight created successfully).

---

## Team Endpoints — [all UNVERIFIED]

### Create Team
```
POST /team/create
Body: {"name": "...", ...}
```

### Get Team Rankings
```
GET /team/rankings/{team_id}
```

### Manage Members
```
POST /team/accept-candidacy
POST /team/reject-candidacy
POST /team/cancel-candidacy
POST /team/cancel-candidacy-for-team
POST /team/send-candidacy

POST /team/change-member-grade
POST /team/change-owner
POST /team/ban
POST /team/quit
```

### Team Settings
```
POST /team/set-opened
Body: {"opened": true/false}

POST /team/set-emblem
Content-Type: multipart/form-data
Body: FormData with emblem image
```

### Compositions
```
POST /team/create-composition
POST /team/move-leek
```

### Team Tournament
```
POST /team/register-tournament
POST /team/unregister-tournament
```

### Dissolve Team
```
POST /team/dissolve
```

---

## Market Endpoints

### Get Item Templates — [VERIFIED]
```
GET /market/get-item-templates
```

### Buy Items — [SUSPECT]
```
POST /market/buy-habs
Body: {"item_id": "100-fights"}
```
Historical doc lists `/market/buy-habs`; `src/common/api.py` calls `/market/buy-habs-quantity` with `{item_id, quantity}`. Neither has been exercised — at least one of the two is stale.

### Sell Items — [UNVERIFIED]
```
POST /market/sell-habs
```

### Mark Item Seen — [UNVERIFIED]
```
POST /market/item-seen
```

---

## Message/Chat Endpoints — [all UNVERIFIED]

### Create Conversation
```
POST /message/create-conversation
```

### Send Message
```
POST /message/send-message
```

### Find Conversation
```
GET /message/find-conversation/{farmer_id}
```

### Mark as Read
```
POST /message/read
```

### Moderation
```
POST /message/censor
POST /message/mute
```

### Reactions
```
POST /message-reaction/add
```

---

## Tournament Endpoints — [all UNVERIFIED]

### Get Tournament Range
```
GET /tournament/range-leek/{leek_id}
GET /tournament/range-farmer/{farmer_id}
GET /tournament/range-compo/{composition_id}
GET /tournament/range-br/{leek_id}
```

### Tournament Actions
```
POST /tournament/comment
POST /tournament/generate
```

---

## Ranking Endpoints — [all UNVERIFIED]

### Get Rankings
```
GET /ranking/{type}
GET /ranking/fun
GET /ranking/get-home-ranking
```

### Get Specific Rank
```
GET /ranking/get-leek-rank{active}/{id}/{order}
GET /ranking/get-farmer-rank{active}/{id}/{order}
GET /ranking/get-team-rank{active}/{id}/{order}
```

### Search
```
POST /ranking/search
Body: {"query": "..."}
```

---

## Trophy Endpoints — [all UNVERIFIED]

### Get Farmer Trophies
```
GET /trophy/get-farmer-trophies/{farmer_id}
```

### Unlock Trophy
```
POST /trophy/unlock
Body: {"trophy_id": id}
```

### Give Trophy (Admin)
```
POST /trophy/give
Body: {"farmer_id": id, "trophy_id": id}
```

---

## Forum Endpoints — [all UNVERIFIED]

### Get Categories
```
GET /forum/get-categories/{lang}
```

---

## Settings Endpoints — [all UNVERIFIED]

### Get Settings
```
GET /settings/get-settings
```

### Update Setting
```
POST /settings/update-setting
Body: {"setting": "key", "value": "value"}
```

---

## Moderation Endpoints — [all UNVERIFIED]

### Get Warnings
```
GET /moderation/get-warnings/{farmer_id}
```

---

## Other Endpoints — [all UNVERIFIED]

### Country List
```
GET /country/get-all
```

### Changelog
```
GET /changelog/get/{version}
```

### Encyclopedia
```
GET /encyclopedia/get-all-locale/{locale}
```

### LeekScript Functions
```
GET /function/get-all
GET /function/doc/{locale}
```

### Push Notifications
```
POST /push-endpoint/register
```

---

## Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request |
| 401 | Unauthorized (invalid/missing token) |
| 403 | Forbidden |
| 404 | Not Found |
| 429 | Rate Limited |

## Error Response Format
```json
{
  "error": "error_code",
  "message": "Human readable message"
}
```

---

## Notes

- API version uses LeekScript version numbers (e.g., "11" = v1.1)
- File uploads use multipart/form-data
- Most POST endpoints require authentication
- Poll fight results until `winner != -1`
