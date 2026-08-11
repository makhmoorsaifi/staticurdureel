# GitHub Actions par free automation -- setup guide

Isse laptop/internet hamesha on rakhne ki zaroorat nahi -- sab GitHub ke
apne free servers (Actions) par chalega. Tumhara kaam sirf itna: Google
Drive ke `staticurdureels` folder me reels daalte rehna.

**Zaroori: repo PRIVATE banao.** `token.json` (Instagram access token) is
repo me commit hota hai taaki har run ke beech persist rahe -- isliye
public repo bilkul mat banana.

---

## 1) Repo banao aur code push karo

```
git init
git add .
git commit -m "Initial commit"
```

Phir GitHub par ek naya **private** repo banao aur usse push kar do
(GitHub khud commands dikha dega `git remote add origin ...` wali).

---

## 2) Supabase (free video hosting) -- one-time setup

1. https://supabase.com par free account banao.
2. New Project banao (free tier, card nahi chahiye).
3. Left sidebar -> **Storage** -> New bucket -> naam `reels` rakho ->
   **Public** bucket toggle ON karo.
4. Left sidebar -> **Project Settings -> API** -> yahan se do cheezein
   copy karo:
   - **Project URL** (jaise `https://xxxxxxxx.supabase.co`)
   - **service_role key** (secret wala, `anon` key nahi)

---

## 3) Google Drive service account -- one-time setup

`drive_sync.py` ke top comment me poora tarika likha hai, short me:

1. https://console.cloud.google.com -> naya project -> "Google Drive
   API" enable karo.
2. Credentials -> Create Credentials -> Service Account -> koi bhi naam.
3. Us service account ki Keys tab -> Add Key -> JSON -> download hoga.
4. Downloaded JSON ke andar `client_email` copy karo.
5. Apne Drive ke `staticurdureels` folder ko us email ke sath **Viewer**
   access se share karo.
6. Folder ka URL khोlो browser me -- `/folders/` ke baad wala part hi
   `drive_folder_id` hai.

Is downloaded JSON ki **poori file content** copy karke rakh lo -- step 4
me GitHub secret me daalni hai.

---

## 4) GitHub repo Secrets add karo

Repo -> **Settings -> Secrets and variables -> Actions -> New repository
secret** -- ye sab add karo:

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Step 3 wali poori downloaded JSON file content |
| `DRIVE_FOLDER_ID` | Step 3.6 wali folder ID |
| `SUPABASE_URL` | Step 2 ka Project URL |
| `SUPABASE_KEY` | Step 2 ka service_role key |
| `IG_USER_ID` | Tumhara Instagram professional account ID (config.py me pehle se ho sakta hai) |
| `META_APP_ID` | Meta developer app ID |
| `META_APP_SECRET` | Meta developer app secret |

---

## 5) `token.json` ek baar commit karo

Local machine par jo `token.json` pehle se kaam kar raha hai (ya jo
`get_long_lived_token.py` se banaya tha), wahi file repo me commit kar
do -- isse GitHub Actions ko pehla valid token mil jaayega, uske baad
`token_refresh.py` khud isse refresh karta rahega aur wapas commit karta
rahega.

```
git add token.json
git commit -m "Add initial token"
git push
```

---

## 6) Confirm karo

Repo -> **Actions** tab -> "Reel Pipeline" workflow -> **Run workflow**
(manual trigger) se ek test run kar lo. Log me dikhega: Drive se naye
files aaye, Supabase pe upload hue, Instagram pe publish hua, aur DB
wapas commit ho gaya.

Uske baad ye har ghante khud-ba-khud chalega (`pipeline.yml`), aur token
refresh roz check hoga (`token_refresh.yml`) -- kuch bhi manually chalane
ki zaroorat nahi.

---

## Dhyan rakhne wali baatein

- **Rate limit**: `reels_per_day` (abhi 16) Meta ke 25/24h cap ke andar
  hai -- change mat karo bina wajah ke.
- **Storage quota**: Supabase free tier 1GB deta hai -- publish ke baad
  file khud delete ho jaati hai (`uploader.cleanup()`), isliye 100 reels
  ke liye bhi kaafi hai.
- **Agar koi reel fail ho** -- `database/instagram.db` me status
  `'failed'` dikhega, `error_message` column me wajah bhi. Agli run me
  woh phir se retry nahi hoga automatically abhi -- chaho to bata dena,
  ek retry-script bana denge.
