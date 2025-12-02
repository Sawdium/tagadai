# LeekWars API Reference

**Base URL**: `https://leekwars.com/api`

**Source**: Extracted from [leek-wars frontend](https://github.com/leek-wars/leek-wars) source code.

---

## Authentication

### Login
```
POST /farmer/login-token
Body: {"login": "username", "password": "password"}
Response: {"token": "jwt_token", "farmer": {...}}
```

All authenticated requests require:
```
Headers: {"Authorization": "Bearer <token>"}
```

### Logout
```
POST /farmer/disconnect
```

---

## Farmer Endpoints

### Get Farmer Info
```
GET /farmer/get/{farmer_id}
```

### Update Farmer
```
POST /farmer/update
```

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

## Leek Endpoints

### Get Leek Info
```
GET /leek/get/{leek_id}
```

### Get Leek Count
```
GET /leek/get-count
```

### Get Level Popup
```
GET /leek/get-level-popup/{leek_id}
```

### Set Leek AI
```
POST /leek/set-ai
Body: {"leek_id": id, "ai_id": id}
```

### Set Leek Hat
```
POST /leek/set-hat
Body: {"leek_id": id, "hat_id": id}
```

### Set In Garden
```
POST /leek/set-in-garden
Body: {"leek_id": id, "in_garden": true/false}
```

### Equipment Management
```
POST /leek/add-weapon
Body: {"leek_id": id, "weapon_id": id}

POST /leek/add-chip
Body: {"leek_id": id, "chip_id": id}

POST /leek/add-component
Body: {"leek_id": id, "component_id": id}

POST /leek/move-component
Body: {"leek_id": id, ...}
```

### Use Potion
```
POST /leek/use-potion
Body: {"leek_id": id, "potion_id": id}
```

### Spend Capital
```
POST /leek/spend-capital
Body: {"leek": id, "characteristics": {...}}
```

### Leek Registers (Persistent Storage)
```
GET /leek/get-registers/{leek_id}
POST /leek/set-register/{leek_id}/{key}/{value}
DELETE /leek/delete-register/{leek_id}/{key}
```

### Tournament Registration
```
POST /leek/register-tournament
Body: {"leek_id": id}

POST /leek/unregister-tournament
Body: {"leek_id": id}
```

### Battle Royale Registration
```
POST /leek/register-auto-br
Body: {"leek_id": id}

POST /leek/unregister-auto-br
Body: {"leek_id": id}
```

### Test Leek
```
POST /test-leek/new
POST /test-leek/update
```

---

## Garden (Fight) Endpoints

### Get Garden State
```
GET /garden/get
```

### Get Opponents
```
GET /garden/get-leek-opponents/{leek_id}
GET /garden/get-farmer-opponents
GET /garden/get-composition-opponents/{composition_id}
```

### Start Fights
```
POST /garden/start-solo-fight/{leek_id}/{enemy_id}
Response: {"fight": fight_id}

POST /garden/start-farmer-fight/{enemy_id}
Response: {"fight": fight_id}

POST /garden/start-team-fight/{composition_id}
Response: {"fight": fight_id}
```

### Challenge Endpoints
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

### Get Fight Results
```
GET /fight/get/{fight_id}
GET /fight/get/{fight_id}?logs=true  # Include debug output

Response when pending: {"winner": -1, ...}
Response when complete: {"winner": 0|1|2, "actions": [...], ...}
```

### Comment on Fight
```
POST /fight/comment
Body: {"fight_id": id, "comment": "..."}
```

---

## AI Code Endpoints

### Get All AI Files
```
GET /ai/get-farmer-ais
```

### Get AI Code
```
GET /ai/get/{ai_id}
Response: {"ai": {"code": "...", ...}}
```

### Create New AI
```
POST /ai/new/{folder_id}/false
Body: {"folder_id": id, "version": "11"}
Response: {"ai": {"id": new_id, ...}}
```

### Create New AI with Name
```
POST /ai/new-name
Body: {"folder_id": id, "name": "filename", "version": "11"}
```

### Rename AI
```
POST /ai/rename
Body: {"ai_id": id, "new_name": "name"}
```

### Save AI Code
```
POST /ai/save
Body: {"ai_id": id, "code": "leekscript_code"}
```

### AI Folder Management
```
POST /ai-folder/new/{parent_folder_id}
Body: {"folder_id": id}
Response: {"id": new_folder_id}

POST /ai-folder/new-name
Body: {"folder_id": id, "name": "foldername"}

POST /ai-folder/rename/{folder_id}/{new_name}
Body: {"folder_id": id, "new_name": "name"}
```

---

## Team Endpoints

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

### Get Item Templates
```
GET /market/get-item-templates
```

### Buy Items
```
POST /market/buy-habs
Body: {"item_id": "100-fights"}
```

### Sell Items
```
POST /market/sell-habs
```

### Mark Item Seen
```
POST /market/item-seen
```

---

## Message/Chat Endpoints

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

## Tournament Endpoints

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

## Ranking Endpoints

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

## Trophy Endpoints

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

## Forum Endpoints

### Get Categories
```
GET /forum/get-categories/{lang}
```

---

## Settings Endpoints

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

## Moderation Endpoints

### Get Warnings
```
GET /moderation/get-warnings/{farmer_id}
```

---

## Other Endpoints

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
